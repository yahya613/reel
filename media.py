"""Background workers: frame thumbnails (libmpv), remote images, and online metadata (Cinemeta, no key)."""
import os, re, json, time, shutil, hashlib, difflib, tempfile, threading, urllib.request, urllib.parse
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap, QImage
import mpv
from library import DATA_DIR, THUMB_DIR, JsonFile, thumb_path, norm_key

IMG_DIR = os.path.join(DATA_DIR, 'img')
os.makedirs(IMG_DIR, exist_ok=True)
CINEMETA = 'https://v3-cinemeta.strem.io'
UA = {'User-Agent': 'Reel/1.0 (desktop media player)'}


def http(url, timeout=15):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def http_json(url):
    return json.loads(http(url).decode('utf-8'))


class Images(QObject):
    """Pixmaps for frame thumbnails ('f:'+item key) and remote URLs, loaded lazily off the UI thread."""
    ready = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.cache = OrderedDict()
        self.failed, self.queued = set(), set()
        self.stack = []
        self.cv = threading.Condition()
        self.pool = ThreadPoolExecutor(6)
        for _ in range(2):
            threading.Thread(target=self._frame_worker, daemon=True).start()

    def _cached(self, key, path):
        pm = self.cache.get(key)
        if pm is not None:
            self.cache.move_to_end(key)
            return pm
        if os.path.exists(path):
            pm = QPixmap(path)
            if pm.isNull():
                self.failed.add(key)
                return None
            self.cache[key] = pm
            while len(self.cache) > 600:
                self.cache.popitem(last=False)
            return pm
        return None

    # -- frame thumbnails ---------------------------------------------------
    def frame(self, item):
        key = 'f:' + item.key
        pm = self._cached(key, thumb_path(item))
        if pm is None and key not in self.failed:
            with self.cv:
                if key in self.queued:
                    self.stack = [i for i in self.stack if i.key != item.key]
                self.queued.add(key)
                self.stack.append(item)  # LIFO: what's on screen now goes first
                self.cv.notify()
        return pm

    def _frame_worker(self):
        while True:
            with self.cv:
                while not self.stack:
                    self.cv.wait()
                item = self.stack.pop()
            key = 'f:' + item.key
            try:
                ok = self._grab(item)
            except Exception:
                ok = False
            self.queued.discard(key)
            if ok:
                self.ready.emit(key)
            else:
                self.failed.add(key)

    def _grab(self, item):
        dst = thumb_path(item)
        for start in ('22%', '40%', '8%'):
            out = tempfile.mkdtemp(dir=THUMB_DIR)
            try:
                m = mpv.MPV(vo='image', ao='null', aid='no', sid='no', frames=1, start=start, hr_seek='no',
                            vo_image_format='jpg', vo_image_jpeg_quality=84, vo_image_outdir=out,
                            vf='scale=w=640:h=-2', config=False, load_scripts=False, ytdl=False,
                            input_default_bindings=False, terminal=False, hwdec='no')
                try:
                    m.play(item.src or item.path)
                    m.wait_for_playback(timeout=25)
                except Exception:
                    pass
                finally:
                    m.terminate()
                files = [f for f in os.listdir(out) if f.endswith('.jpg')]
                if not files:
                    continue
                src = os.path.join(out, files[0])
                img = QImage(src)
                if img.isNull():
                    continue
                small = img.scaled(16, 9)
                lum = sum(small.pixelColor(x, y).lightness() for x in range(16) for y in range(9)) / 144
                if lum < 22 and start != '8%':
                    continue  # black frame (scene cut) - try elsewhere
                shutil.move(src, dst)
                return True
            finally:
                shutil.rmtree(out, ignore_errors=True)
        return False

    # -- remote images -------------------------------------------------------
    def remote(self, url):
        if not url:
            return None
        path = os.path.join(IMG_DIR, hashlib.sha1(url.encode()).hexdigest()[:24] + '.img')
        pm = self._cached(url, path)
        if pm is None and url not in self.failed and url not in self.queued:
            self.queued.add(url)
            self.pool.submit(self._download, url, path)
        return pm

    def _download(self, url, path):
        try:
            data = http(url)
            if len(data) < 400:
                raise ValueError('tiny image')
            tmp = path + '.part'
            with open(tmp, 'wb') as f:
                f.write(data)
            os.replace(tmp, path)
            self.ready.emit(url)
        except Exception:
            self.failed.add(url)
        finally:
            self.queued.discard(url)


def _year_of(m):
    y = re.match(r'\d{4}', str(m.get('releaseInfo') or m.get('year') or ''))
    return int(y.group()) if y else 0


def _pick(metas, title, year):
    want = norm_key(title)
    best, best_score = None, 0
    for i, m in enumerate(metas[:12]):
        name = norm_key(m.get('name') or '')
        if not name:
            continue
        ratio = 1.0 if name == want else difflib.SequenceMatcher(None, want, name).ratio()
        score = ratio - i * 0.01
        my = _year_of(m)
        if year and my:
            d = abs(my - year)
            score += 0.5 if d == 0 else 0.3 if d == 1 else -0.6
        if ratio >= 0.78 and score > best_score:
            best, best_score = m, score
    return best if best_score >= 0.75 else None


def _poster(url, imdb):
    if imdb:
        return f'https://images.metahub.space/poster/medium/{imdb}/img'
    return url


def _slim(m, kind):
    imdb = m.get('imdb_id') or (m.get('id') if str(m.get('id', '')).startswith('tt') else '')
    rec = {
        'id': m.get('id'), 'kind': kind, 'name': m.get('name'), 'year': m.get('releaseInfo') or m.get('year') or '',
        'poster': _poster(m.get('poster'), imdb),
        'background': (m.get('background') or '').replace('/background/small/', '/background/medium/'),
        'logo': m.get('logo') or '', 'description': m.get('description') or '',
        'genres': (m.get('genres') or m.get('genre') or [])[:3], 'rating': m.get('imdbRating') or '',
        'runtime': m.get('runtime') or '', 'cast': (m.get('cast') or [])[:4], 'director': (m.get('director') or [])[:2],
    }
    if kind == 'series':
        eps = {}
        for v in m.get('videos') or []:
            s, e = v.get('season'), v.get('episode') or v.get('number')
            if s is None or e is None:
                continue
            eps[f'{s}:{e}'] = {'name': v.get('name') or v.get('title') or '', 'overview': v.get('overview') or v.get('description') or '',
                               'thumb': v.get('thumbnail') or '', 'aired': (v.get('released') or v.get('firstAired') or '')[:10]}
        rec['episodes'] = eps
    return rec


class Metadata(QObject):
    """Matches movies/shows to Cinemeta (IMDb-backed) for posters, art, plots and episode names."""
    ready = pyqtSignal(str)

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.db = JsonFile('metadata.json', {})
        self.pending = set()
        self.pool = ThreadPoolExecutor(4)
        self.dirty = False
        self.timer = QTimer(self, interval=4000, timeout=self._flush)
        self.timer.start()

    @property
    def enabled(self):
        return self.store.settings.data.get('online', True)

    @staticmethod
    def movie_key(item):
        return f'movie:{norm_key(item.title)}:{item.year or ""}'

    @staticmethod
    def show_key(show):
        return f'series:{show.key}'

    def movie(self, item):
        return self._get(self.movie_key(item), 'movie', item.title, item.year)

    def show(self, show):
        return self._get(self.show_key(show), 'series', show.name, show.year)

    def episode(self, show_meta, item):
        if not show_meta:
            return {}
        return show_meta.get('episodes', {}).get(f'{item.season}:{item.episode}', {})

    def settled(self, key):
        return key in self.db.data

    def _get(self, key, kind, title, year):
        rec = self.db.data.get(key)
        fresh = rec is not None and (rec.get('id') or time.time() - rec.get('t', 0) < rec.get('retry', 3 * 86400))
        if not fresh and self.enabled and key not in self.pending and title:
            self.pending.add(key)
            self.pool.submit(self._fetch, key, kind, title, year)
        return rec if rec and rec.get('id') else None

    def _fetch(self, key, kind, title, year):
        rec = {'none': True}
        try:
            q = urllib.parse.quote(title)
            metas = http_json(f'{CINEMETA}/catalog/{kind}/top/search={q}.json').get('metas', [])
            best = _pick(metas, title, year)
            if not best and kind == 'movie' and ' ' in title and len(title.split()) > 3:
                short = ' '.join(title.split()[:3])
                metas = http_json(f'{CINEMETA}/catalog/{kind}/top/search={urllib.parse.quote(short)}.json').get('metas', [])
                best = _pick(metas, title, year)
            if best:
                try:
                    full = http_json(f'{CINEMETA}/meta/{kind}/{best["id"]}.json').get('meta') or best
                except Exception:
                    full = best
                rec = _slim({**best, **full}, kind)
        except Exception:
            rec = {'none': True, 'retry': 900}  # offline / network hiccup: retry in 15 min
        rec['t'] = time.time()
        with self.db.lock:
            self.db.data[key] = rec
        self.dirty = True
        self.pending.discard(key)
        self.ready.emit(key)

    def _flush(self):
        if self.dirty:
            self.dirty = False
            self.db.save()


def _slim_catalog(m, kind):
    imdb = m.get('imdb_id') or (m.get('id') if str(m.get('id', '')).startswith('tt') else '')
    return {'id': m.get('id'), 'kind': kind, 'name': m.get('name'),
            'year': str(m.get('releaseInfo') or m.get('year') or '')[:9],
            'poster': _poster(m.get('poster'), imdb),
            'background': (m.get('background') or '').replace('/background/small/', '/background/medium/'),
            'logo': m.get('logo') or '', 'description': m.get('description') or '',
            'genres': (m.get('genres') or m.get('genre') or [])[:4], 'rating': m.get('imdbRating') or '',
            'runtime': m.get('runtime') or '', 'cast': (m.get('cast') or [])[:4]}


class Catalog(QObject):
    """Cinemeta's public catalogs (trending / by-genre), for recommendations. Keyless, cached a day."""
    ready = pyqtSignal(str)
    GENRES = ['Action', 'Adventure', 'Animation', 'Comedy', 'Crime', 'Documentary', 'Drama', 'Family',
              'Fantasy', 'History', 'Horror', 'Mystery', 'Romance', 'Sci-Fi', 'Thriller', 'War', 'Western']

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.db = JsonFile('catalogs.json', {})
        self.pending = set()
        self.pool = ThreadPoolExecutor(4)
        self.dirty = False
        self.timer = QTimer(self, interval=5000, timeout=self._flush)
        self.timer.start()

    @property
    def enabled(self):
        return self.store.settings.data.get('online', True)

    def get(self, kind, genre=None, sort='top'):
        """Return cached metas for a catalog, fetching in the background if stale. kind: 'movie'|'series'."""
        key = f'{kind}/{sort}/{genre or ""}'
        rec = self.db.data.get(key)
        fresh = rec and time.time() - rec.get('t', 0) < 86400
        if not fresh and self.enabled and key not in self.pending:
            self.pending.add(key)
            self.pool.submit(self._fetch, key, kind, sort, genre)
        return rec.get('metas', []) if rec else []

    def _fetch(self, key, kind, sort, genre):
        try:
            url = f'{CINEMETA}/catalog/{kind}/{sort}' + (f'/genre={urllib.parse.quote(genre)}' if genre else '') + '.json'
            metas = [_slim_catalog(m, kind) for m in http_json(url).get('metas', []) if m.get('name')]
            with self.db.lock:
                self.db.data[key] = {'metas': metas, 't': time.time()}
            self.dirty = True
            self.ready.emit(key)
        except Exception:
            pass
        finally:
            self.pending.discard(key)

    def meta(self, kind, cid):
        """Full meta for one title (for the trailer + full plot on the detail page)."""
        key = f'full/{kind}/{cid}'
        rec = self.db.data.get(key)
        if rec is None and self.enabled and key not in self.pending:
            self.pending.add(key)

            def run():
                try:
                    m = http_json(f'{CINEMETA}/meta/{kind}/{cid}.json').get('meta') or {}
                    yt = ''
                    for s in (m.get('trailerStreams') or []):
                        if s.get('ytId'):
                            yt = s['ytId']
                            break
                    if not yt:
                        for tr in (m.get('trailers') or []):
                            if tr.get('source'):
                                yt = tr['source']
                                break
                    with self.db.lock:
                        self.db.data[key] = {'trailer': yt, 'description': m.get('description') or '',
                                             'cast': (m.get('cast') or [])[:5], 't': time.time()}
                    self.dirty = True
                    self.ready.emit(key)
                except Exception:
                    pass
                finally:
                    self.pending.discard(key)
            self.pool.submit(run)
        return rec or {}

    def _flush(self):
        if self.dirty:
            self.dirty = False
            self.db.save()
