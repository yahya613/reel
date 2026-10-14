"""Auto-sync subtitles to the dialogue — no extra installs.

Reel listens to a few minutes of the movie through a throwaway libmpv instance (the dialogue channel of 5.1
audio, speech band only, 8 kHz) and marks every 20 ms where someone is talking. Then it slides the subtitle
timeline — trying the usual frame-rate stretches too (23.976 / 24 / 25 fps) — to where subtitles and talking
line up best. It only answers when the match clearly stands out; otherwise it says it isn't sure.
The answer is two numbers mpv already understands:  shown_at = speed * subtitle_time + delay
(`sub-speed`, `sub-delay`).

Tuned on real episodes with their own subtitles shifted / stretched / swapped for another episode:
right answers score 4.3-7, wrong subtitles never above 3.9.
"""
import os, re, sys, math, time, array, shutil, tempfile, threading, subprocess, statistics, urllib.request
from operator import mul

RATE = 8000
FINE = 0.02                 # seconds per 'talking?' decision
SUB = 5                     # FINE frames per matching step  -> 0.1 s
STEP = FINE * SUB
MAX_SHIFT = 120.0           # look up to 2 minutes either way
SPEEDS = (1.0, 25 / 23.976, 23.976 / 25, 25 / 24, 24 / 25)
MIN_SCORE = 4.3             # sharpness of the best match (std-devs)
MIN_RATIO = 1.25            # ...and how far it beats the runner-up more than 1 s away
TEXT_CODECS = ('subrip', 'srt', 'ass', 'ssa', 'webvtt', 'mov_text', 'text')

SRT_TIME = re.compile(r'(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})\s*-->\s*(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})')
ASS_LINE = re.compile(r'^Dialogue:\s*[^,]*,(\d+):(\d+):(\d+)[.](\d+),(\d+):(\d+):(\d+)[.](\d+),', re.M)


class Cancelled(Exception):
    pass


# ------------------------------------------------------------------ subtitles
def _secs(h, m, s, frac):
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(frac.ljust(3, '0')[:3]) / 1000


def parse(text):
    """[(start, end)] in seconds from SRT / VTT / ASS text."""
    out = []
    if '[Events]' in text or 'Dialogue:' in text:
        for g in ASS_LINE.findall(text):
            out.append((_secs(*g[:4]), _secs(*g[4:])))
    else:
        for g in SRT_TIME.findall(text):
            out.append((_secs(*g[:4]), _secs(*g[4:])))
    return sorted((a, b) for a, b in out if b > a and b - a < 30)


def decode(data):
    for enc in ('utf-8-sig', 'utf-16') if data[:2] in (b'\xff\xfe', b'\xfe\xff') else ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode('latin-1', 'replace')


def read_text(src, timeout=20):
    if re.match(r'https?://', src or ''):
        with urllib.request.urlopen(src, timeout=timeout) as r:
            return decode(r.read())
    with open(src, 'rb') as f:
        return decode(f.read())


def ffmpeg_path():
    for p in (shutil.which('ffmpeg') or '', '/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg'):
        if p and os.path.isfile(p):
            return p
    return None


def extract_embedded(video, ff_index, timeout=300):
    """Pull an embedded text subtitle track out as SRT (needs ffmpeg; reads the whole file)."""
    exe = ffmpeg_path()
    if not exe:
        return None
    flags = 0x08000000 if os.name == 'nt' else 0
    r = subprocess.run([exe, '-v', 'error', '-nostdin', '-i', video, '-map', f'0:{ff_index}', '-f', 'srt', '-'],
                       capture_output=True, timeout=timeout, creationflags=flags)
    return decode(r.stdout) if r.returncode == 0 and r.stdout else None


# ------------------------------------------------------------------ listening
def listen(src, start, dur, aid=None, center=False, cancel=None):
    """Decode [start, start+dur) of the audio and return 'talking' flags, one per FINE frame."""
    import mpv
    fd, raw = tempfile.mkstemp(suffix='.pcm', prefix='reel-sync-')
    os.close(fd)
    done = threading.Event()
    band = 'highpass=f=200,lowpass=f=3400'
    m = mpv.MPV(vid='no', sid='no', ao='pcm', ao_pcm_file=raw, ao_pcm_waveheader='no', audio_format='s16',
                audio_samplerate=RATE, audio_channels='mono', untimed='yes', start=f'{start:.2f}',
                end=f'{start + dur:.2f}', af=f'lavfi=[pan=mono|c0=FC,{band}]' if center else f'lavfi=[{band}]',
                aid=str(aid or 'auto'), config='no', load_scripts='no', ytdl='no', terminal='no',
                input_default_bindings='no', idle='no', keep_open='no', cache='yes', demuxer_max_bytes='64MiB')
    try:
        @m.event_callback('end-file')
        def _end(ev):
            done.set()

        @m.event_callback('shutdown')
        def _shut(ev):
            done.set()
        m.play(src)
        t0 = time.time()
        while not done.wait(0.25):
            if cancel and cancel.is_set():
                raise Cancelled()
            if time.time() - t0 > 300:
                raise TimeoutError('listening took too long')
    finally:
        try:
            m.terminate()
        except Exception:
            pass
    try:
        a = array.array('h')
        with open(raw, 'rb') as f:
            a.frombytes(f.read())
    finally:
        try:
            os.remove(raw)
        except OSError:
            pass
    if sys.byteorder == 'big':
        a.byteswap()
    step = int(RATE * FINE)
    n = len(a) // step
    if n < 50:
        return []
    energy = [math.log10(1 + sum(map(mul, fr, fr)) / step) for fr in (a[i * step:(i + 1) * step] for i in range(n))]
    srt = sorted(energy)
    lo, hi = srt[int(n * .15)], srt[int(n * .97)]
    if hi - lo < .2:                  # silence (e.g. no centre channel after all)
        return []
    thr = lo + (hi - lo) * .5
    return [e > thr for e in energy]


# ------------------------------------------------------------------ matching
def _bits(flags):
    """[bool] -> int with bit i == flags[i]."""
    if not flags:
        return 0
    return int(''.join('1' if f else '0' for f in reversed(flags)), 2)


def _ranges_bits(ranges, t0, n, fr):
    """Subtitle 'on' bits for steps covering [t0, t0 + n*fr)."""
    if n <= 0:
        return 0
    buf = bytearray(b'0' * n)
    for a, b in ranges:
        i, j = max(0, int((a - t0) / fr)), min(n, int(math.ceil((b - t0) / fr)))
        if j > i:
            buf[i:j] = b'1' * (j - i)
    buf.reverse()
    return int(buf, 2)


def _curve(windows, subs, speed, K):
    """Covariance of 'subtitle on' vs 'talking' for every delay -K..K steps (summed over windows)."""
    tot = [0.0] * (2 * K + 1)
    scaled = [(a * speed, b * speed) for a, b in subs]
    for w0, flags in windows:
        n = len(flags) // SUB
        if n < 10:
            continue
        planes = [_bits(flags[p:n * SUB:SUB]) for p in range(SUB)]     # talking-ness 0..5 per step
        mean = sum(flags[:n * SUB]) / n
        mask = (1 << n) - 1
        ext = _ranges_bits(scaled, w0 - K * STEP, n + 2 * K, STEP)    # zero-delay subtitles, padded both sides
        for idx in range(2 * K + 1):                                   # delay = idx - K steps
            s = (ext >> (2 * K - idx)) & mask
            tot[idx] += sum((pl & s).bit_count() for pl in planes) - mean * s.bit_count()
    return tot


def _peak(c, w=int(round(4 / STEP)), ex=int(round(1 / STEP))):
    """Best delay by sharpness (curve minus its 4 s moving average) -> (index, score, ratio vs runner-up)."""
    n = len(c)
    pre = [0.0]
    for x in c:
        pre.append(pre[-1] + x)
    hp = [c[i] - (pre[min(n, i + w // 2)] - pre[max(0, i - w // 2)]) / w for i in range(n)]
    i = max(range(w, n - w), key=hp.__getitem__)
    mu, sd = statistics.fmean(hp), statistics.pstdev(hp) or 1e-9
    rest = max(hp[j] for j in range(n) if abs(j - i) > ex)
    return i, (hp[i] - mu) / sd, hp[i] / rest if rest > 0 else 9.9


def align(windows, subs, speeds=SPEEDS, max_shift=MAX_SHIFT):
    """windows: [(video_start_seconds, [talking per FINE frame])]. Returns (delay, speed, score, ratio)."""
    K = int(round(max_shift / STEP))
    best = None
    for sp in speeds:
        i, z, ratio = _peak(_curve(windows, subs, sp, K))
        if best is None or z > best[2]:
            best = ((i - K) * STEP, sp, z, ratio)
    return best


def plan(duration, remote=False):
    """Where to listen: windows spread through the movie (shorter when streaming, to save data)."""
    wl = 240 if remote else 480
    if not duration or duration < 3 * wl + 120:
        return [(0.0, min(duration or 1200, 1500))]
    return [(max(0.0, duration * f - wl / 2), wl) for f in (.2, .5, .8)]


def auto_sync(video, sub_text, duration, aid=None, channels=2, remote=False, speeds=SPEEDS, cancel=None,
              progress=None):
    """Full pipeline -> {'delay', 'speed', 'score', 'ratio', 'ok'}. ok=False means 'not sure, leave it alone'."""
    subs = parse(sub_text)
    if len(subs) < 20:
        raise ValueError('not enough subtitle lines to match')
    spots = plan(duration, remote)
    center = (channels or 0) >= 6     # 5.1+: dialogue lives in the centre channel
    windows = []
    for n, (start, dur) in enumerate(spots):
        if progress:
            progress(n, len(spots))
        flags = listen(video, start, dur, aid, center, cancel)
        if not flags and center:      # no usable centre channel: use the full mix
            center = False
            flags = listen(video, start, dur, aid, False, cancel)
        windows.append((start, flags))
    if sum(len(f) for _, f in windows) < 3000:
        raise ValueError('could not read the audio')
    delay, speed, score, ratio = align(windows, subs, speeds)
    return {'delay': round(delay, 2), 'speed': speed, 'score': round(score, 1), 'ratio': round(ratio, 2),
            'ok': score >= MIN_SCORE and ratio >= MIN_RATIO}
