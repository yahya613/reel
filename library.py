"""Library: scanning folders, parsing release names, progress + settings storage."""
import os, re, sys, json, time, hashlib, threading, tempfile, posixpath
from dataclasses import dataclass, field

VIDEO_EXT = {'.mkv', '.mp4', '.m4v', '.avi', '.mov', '.webm', '.wmv', '.ts', '.m2ts', '.mts',
             '.mpg', '.mpeg', '.flv', '.ogv', '.3gp', '.divx', '.vob', '.rmvb'}
SUB_EXT = {'.srt', '.ass', '.ssa', '.vtt', '.sub', '.idx', '.sup'}
SKIP_DIRS = {'node_modules', '$recycle.bin', 'system volume information', '__pycache__', 'site-packages',
             'appdata', 'windows', 'windows.old', 'program files', 'program files (x86)', 'programdata',
             'recovery', 'perflogs', 'msocache', 'windowsapps', 'onedrivetemp', 'temp', 'tmp', 'cache',
             'steamapps', 'steamlibrary', 'epic games', 'xboxgames', 'riot games', 'battle.net', 'ea games',
             'origin games', 'gog games', 'ubisoft game launcher', 'rockstar games', 'minecraftserver',
             'library', 'applications', 'system', 'private', 'opt', 'usr', 'bin', 'proc', 'dev', 'snap'}
PACKAGE_DIRS = ('.app', '.photoslibrary', '.imovielibrary', '.fcpbundle', '.tvlibrary', '.musiclibrary', '.bundle',
                '.framework', '.photolibrary', '.aplibrary')  # macOS bundles that look like folders
ROOT_ONLY_SKIP = {'library', 'applications', 'system', 'private', 'opt', 'usr', 'bin', 'proc', 'dev', 'snap'}


def all_drives():
    """Every local + removable drive (no network/optical), or / on mac/linux."""
    if os.name != 'nt':
        vols = ['/Volumes/' + v for v in os.listdir('/Volumes')] if os.path.isdir('/Volumes') else []
        return [os.path.expanduser('~')] + [v for v in vols if not os.path.islink(v)]
    import ctypes, string
    mask, out = ctypes.windll.kernel32.GetLogicalDrives(), []
    for i, letter in enumerate(string.ascii_uppercase):
        if mask >> i & 1:
            root = f'{letter}:' + os.sep
            if ctypes.windll.kernel32.GetDriveTypeW(root) in (2, 3):  # removable, fixed
                out.append(root)
    return out

if sys.platform == 'darwin':
    DATA_DIR = os.path.expanduser('~/Library/Application Support/Reel')
else:
    DATA_DIR = os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~/.config'), 'Reel')
THUMB_DIR = os.path.join(DATA_DIR, 'thumbs')
os.makedirs(THUMB_DIR, exist_ok=True)

# ---------------------------------------------------------------- name parsing

QUALITY = re.compile(
    r'\b(2160p|1440p|1080p|1080i|720p|576p|480p|4k|uhd|hdr10\+?|hdr|dv|dovi|sdr|'
    r'web[ .-]?dl|web[ .-]?rip|webrip|web|blu[ .-]?ray|bdrip|brrip|bdremux|remux|dvdrip|dvdscr|hdtv|hdrip|'
    r'x264|x265|h[ .]?264|h[ .]?265|hevc|avc|av1|xvid|divx|10bit|8bit|hi10p?|'
    r'aac(?:2[ .]0)?|ac3|eac3|e-ac-3|dts(?:-hd)?|truehd|atmos|flac|opus|ddp?(?:[ .]?[257][ .]1)?|'
    r'proper|repack|extended|unrated|uncut|remastered|imax|internal|limited|complete|'
    r'multi|dual[ .-]?audio|dubbed|subbed|multisub|esub|hc|'
    r'amzn|nf|dsnp|hmax|max|hulu|atvp|pcok|pmtp|cr|'
    r'yify|yts(?:\.\w+)?|rarbg|galaxytv|tgx|eztv|psa|qxr|tigole|ettv)\b', re.I)
EP_PATTERNS = [
    re.compile(r'\bS(\d{1,2})[ ._-]*E(\d{1,3})(?:[ ._-]*-?[ ._-]*E?(\d{1,3}))?\b', re.I),
    re.compile(r'\b(\d{1,2})x(\d{2,3})\b', re.I),
    re.compile(r'\bSeason[ ._-]*(\d{1,2})[ ._-]*Episode[ ._-]*(\d{1,3})\b', re.I),
]
ANIME_EP = re.compile(r'\s-\s(\d{1,4})(?:v\d)?(?=\s|$|\[|\()')
SEASON_DIR = re.compile(r'^(?:season|series|s)[ ._-]*(\d{1,2})\b', re.I)
ANIME_SEASON = re.compile(r'\s(?:(\d)(?:st|nd|rd|th) Season|Season (\d{1,2})|S(\d{1,2}))$', re.I)
BARE_EP = re.compile(r'^(?:e|ep|episode)?[ ._-]*(\d{1,3})\b', re.I)
YEAR = re.compile(r'(?<!\d)(19[2-9]\d|20[0-4]\d)(?!\d)')
PERSONAL = re.compile(
    r'(?<!\d)(?:19|20)\d{2}[-_. ]?(?:0[1-9]|1[0-2])[-_. ]?(?:0[1-9]|[12]\d|3[01])(?!\d)'   # 2026-01-05 / 20260105
    r'|^(?:img|vid|pxl|mvi|dji|gopr|gp\d|dsc|screen ?recording|screen ?capture|recording|capture|clip|replay|'
    r'untitled|video|movie|new video|medaltv|obs|bandicam|fraps|shadowplay|desktop)', re.I)
RES = re.compile(r'\b(2160p|4k|uhd|1080p|1080i|720p|576p|480p)\b', re.I)


def clean(s):
    s = re.sub(r'\[[^\]]*\]|\{[^}]*\}', ' ', s)          # [group] {tags}
    s = re.sub(r'(?<=\w)\.(?=\w)|_', ' ', s)              # dots/underscores -> spaces
    s = s.replace('.', ' ')
    s = re.sub(r'\(\s*\)', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip(' -–—:,.([')
    if s and (s.islower() or s.isupper()):
        s = ' '.join(w[:1].upper() + w[1:].lower() if len(w) > 2 or i == 0 else w.lower()
                     for i, w in enumerate(s.split()))
    return s


def cut_quality(s):
    m = QUALITY.search(s)
    return s[:m.start()] if m else s


def norm_key(name):
    s = re.sub(r'\(?\b(19|20)\d{2}\b\)?', ' ', name.lower())
    s = s.replace('&', 'and')
    return re.sub(r'[^a-z0-9]+', '', s)


def quality_of(name):
    m = RES.search(name)
    q = ''
    if m:
        r = m.group(1).lower()
        q = '4K' if r in ('2160p', '4k', 'uhd') else r.replace('1080i', '1080p')
    if re.search(r'\bhdr10\+?|\bhdr\b|\bdv\b|dovi|dolby[ .]?vision', name, re.I):
        q = (q + ' HDR').strip()
    return q


@dataclass
class Item:
    path: str
    kind: str                # 'movie' | 'episode'
    title: str               # movie title, or show name for episodes
    year: int = 0
    season: int = 0
    episode: int = 0
    episode_end: int = 0
    ep_title: str = ''
    quality: str = ''
    size: int = 0
    added: float = 0.0
    key: str = ''
    show_key: str = ''
    release: bool = False
    remote: str = ''        # name of the computer this streams from ('' = on this computer)
    src: str = ''           # stream URL for remote items

    @property
    def code(self):
        if self.kind != 'episode':
            return ''
        e = f'E{self.episode}' + (f'–{self.episode_end}' if self.episode_end else '')
        return f'S{self.season} {e}' if self.season else e

    @property
    def display(self):
        if self.kind == 'episode':
            return f'{self.title} · {self.code}'
        return f'{self.title} ({self.year})' if self.year else self.title

    @property
    def ep_name(self):
        return self.ep_title or f'Episode {self.episode}'


def path_key(p):
    return os.path.normcase(os.path.abspath(p))


def parse(path, size=0, added=0.0):
    p = path.replace('\\', '/')
    base = posixpath.splitext(posixpath.basename(p))[0].replace('_', ' ')
    parent = posixpath.basename(posixpath.dirname(p)).replace('_', ' ')
    grand = posixpath.basename(posixpath.dirname(posixpath.dirname(p))).replace('_', ' ')
    it = Item(path=path, kind='movie', title='', size=size, added=added, key=path_key(path),
              quality=quality_of(base) or quality_of(parent))

    # --- episodes: S01E02 / 1x02 / Season 1 Episode 2
    for pat in EP_PATTERNS:
        m = pat.search(base)
        if m:
            it.kind = 'episode'
            it.season, it.episode = int(m.group(1)), int(m.group(2))
            if m.lastindex and m.lastindex >= 3 and m.group(3):
                end = int(m.group(3))
                it.episode_end = end if end > it.episode and end - it.episode < 5 else 0
            show = clean(cut_quality(base[:m.start()]))
            it.ep_title = clean(cut_quality(base[m.end():]))
            break
    else:
        m = ANIME_EP.search(clean_brackets_keep(base))
        sd = SEASON_DIR.match(parent)
        if m and not YEAR.fullmatch(m.group(1)):
            b = clean_brackets_keep(base)
            it.kind, it.season, it.episode = 'episode', 1, int(m.group(1))
            show = clean(b[:m.start()])
            it.ep_title = clean(cut_quality(b[m.end():]))
        elif sd and BARE_EP.match(base):
            it.kind, it.season, it.episode = 'episode', int(sd.group(1)), int(BARE_EP.match(base).group(1))
            show = ''
            it.ep_title = clean(cut_quality(base[BARE_EP.match(base).end():]))
        else:
            show = None

    if it.kind == 'episode':
        if not show:  # name comes from folders: Show/Season 1/E01.mkv or Show.S01/S01E01.mkv
            folder = grand if SEASON_DIR.match(parent) else parent
            fm = EP_PATTERNS[0].search(folder) or re.search(r'\bS\d{1,2}\b|\bSeason\b', folder, re.I)
            show = clean(cut_quality(folder[:fm.start()] if fm else folder))
        ym = YEAR.search(show or '')
        if ym and ym.start() > 0:
            it.year = int(ym.group(1))
            show = clean(show[:ym.start()])
        sm = ANIME_SEASON.search(show or '')
        if sm and sm.start() > 0:  # "Jujutsu Kaisen 2nd Season - 05" / "Show S2 - 05"
            if it.season <= 1:
                it.season = int(sm.group(1) or sm.group(2) or sm.group(3))
            show = clean(show[:sm.start()])
        it.title = show or 'Unknown show'
        if it.ep_title and (norm_key(it.ep_title) == norm_key(it.title) or len(it.ep_title) < 2):
            it.ep_title = ''
        it.show_key = norm_key(it.title) or it.title.lower()
        return it

    # --- personal clips (phone/screen recordings, game clips) are never movies
    if PERSONAL.search(base):
        it.kind, it.title = 'video', re.sub(r'\s+', ' ', base).strip()
        return it

    # --- movies: Title.Year.quality  (release tokens or "(Year)" make it a confident match)
    it.release = bool(QUALITY.search(base) or QUALITY.search(parent) or re.search(r'[(\[](19|20)\d{2}[)\]]', base + parent))
    name = base
    generic = len(re.sub(r'[^a-z]', '', base.lower())) < 4 or base.lower() in ('movie', 'video', 'film')
    if generic and parent:
        name = parent
    s = re.sub(r'\[[^\]]*\]', ' ', name)
    years = [m for m in YEAR.finditer(s) if m.start() > 0 and int(m.group(1)) <= time.localtime().tm_year + 1]
    if years:
        y = years[-1]
        it.year = int(y.group(1))
        title = s[:y.start()]
    else:
        title = cut_quality(s)
    it.title = clean(title) or clean(name) or base
    if not it.year and not it.release:
        it.kind, it.title = 'video', re.sub(r'\s+', ' ', base).strip()
    return it


def clean_brackets_keep(s):
    s = re.sub(r'\[[^\]]*\]|\([^)]*\)', ' ', s)
    s = re.sub(r'_', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


# ---------------------------------------------------------------- library

@dataclass
class Show:
    key: str
    name: str
    year: int = 0
    episodes: list = field(default_factory=list)

    @property
    def seasons(self):
        return sorted({e.season for e in self.episodes})

    @property
    def added(self):
        return max((e.added for e in self.episodes), default=0)


class Library:
    def __init__(self):
        self.items, self.movies, self.videos, self.shows, self.by_key = [], [], [], {}, {}

    def scan(self, roots, min_mb=40, hidden=(), progress=None, cancel=None):
        found, hidden = {}, set(hidden)
        min_bytes = min_mb * 1024 * 1024
        dirs, last = 0, time.time()
        skip_paths = {path_key(DATA_DIR)}
        for root in roots:
            if not os.path.isdir(root):
                continue
            top = len(os.path.abspath(root).rstrip('\\/').split(os.sep))
            stack = [root]
            while stack:
                if cancel and cancel():
                    return None
                d = stack.pop()
                dirs += 1
                if progress and time.time() - last > 0.25:
                    last = time.time()
                    progress(dirs, len(found), d)
                try:
                    entries = list(os.scandir(d))
                except OSError:
                    continue
                depth = len(d.rstrip('\\/').split(os.sep)) - top
                for e in entries:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            n = e.name.lower()
                            if n.startswith(('.', '$', '~')) or n in SKIP_DIRS and (depth == 0 or n not in ROOT_ONLY_SKIP):
                                continue
                            if path_key(e.path) in skip_paths or n.endswith(PACKAGE_DIRS):
                                continue
                            stack.append(e.path)
                        elif os.path.splitext(e.name)[1].lower() in VIDEO_EXT:
                            st = e.stat()
                            if st.st_size < min_bytes:
                                continue
                            low = e.name.lower()
                            if ('sample' in low or 'trailer' in low) and st.st_size < 400 * 1024 * 1024:
                                continue
                            k = path_key(e.path)
                            if k not in found and k not in hidden:
                                it = parse(e.path, st.st_size, getattr(st, 'st_birthtime', st.st_ctime))
                                if it.kind != 'video':
                                    found[k] = it
                    except OSError:
                        continue
        self.set_items(list(found.values()))
        return self

    def save_cache(self):
        from dataclasses import asdict
        f = JsonFile('library.json', [])
        f.data = [asdict(i) for i in self.items if not i.remote]
        f.save()

    def load_cache(self):
        try:
            data = JsonFile('library.json', []).data  # re-parse so naming fixes apply without a rescan
            items = [parse(d['path'], d.get('size', 0), d.get('added', 0)) for d in data if os.path.exists(d['path'])]
            self.set_items([i for i in items if i.kind != 'video'])
            return bool(self.items)
        except Exception:
            return False

    def set_items(self, items):
        self.items = items
        self.by_key = {i.key: i for i in items}
        self.movies = sorted((i for i in items if i.kind == 'movie'), key=lambda i: i.title.lower())
        self.videos = [i for i in items if i.kind == 'video']
        shows = {}
        for i in items:
            if i.kind != 'episode':
                continue
            s = shows.get(i.show_key)
            if not s:
                s = shows[i.show_key] = Show(i.show_key, i.title, i.year)
            s.episodes.append(i)
        for s in shows.values():
            s.episodes.sort(key=lambda e: (e.season, e.episode, e.path.lower()))
            dedup, seen = [], set()
            for e in s.episodes:  # same episode in two qualities: keep the bigger file
                k = (e.season, e.episode)
                if k in seen:
                    prev = dedup[-1]
                    if e.size > prev.size:
                        dedup[-1] = e
                    continue
                seen.add(k)
                dedup.append(e)
            s.episodes = dedup
            s.year = next((e.year for e in s.episodes if e.year), 0)
        self.shows = dict(sorted(shows.items(), key=lambda kv: kv[1].name.lower()))

    @property
    def local_items(self):
        return [i for i in self.items if not i.remote]

    def find(self, path):
        return self.by_key.get(path_key(path))

    def show_of(self, item):
        return self.shows.get(item.show_key) if item and item.kind == 'episode' else None

    def neighbour(self, item, step):
        show = self.show_of(item)
        eps = show.episodes if show else sibling_episodes(item)
        keys = [e.key for e in eps]
        if item.key in keys:
            j = keys.index(item.key) + step
            if 0 <= j < len(eps):
                return eps[j]
        return None

    def recent(self, n=24):
        return sorted(self.items, key=lambda i: -i.added)[:n]


def sibling_episodes(item):
    """For a file opened directly (not in the library): its episode siblings in the same folder."""
    if not item or item.kind != 'episode':
        return []
    d = os.path.dirname(item.path)
    try:
        names = os.listdir(d)
    except OSError:
        return []
    eps = [parse(os.path.join(d, n)) for n in names if os.path.splitext(n)[1].lower() in VIDEO_EXT]
    eps = [e for e in eps if e.kind == 'episode' and e.show_key == item.show_key]
    return sorted(eps, key=lambda e: (e.season, e.episode))


# ---------------------------------------------------------------- persistence

class JsonFile:
    def __init__(self, name, default):
        self.path = os.path.join(DATA_DIR, name)
        self.lock = threading.Lock()
        try:
            with open(self.path, encoding='utf-8') as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = default

    def save(self):
        with self.lock:
            fd, tmp = tempfile.mkstemp(dir=DATA_DIR, suffix='.tmp')
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)


class Store:
    def __init__(self):
        self.on_change = None  # set by the cloud sync
        self.settings = JsonFile('settings.json', {})
        self.progress = JsonFile('progress.json', {})
        self.meta = JsonFile('meta.json', {})
        s = self.settings.data
        seed = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'seed.json')
        if os.path.exists(seed):
            try:
                for k, v in json.load(open(seed, encoding='utf-8')).items():
                    s.setdefault(k, v)
            except ValueError:
                pass
        s.setdefault('scan_all', True)       # scan every drive on the computer
        s.setdefault('folders', [])          # extra folders (network shares etc.)
        s.setdefault('hidden', [])           # files removed from the library by the user
        s.setdefault('online', True)         # fetch posters/plots from Cinemeta
        s.setdefault('min_mb', 40)
        s.setdefault('volume', 100)
        s.setdefault('sub_scale', 1.0)
        s.setdefault('track_prefs', {})
        self.settings.save()

    def roots(self):
        s = self.settings.data
        r = list(all_drives()) if s.get('scan_all', True) else []
        for f in s.get('folders', []):
            if not any(path_key(f).startswith(path_key(x)) for x in r):
                r.append(f)
        return r

    # progress ---------------------------------------------------------
    def get(self, item):
        return self.progress.data.get(item.key, {})

    def watched(self, item):
        return bool(self.get(item).get('watched'))

    def fraction(self, item):
        p = self.get(item)
        if p.get('watched'):
            return 1.0
        d = p.get('dur') or self.duration(item)
        return min(1.0, p.get('pos', 0) / d) if d else 0.0

    def resume_pos(self, item):
        p = self.get(item)
        return 0 if p.get('watched') else p.get('pos', 0)

    def set_progress(self, item, pos, dur):
        if not dur or pos is None:
            return
        left = dur - pos
        done = left < max(60, min(dur * 0.08, 600))
        rec = self.progress.data.setdefault(item.key, {})
        rewatching = rec.get('watched') and pos < 30
        rec.update(pos=0 if done else round(pos, 1), dur=round(dur, 1), t=time.time(),
                   watched=bool(done or rewatching))
        self.meta.data.setdefault(item.key, {})['dur'] = round(dur, 1)
        if self.on_change:
            self.on_change(item)

    def set_watched(self, item, watched):
        rec = self.progress.data.setdefault(item.key, {})
        rec.update(watched=watched, pos=0, t=time.time())
        self.progress.save()
        if self.on_change:
            self.on_change(item)

    def duration(self, item):
        return self.meta.data.get(item.key, {}).get('dur', 0)

    # continue watching -------------------------------------------------
    def continue_watching(self, lib, n=12):
        latest = {}
        for k, rec in self.progress.data.items():
            it = lib.by_key.get(k)
            if not it:
                continue
            group = it.show_key if it.kind == 'episode' else it.key
            if group not in latest or rec.get('t', 0) > latest[group][1].get('t', 0):
                latest[group] = (it, rec)
        out = []
        for it, rec in sorted(latest.values(), key=lambda v: -v[1].get('t', 0)):
            if rec.get('watched'):
                nxt = lib.neighbour(it, 1) if it.kind == 'episode' else None
                while nxt and self.watched(nxt):
                    nxt = lib.neighbour(nxt, 1)
                if nxt:
                    out.append((nxt, 'next'))
            elif rec.get('pos', 0) > 15:
                out.append((it, 'resume'))
            if len(out) >= n:
                break
        return out

    def up_next(self, show):
        """Episode to play when hitting Play on a show: in-progress one, else first unwatched."""
        best, best_t = None, -1
        for e in show.episodes:
            rec = self.get(e)
            if rec.get('t', 0) > best_t and (rec.get('pos', 0) > 15 or rec.get('watched')):
                best, best_t = e, rec['t']
        if best is None:
            return next((e for e in show.episodes if not self.watched(e)), show.episodes[0])
        if not self.watched(best):
            return best
        i = show.episodes.index(best)
        for e in show.episodes[i + 1:] + show.episodes[:i]:
            if not self.watched(e):
                return e
        return show.episodes[0]


def thumb_path(item):
    h = hashlib.sha1(f'{item.key}|{item.size}'.encode()).hexdigest()[:20]
    return os.path.join(THUMB_DIR, h + '.jpg')


def fmt_time(t):
    t = int(max(0, t or 0))
    h, m, s = t // 3600, t // 60 % 60, t % 60
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'


def fmt_dur(t):
    t = int(t or 0)
    if not t:
        return ''
    h, m = t // 3600, round(t % 3600 / 60)
    if m == 60:
        h, m = h + 1, 0
    return f'{h}h {m}m' if h else f'{m}m'


def fmt_size(b):
    return f'{b / 1024**3:.1f} GB' if b >= 1024**3 else f'{b / 1024**2:.0f} MB'
