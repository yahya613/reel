"""Download movies & episodes from your other computers onto this one, so they play offline.

Pick titles, they go in a queue, and Reel pulls them one at a time in the background from your own
Reels (same account, through their token-gated media server). The queue survives restarts
(settings['downloads']) and a stopped download picks up where it left off (.part file + Range).
"""
import os, re, json, time, shutil, threading, urllib.parse, urllib.request
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from cloud import sync_id
from server import safe_name

CHUNK = 1024 * 1024
KEEP_FREE = 2 * 1024**3       # never fill the disk: leave this much free
TRIES = 6


class Cancelled(Exception):
    pass


def folder_name(s):
    return re.sub(r'[\\/:*?"<>|]', '', s or '').strip().strip('.')[:80] or 'Show'


def remote_basename(path):
    """The other computer may be Windows or Mac, so split on both separators."""
    return safe_name(re.split(r'[\\/]', path or '')[-1])


class Downloads(QObject):
    changed = pyqtSignal()        # queue or progress changed
    finished = pyqtSignal(str)    # a file finished downloading (its path on this computer)

    def __init__(self, store, dest_dir):
        super().__init__()
        self.store = store
        self.dest_dir = dest_dir          # callable -> folder downloads go into
        self.items = {}                   # sync_id -> remote Item (refreshed every sync; URLs can change)
        self.lock = threading.Lock()
        self.running = False
        self.cancel = set()
        self.rate = 0.0                   # bytes/s of the current download
        self._dirty = False
        self.save_timer = QTimer(self, singleShot=True, interval=4000, timeout=self.save)
        self.changed.connect(self._on_changed)
        for d in self.queue:              # app was closed mid-download: it resumes from the .part file
            if d.get('state') == 'downloading':
                d['state'] = 'queued'

    # ---------------------------------------------------------------- queue
    @property
    def queue(self):
        return self.store.settings.data.setdefault('downloads', [])

    def entry(self, item_or_id):
        sid = item_or_id if isinstance(item_or_id, str) else sync_id(item_or_id)
        return next((d for d in self.queue if d['id'] == sid), None)

    def active(self):
        return [d for d in self.queue if d.get('state') in ('queued', 'downloading')]

    def set_remote(self, items):
        self.items = {sync_id(i): i for i in items if i.remote and i.src}
        self.kick()
        self.changed.emit()

    def add(self, items, name_of=None):
        """Queue remote titles. Returns how many were newly queued."""
        n = 0
        for it in items:
            if not it.remote or it.kind not in ('movie', 'episode'):
                continue
            d = self.entry(it)
            if d:
                if d['state'] == 'failed':
                    d.update(state='queued', error='', tries=0)
                    n += 1
                continue
            title = name_of(it) if name_of else it.display
            self.queue.append({'id': sync_id(it), 'name': title, 'kind': it.kind,
                               'show': it.title if it.kind == 'episode' else '',
                               'file': remote_basename(it.path), 'size': it.size or 0, 'got': 0,
                               'state': 'queued', 'from': it.remote, 'error': '', 'tries': 0, 'added': time.time()})
            n += 1
        if n:
            self.save()
            self.kick()
            self.changed.emit()
        return n

    def remove(self, sid):
        d = self.entry(sid)
        if not d:
            return
        if d['state'] == 'downloading':
            self.cancel.add(sid)          # the worker deletes the .part and drops the entry
            return
        if d['state'] != 'done':
            self._drop_part(d)
        self.queue.remove(d)
        self.save()
        self.changed.emit()

    def retry(self, sid):
        d = self.entry(sid)
        if d and d['state'] == 'failed':
            d.update(state='queued', error='', tries=0)
            self.save()
            self.kick()
            self.changed.emit()

    def clear_done(self):
        self.store.settings.data['downloads'] = [d for d in self.queue if d['state'] != 'done']
        self.save()
        self.changed.emit()

    def forget_missing(self):
        """Downloaded files that were deleted/moved later shouldn't stay listed as 'done'."""
        before = len(self.queue)
        self.store.settings.data['downloads'] = [d for d in self.queue
                                                 if d['state'] != 'done' or os.path.exists(d.get('path', ''))]
        if len(self.queue) != before:
            self.save()

    def save(self):
        self.store.settings.save()

    def _on_changed(self):            # main thread: persist progress every few seconds, not every chunk
        if any(d.get('state') == 'cancelled' for d in self.queue):
            self.store.settings.data['downloads'] = [d for d in self.queue if d.get('state') != 'cancelled']
        if not self.save_timer.isActive():
            self.save_timer.start()

    # ---------------------------------------------------------------- worker
    def kick(self):
        with self.lock:
            if self.running or not self._next():
                return
            self.running = True
        threading.Thread(target=self._run, daemon=True).start()

    def _next(self):
        return next((d for d in list(self.queue) if d.get('state') == 'queued' and d['id'] in self.items), None)

    def _run(self):
        try:
            while True:
                d = self._next()
                if not d:
                    break
                it = self.items.get(d['id'])
                if it:
                    self._fetch(d, it)
        finally:
            with self.lock:
                self.running = False
            self.rate = 0.0
            self.changed.emit()
        self.kick()  # something may have been queued while we were finishing

    def _target(self, d):
        folder = self.dest_dir()
        if d['kind'] == 'episode':
            folder = os.path.join(folder, folder_name(d.get('show')))
        return folder, os.path.join(folder, d['file'] or 'video.mkv')

    def _drop_part(self, d):
        try:
            os.remove(self._target(d)[1] + '.part')
        except OSError:
            pass

    def _fetch(self, d, it):
        folder, dest = self._target(d)
        part = dest + '.part'
        try:
            os.makedirs(folder, exist_ok=True)
            if os.path.exists(dest) and (not d['size'] or os.path.getsize(dest) == d['size']):
                return self._done(d, dest, it)
            got = os.path.getsize(part) if os.path.exists(part) else 0
            free = shutil.disk_usage(folder).free
            if d['size'] and d['size'] - got > free - KEEP_FREE:
                d.update(state='failed', error=f'Not enough space — needs {d["size"] / 1024**3:.1f} GB, '
                                               f'{max(0, free - KEEP_FREE) / 1024**3:.1f} GB free')
                return
            d.update(state='downloading', error='')
            self.changed.emit()
            req = urllib.request.Request(it.src, headers={'Range': f'bytes={got}-'} if got else {})
            with urllib.request.urlopen(req, timeout=30) as r:
                if got and r.status != 206:   # server ignored the range: start over
                    got = 0
                total = got + int(r.headers.get('Content-Length') or 0)
                if total and not d['size']:
                    d['size'] = total
                t0, b0, last = time.time(), got, 0.0
                with open(part, 'ab' if got else 'wb') as f:
                    while True:
                        if d['id'] in self.cancel:
                            raise Cancelled()
                        buf = r.read(CHUNK)
                        if not buf:
                            break
                        f.write(buf)
                        got += len(buf)
                        d['got'] = got
                        now = time.time()
                        if now - last > 0.5:
                            last = now
                            if now - t0 > 1:
                                self.rate = (got - b0) / (now - t0)
                            self.changed.emit()
            if total and got < total:
                raise IOError('connection dropped')
            os.replace(part, dest)
            self._subtitles(it.src, folder)
            self._done(d, dest, it)
        except Cancelled:
            self.cancel.discard(d['id'])
            try:
                os.remove(part)
            except OSError:
                pass
            d['state'] = 'cancelled'        # the main thread drops it from the list
        except Exception as e:
            d['tries'] = d.get('tries', 0) + 1
            if d['tries'] >= TRIES:
                d.update(state='failed', error=f'{type(e).__name__}: {e}'[:120])
            else:
                d.update(state='queued', error=f'Retrying… ({e.__class__.__name__})')
                time.sleep(min(30, 3 * d['tries']))
        finally:
            self.changed.emit()

    def _done(self, d, dest, it):
        d.update(state='done', path=dest, got=os.path.getsize(dest), error='', finished=time.time())
        if not d['size']:
            d['size'] = d['got']
        self.finished.emit(dest)

    def _subtitles(self, src, folder):
        """Grab the external subtitle files that sit next to the video on the other computer."""
        try:
            u = urllib.parse.urlsplit(src)
            vid = [p for p in u.path.split('/') if p][-1]
            base = f'{u.scheme}://{u.netloc}'
            with urllib.request.urlopen(f'{base}/subs/{vid}?{u.query}', timeout=15) as r:
                names = json.loads(r.read() or b'[]')
            for i, n in enumerate(names):
                out = os.path.join(folder, safe_name(n))
                if not safe_name(n) or os.path.exists(out):
                    continue
                with urllib.request.urlopen(f'{base}/sub/{vid}/{i}?{u.query}', timeout=30) as r:
                    data = r.read()
                with open(out, 'wb') as f:
                    f.write(data)
        except Exception:
            pass
