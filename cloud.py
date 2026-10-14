"""Supabase sync: watch progress + each computer's library + where to stream it from.

Progress is keyed by *what* you watched, not where the file lives, so a show you stop on the PC
resumes at the same spot on the Mac. Videos never go to the cloud (they're far too big for it):
each Reel shares its own files (server.py) and the cloud just tells the other computers where to find them.
"""
import json, re, socket, threading, time, urllib.request, urllib.error, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from library import norm_key

DEVICE = socket.gethostname()


def slug(name):
    return re.sub(r'[^a-z0-9]+', '-', (name or '').lower()).strip('-')[:40] or 'user'


def sync_id(item):
    if item.kind == 'episode':
        return f'ep:{item.show_key}:{item.season}:{item.episode}'
    return f'mv:{norm_key(item.title)}:{item.year or ""}' if item.kind == 'movie' else f'v:{item.key}'


def ping(base, token):
    try:
        timeout = 8 if base.startswith('https') else 1.5
        with urllib.request.urlopen(f'{base}/ping?t={urllib.parse.quote(token)}', timeout=timeout) as r:
            return r.read() == b'reel'
    except Exception:
        return False


class Cloud(QObject):
    status = pyqtSignal(str)
    synced = pyqtSignal(object, object)  # progress rows, [remote device dicts]
    accounts = pyqtSignal(object)        # [account rows] for the control panel
    revoked = pyqtSignal()               # the owner turned this account off
    shares = pyqtSignal(object)          # [recommendation rows] someone sent to this account

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.dirty = {}
        self.lock = threading.Lock()
        self.busy = False
        self.now_playing = ''
        self.timer = QTimer(self, interval=15000, timeout=self.flush)
        self.timer.start()

    @property
    def cfg(self):
        s = self.store.settings.data
        return (s.get('supabase_url') or '').rstrip('/'), s.get('supabase_key') or ''

    @property
    def on(self):
        url, key = self.cfg
        return bool(url and key)

    @property
    def account(self):
        return (self.store.settings.data.get('account') or {}).get('id', 'owner')

    @property
    def is_owner(self):
        return (self.store.settings.data.get('account') or {}).get('role', 'owner') == 'owner'

    # -- accounts -----------------------------------------------------------------
    def fetch_accounts(self):
        """Load the account list (for the control panel / sign-in) and emit `accounts`."""
        if not self.on:
            return

        def run():
            try:
                rows = self._req('GET', 'reel_accounts?select=*&order=role.desc,name.asc') or []
                self.accounts.emit(rows)
            except Exception:
                self.accounts.emit(None)
        threading.Thread(target=run, daemon=True).start()

    def accounts_sync(self):
        try:
            return self._req('GET', 'reel_accounts?select=*&order=role.desc,name.asc') or []
        except Exception:
            return []

    def save_account(self, row, cb=None):
        def run():
            ok = True
            try:
                self._req('POST', 'reel_accounts', [row], 'resolution=merge-duplicates')
            except Exception:
                ok = False
            if cb:
                cb(ok)
            self.fetch_accounts()
        threading.Thread(target=run, daemon=True).start()

    def delete_account(self, aid):
        def run():
            try:
                self._req('DELETE', f'reel_accounts?id=eq.{urllib.parse.quote(aid)}')
                self._req('DELETE', f'reel_progress?account=eq.{urllib.parse.quote(aid)}')
                self._req('DELETE', f'reel_library?account=eq.{urllib.parse.quote(aid)}')
            except Exception:
                pass
            self.fetch_accounts()
        threading.Thread(target=run, daemon=True).start()

    # -- recommendations ("watch this") -------------------------------------------
    def send_shares(self, rows, cb=None):
        def run():
            ok = True
            try:
                self._req('POST', 'reel_shares', rows, 'resolution=merge-duplicates')
            except Exception:
                ok = False
            if cb:
                cb(ok)
        threading.Thread(target=run, daemon=True).start()

    def dismiss_share(self, sid):
        def run():
            try:
                self._req('DELETE', f'reel_shares?id=eq.{urllib.parse.quote(sid)}')
            except Exception:
                pass
        threading.Thread(target=run, daemon=True).start()

    def heartbeat(self):
        """Keep this account's presence fresh and check it hasn't been revoked. Returns active?"""
        aid = self.account
        try:
            self._req('POST', 'reel_accounts', [{'id': aid, 'device': DEVICE, 'now_playing': self.now_playing,
                                                 'last_seen': time.time()}], 'resolution=merge-duplicates')
            rows = self._req('GET', f'reel_accounts?id=eq.{urllib.parse.quote(aid)}&select=active') or []
            if rows and rows[0].get('active') is False:
                self.revoked.emit()
                return False
        except Exception:
            pass
        return True

    def _req(self, method, path, body=None, prefer=None):
        url, key = self.cfg
        h = {'apikey': key, 'Content-Type': 'application/json'}
        if key.startswith('eyJ'):  # legacy JWT anon key; new sb_publishable_ keys go in apikey only
            h['Authorization'] = f'Bearer {key}'
        if prefer:
            h['Prefer'] = prefer
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f'{url}/rest/v1/{path}', data=data, headers=h, method=method)
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            return json.loads(raw) if raw else None

    def _bg(self, fn):
        def run():
            try:
                fn()
            except urllib.error.HTTPError as e:
                self.status.emit(f'Sync error {e.code}: {e.read().decode(errors="ignore")[:160]}')
            except Exception as e:
                self.status.emit(f'Cloud offline ({type(e).__name__})')
        threading.Thread(target=run, daemon=True).start()

    # -- progress -----------------------------------------------------------------
    def mark(self, item):
        if self.on:
            with self.lock:
                self.dirty[item.key] = item

    def flush(self, wait=False):
        if not self.on or not self.dirty:
            return
        with self.lock:
            items, self.dirty = list(self.dirty.values()), {}
        acct = self.account
        rows = {}
        for it in items:
            rec = self.store.get(it)
            rows[sync_id(it)] = {'id': sync_id(it), 'account': acct, 'title': it.display, 'pos': rec.get('pos', 0),
                                 'dur': rec.get('dur', 0), 'watched': bool(rec.get('watched')),
                                 't': rec.get('t', time.time()), 'device': DEVICE}
        rows = list(rows.values())
        if wait:
            try:
                self._req('POST', 'reel_progress', rows, 'resolution=merge-duplicates')
            except Exception:
                pass
            return
        self._bg(lambda: (self._req('POST', 'reel_progress', rows, 'resolution=merge-duplicates'),
                          self.status.emit(f'Progress synced')))

    def apply_progress(self, items, rows):
        """Newest wins. Runs on the UI thread. Returns how many items changed."""
        by_id = {}
        for it in items:
            by_id.setdefault(sync_id(it), []).append(it)
        changed = 0
        for r in rows or []:
            for it in by_id.get(r['id'], []):
                local = self.store.progress.data.get(it.key, {})
                if (r.get('t') or 0) > local.get('t', 0) + 1:
                    self.store.progress.data[it.key] = {'pos': r.get('pos', 0), 'dur': r.get('dur', 0),
                                                        'watched': r.get('watched', False), 't': r['t']}
                    if r.get('dur'):
                        self.store.meta.data.setdefault(it.key, {})['dur'] = r['dur']
                    changed += 1
        if changed:
            self.store.progress.save()
        return changed

    # -- library + other computers --------------------------------------------------
    def push_library(self, items, server_info):
        if not self.on:
            return
        acct = self.account
        rows = [{'id': f'{DEVICE}:{it.key}', 'account': acct, 'device': DEVICE, 'kind': it.kind, 'title': it.title,
                 'year': it.year, 'season': it.season, 'episode': it.episode, 'path': it.path, 'size': it.size,
                 'added': it.added, 'sync_id': sync_id(it)} for it in items if not it.remote and it.kind in ('movie', 'episode')]
        if server_info:
            rows.append({'id': f'{DEVICE}:__server__', 'account': acct, 'device': DEVICE, 'kind': 'server',
                         'title': server_info['token'], 'year': 0, 'season': 0, 'episode': 0,
                         'path': json.dumps(server_info), 'size': server_info['port'], 'added': time.time(), 'sync_id': ''})

        def run():
            self._req('DELETE', f'reel_library?device=eq.{urllib.parse.quote(DEVICE)}')
            for i in range(0, len(rows), 500):
                self._req('POST', 'reel_library', rows[i:i + 500], 'resolution=merge-duplicates')
            self.sync()
        self._bg(run)

    def sync(self):
        """Pull progress + other computers' libraries, and find which of them are reachable right now."""
        if not self.on or self.busy:
            return
        self.busy = True

        def run():
            try:
                self.heartbeat()                       # presence + revoke check
                acct = urllib.parse.quote(self.account)
                try:
                    self.shares.emit(self._req('GET', f'reel_shares?select=*&to_account=eq.{acct}'
                                               f'&status=eq.sent&order=t.desc&limit=200') or [])
                except Exception:
                    pass
                progress = self._req('GET', f'reel_progress?select=*&account=eq.{acct}&limit=50000') or []
                rows = self._req('GET', f'reel_library?select=*&account=eq.{acct}&device=neq.'
                                 f'{urllib.parse.quote(DEVICE)}&limit=50000') or []
                servers = {r['device']: json.loads(r['path']) for r in rows if r.get('kind') == 'server'}
                remotes = []

                def probe(dev):
                    info = servers[dev]
                    urls = info.get('urls') or [f'http://{a}:{info["port"]}' for a in info.get('addrs', [])]
                    for base in urls:  # same Wi-Fi first (fastest), then the public link
                        if ping(base, info['token']):
                            return {'device': dev, 'base': base, 'token': info['token'],
                                    'rows': [r for r in rows if r['device'] == dev and r.get('kind') != 'server']}
                    return {'device': dev, 'base': None, 'rows': []}
                if servers:
                    with ThreadPoolExecutor(len(servers)) as ex:
                        remotes = list(ex.map(probe, servers))
                self.synced.emit(progress, remotes)
                online = [r['device'].removesuffix('.local') + (' (internet)' if r['base'].startswith('https') else '')
                          for r in remotes if r['base']]
                offline = [r['device'] for r in remotes if not r['base']]
                bits = [f'Cloud sync on']
                if online:
                    bits.append('streaming from ' + ', '.join(online))
                if offline:
                    bits.append(', '.join(offline) + ' offline')
                self.status.emit(' · '.join(bits))
            except urllib.error.HTTPError as e:
                self.status.emit(f'Sync error {e.code}')
            except Exception as e:
                self.status.emit(f'Cloud offline ({type(e).__name__})')
            finally:
                self.busy = False
        threading.Thread(target=run, daemon=True).start()

    def test(self, done):
        def run():
            try:
                self._req('GET', 'reel_progress?select=id&limit=1')
                done(True, 'Connected')
            except urllib.error.HTTPError as e:
                msg = e.read().decode(errors='ignore')
                done(False, 'Tables missing - run supabase.sql first' if 'does not exist' in msg or e.code == 404
                     else f'Error {e.code}')
            except Exception as e:
                done(False, f'Can’t reach Supabase ({type(e).__name__})')
        threading.Thread(target=run, daemon=True).start()
