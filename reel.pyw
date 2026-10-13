#!/usr/bin/env python3
"""Reel - a clean movie & TV player with a Plex-style library.

Run:  pyw -3.14 C:\\Reel\\reel.pyw  [optional video file]
"""
import os, sys, time, threading, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, 'lib')
os.environ['PATH'] = LIB + os.pathsep + os.environ.get('PATH', '')
if sys.platform == 'darwin':  # Homebrew's libmpv (Apple Silicon + Intel locations)
    os.environ['DYLD_FALLBACK_LIBRARY_PATH'] = os.pathsep.join(
        [LIB, '/opt/homebrew/lib', '/usr/local/lib', os.environ.get('DYLD_FALLBACK_LIBRARY_PATH', ''), '/usr/lib'])
if hasattr(os, 'add_dll_directory') and os.path.isdir(LIB):
    os.add_dll_directory(LIB)
sys.path.insert(0, HERE)

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QFileSystemWatcher, QObject, QEvent
from PyQt6.QtGui import QIcon, QPalette, QColor, QFont, QSurfaceFormat
from PyQt6.QtWidgets import (QApplication, QMainWindow, QStackedWidget, QFileDialog, QDialog, QVBoxLayout,
                             QHBoxLayout, QLabel, QCheckBox, QSpinBox, QWidget, QFrame, QLineEdit,
                             QSystemTrayIcon, QMenu)

import library
from library import Library, Store, parse, path_key, fmt_dur, DATA_DIR, VIDEO_EXT
from theme import BG, SURFACE, SURFACE2, BORDER, TEXT, MUTED, ACCENT, font, BOLD, HEAVY, app_icon, PillButton, IconButton
from media import Images, Metadata
from cloud import Cloud, sync_id
from server import MediaServer, Tunnel
from player import PlayerView
from browse import Browser, label, reveal

LOG = os.path.join(DATA_DIR, 'reel.log')


def log_exc(*exc):
    text = ''.join(traceback.format_exception(*exc))
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(time.strftime('\n[%Y-%m-%d %H:%M:%S]\n') + text)
    except OSError:
        pass
    sys.__stderr__ and sys.__stderr__.write(text)


sys.excepthook = log_exc


CHECK_SVG = os.path.join(DATA_DIR, 'check.svg')
if not os.path.exists(CHECK_SVG):
    with open(CHECK_SVG, 'w') as f:
        f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#fff" '
                'stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6.5L9.2 17.3 4 12.1"/></svg>')


class SettingsDialog(QDialog):
    tested = pyqtSignal(str)

    def __init__(self, main):
        super().__init__(main)
        self.tested.connect(lambda t: self.sb_result.setText(t))
        self.main, self.s = main, main.store.settings.data
        self.setWindowTitle('Library settings')
        self.setMinimumWidth(560)
        self.setStyleSheet(
            f'QDialog{{background:{SURFACE}}} QLabel{{color:{TEXT};background:transparent}}'
            f'QCheckBox{{color:{TEXT};spacing:10px;font-size:14px}}'
            f'QCheckBox::indicator{{width:18px;height:18px;border-radius:5px;border:1px solid #4a4a58;background:#101016}}'
            f'QCheckBox::indicator:checked{{background:{ACCENT};border:1px solid {ACCENT};image:url({CHECK_SVG.replace(os.sep, "/")})}}'
            f'QSpinBox{{background:#101016;color:{TEXT};border:1px solid {BORDER};border-radius:6px;padding:4px 8px;font-size:14px}}')
        v = QVBoxLayout(self)
        v.setContentsMargins(28, 24, 28, 22)
        v.setSpacing(12)
        v.addWidget(label('Library settings', 22, TEXT, HEAVY))
        v.addSpacing(4)
        self.all = QCheckBox('Scan the whole computer (every drive)')
        self.all.setChecked(self.s.get('scan_all', True))
        v.addWidget(self.all)
        v.addWidget(label('Skips Windows, Program Files, AppData, game libraries and other system folders.', 12.5, MUTED))
        v.addSpacing(8)
        v.addWidget(label('Extra folders', 15, TEXT, BOLD))
        v.addWidget(label('Add folders on network drives or anywhere the full scan doesn’t reach.', 12.5, MUTED))
        self.folder_box = QVBoxLayout()
        self.folder_box.setSpacing(4)
        v.addLayout(self.folder_box)
        add = PillButton('Add folder', 'plus', 'ghost', h=36, px=13.5)
        add.clicked.connect(self.add_folder)
        v.addWidget(add)
        v.addSpacing(8)
        row = QHBoxLayout()
        row.addWidget(label('Ignore videos smaller than', 14))
        self.min = QSpinBox()
        self.min.setRange(0, 2000)
        self.min.setSuffix(' MB')
        self.min.setValue(int(self.s.get('min_mb', 40)))
        row.addWidget(self.min)
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(label('Keeps short clips, trailers and game cutscenes out of your library.', 12.5, MUTED))
        v.addSpacing(8)
        self.online = QCheckBox('Download posters, plots and episode names')
        self.online.setChecked(self.s.get('online', True))
        v.addWidget(self.online)
        v.addWidget(label('Looks titles up on Cinemeta (IMDb data). Only the cleaned-up title and year are sent.', 12.5, MUTED))
        v.addSpacing(8)
        self.internet = QCheckBox('Let my other computers stream from anywhere (free Cloudflare link)')
        self.internet.setChecked(self.s.get('internet_share', True))
        v.addWidget(self.internet)
        v.addWidget(label('Off = only on the same Wi-Fi. Everything stays password-protected. Takes effect next launch.',
                          12.5, MUTED, wrap=True))
        v.addSpacing(4)
        self.share = QCheckBox('Keep sharing in the background when I close Reel')
        self.share.setChecked(self.s.get('keep_sharing', True))
        v.addWidget(self.share)
        v.addWidget(label('Lets your other computers stream from this one while the window is closed '
                          '(Reel stays in the system tray).', 12.5, MUTED, wrap=True))
        v.addSpacing(8)
        v.addWidget(label('Cloud sync (Supabase) — optional', 15, TEXT, BOLD))
        v.addWidget(label('Syncs resume points + watched marks between your computers and saves each scan. '
                          'Run supabase.sql once in your project’s SQL editor, then paste the Project URL and anon key '
                          '(Project Settings → API).', 12.5, MUTED, wrap=True))
        css = (f'QLineEdit{{background:#101016;color:{TEXT};border:1px solid {BORDER};border-radius:8px;'
               f'padding:8px 10px;font-size:13.5px}}')
        self.sb_url = QLineEdit(self.s.get('supabase_url', ''))
        self.sb_url.setPlaceholderText('https://xxxx.supabase.co')
        self.sb_key = QLineEdit(self.s.get('supabase_key', ''))
        self.sb_key.setPlaceholderText('anon public key')
        self.sb_key.setEchoMode(QLineEdit.EchoMode.Password)
        for e in (self.sb_url, self.sb_key):
            e.setStyleSheet(css)
            v.addWidget(e)
        tr = QHBoxLayout()
        tb = PillButton('Test connection', None, 'ghost', h=34, px=13)
        self.sb_result = label('', 13, MUTED)
        tb.clicked.connect(self.test_cloud)
        tr.addWidget(tb)
        tr.addWidget(self.sb_result)
        tr.addStretch(1)
        v.addLayout(tr)
        v.addSpacing(8)
        hidden = len(self.s.get('hidden', []))
        if hidden:
            hr = QHBoxLayout()
            hr.addWidget(label(f'{hidden} file{"s" if hidden != 1 else ""} removed from the library', 14))
            rb = PillButton('Restore', None, 'ghost', h=32, px=13)
            rb.clicked.connect(lambda: (self.s.__setitem__('hidden', []), rb.setText('Restored')))
            hr.addWidget(rb)
            hr.addStretch(1)
            v.addLayout(hr)
        dr = QHBoxLayout()
        dr.addWidget(label(f'Data: {DATA_DIR}', 12.5, MUTED))
        dr.addStretch(1)
        v.addLayout(dr)
        v.addSpacing(10)
        br = QHBoxLayout()
        br.addStretch(1)
        done = PillButton('Save', None, 'primary', h=40, px=14)
        done.clicked.connect(self.save)
        br.addWidget(done)
        v.addLayout(br)
        self.folders = list(self.s.get('folders', []))
        self.render_folders()

    def render_folders(self):
        while self.folder_box.count():
            it = self.folder_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if not self.folders:
            self.folder_box.addWidget(label('None', 13, MUTED))
        for f in self.folders:
            w = QFrame()
            w.setStyleSheet(f'QFrame{{background:#101016;border:1px solid {BORDER};border-radius:8px}}')
            h = QHBoxLayout(w)
            h.setContentsMargins(12, 4, 4, 4)
            l = label(f, 13.5)
            l.setStyleSheet(f'color:{TEXT};border:none;background:transparent')
            h.addWidget(l, 1)
            x = IconButton('x', 30, 16)
            x.clicked.connect(lambda _=False, f=f: (self.folders.remove(f), self.render_folders()))
            h.addWidget(x)
            self.folder_box.addWidget(w)

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, 'Add folder')
        if d and d not in self.folders:
            self.folders.append(os.path.normpath(d))
            self.render_folders()

    def test_cloud(self):
        self.s['supabase_url'] = self.sb_url.text().strip()
        self.s['supabase_key'] = self.sb_key.text().strip()
        self.sb_result.setText('Testing…')
        self.main.cloud.test(lambda ok, msg: self.tested.emit(('✓ ' if ok else '✕ ') + msg))

    def save(self):
        self.s['supabase_url'] = self.sb_url.text().strip()
        self.s['supabase_key'] = self.sb_key.text().strip()
        self.s['scan_all'] = self.all.isChecked()
        self.s['keep_sharing'] = self.share.isChecked()
        self.s['internet_share'] = self.internet.isChecked()
        self.s['folders'] = self.folders
        self.s['min_mb'] = self.min.value()
        self.s['online'] = self.online.isChecked()
        self.main.store.settings.save()
        self.accept()


class Main(QMainWindow):
    tunnel_changed = pyqtSignal()
    scan_progress = pyqtSignal(int, int, str)
    scan_done = pyqtSignal(object)
    uploaded = pyqtSignal(str)        # server saved a file sent from another device
    upload_status = pyqtSignal(str)   # progress text while this device sends a file

    def __init__(self, files):
        super().__init__()
        self.store = Store()
        self.local = Library()          # files on this computer
        self.local.load_cache()
        self.remote_items = []          # files on your other computers (streamed)
        self.lib = Library()            # what you browse: both
        self.lib.set_items(list(self.local.items))
        self.server = MediaServer(self.store)
        self.server.start(self.local.items)
        if self.store.settings.data.get('internet_share', True) and self.server.port:
            self.server.tunnel = Tunnel(self.server.port, self.server.token, self.tunnel_changed.emit)
            self.server.tunnel.start()
        self._quitting = False
        self.images = Images()
        self.meta = Metadata(self.store)
        self.cloud = Cloud(self.store)
        self.store.on_change = self.cloud.mark
        self.scanning = False
        self._cancel = False
        self.was_max = True

        self.setWindowTitle('Reel')
        self.setWindowIcon(QIcon(app_icon(256)))
        self.setMinimumSize(1000, 640)
        self.resize(1440, 900)
        self.setAcceptDrops(True)
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.browser = Browser(self)
        self.player = PlayerView(self)
        self.stack.addWidget(self.browser)
        self.stack.addWidget(self.player)
        self.browser.play.connect(self.play)
        self.player.closed.connect(self.show_library)
        self.player.fullscreen.connect(self.toggle_fullscreen)
        self.player.title_changed.connect(lambda t: self.setWindowTitle(f'{t} — Reel'))
        self.scan_progress.connect(self._on_scan_progress)
        self.scan_done.connect(self._on_scan_done)
        self.cloud.status.connect(self.browser.set_cloud_status)
        self.cloud.synced.connect(self._on_synced)
        self.servers = []                       # reachable other computers {name, base, token}
        self.server.on_upload = self.uploaded.emit
        self.uploaded.connect(self._on_uploaded)
        self.upload_status.connect(self.browser.set_cloud_status)
        self._uploading = False
        self.update_status()
        self.cloud.push_library(self.local.items, self.server.info())  # also pulls when done
        self._addrs = (self.server.info() or {}).get('urls')
        self.sync_timer = QTimer(self, interval=60000, timeout=self.periodic)
        self.tunnel_changed.connect(self.periodic)
        self.sync_timer.start()
        self.tray = QSystemTrayIcon(QIcon(app_icon(64)), self)
        self.tray.setToolTip('Reel — sharing your library')
        menu = QMenu()
        menu.addAction('Open Reel', self.bring_back)
        menu.addSeparator()
        menu.addAction('Quit Reel', self.quit_app)
        self.tray.setContextMenu(menu)
        self._tray_menu = menu
        self.tray.activated.connect(lambda r: self.bring_back() if r != QSystemTrayIcon.ActivationReason.Context else None)
        if not self.lib.items and not self.store.settings.data.get('last_scan'):
            QTimer.singleShot(400, self.start_scan)  # first run: go find stuff right away
        for f in files:
            if os.path.isfile(f):
                QTimer.singleShot(200, lambda f=f: self.play_path(f))
                break

    # ------------------------------------------------------------ helpers used by views
    def titles(self, it):
        return self.browser.titles(it)

    def episode_pixmap(self, it):
        return self.browser.episode_pixmap(it)

    def episode_blurb(self, it):
        d = self.store.duration(it)
        return fmt_dur(d)

    # ------------------------------------------------------------ playback
    def play(self, item, start=None):
        self.stack.setCurrentWidget(self.player)
        self.player.open(item, start)

    def play_path(self, path):
        it = self.lib.find(path)
        if not it:
            st = os.stat(path)
            it = parse(path, st.st_size, st.st_ctime)
        self.play(it)

    def show_library(self):
        if self.isFullScreen():
            self.toggle_fullscreen()
        self.setWindowTitle('Reel')
        self.stack.setCurrentWidget(self.browser)
        self.browser.render(keep_scroll=True)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showMaximized() if self.was_max else self.showNormal()
            self.player.set_fs(False)
        else:
            self.was_max = self.isMaximized()
            self.showFullScreen()
            self.player.set_fs(True)

    def open_file_dialog(self):
        exts = ' '.join('*' + e for e in sorted(VIDEO_EXT))
        f, _ = QFileDialog.getOpenFileName(self, 'Open video', os.path.expanduser('~'), f'Videos ({exts});;All files (*)')
        if f:
            self.play_path(f)

    # ------------------------------------------------------------ scanning
    def start_scan(self):
        if self.scanning:
            self._cancel = True
            return
        self.scanning, self._cancel = True, False
        roots = self.store.roots()
        s = self.store.settings.data
        self.browser.set_scan_status('Starting scan…', True)
        if not self.lib.items:
            self.browser.render()

        def run():
            try:
                lib = Library().scan(roots, s.get('min_mb', 40), s.get('hidden', []),
                                     progress=lambda d, n, p: self.scan_progress.emit(d, n, p),
                                     cancel=lambda: self._cancel)
            except Exception:
                log_exc(*sys.exc_info())
                lib = None
            self.scan_done.emit(lib)
        threading.Thread(target=run, daemon=True).start()

    def _on_scan_progress(self, dirs, found, path):
        short = path if len(path) < 34 else '…' + path[-33:]
        self.browser.set_scan_status(f'Scanning {dirs:,} folders · {found} videos found\n{short}', True)

    def _on_scan_done(self, lib):
        self.scanning = False
        if lib is not None:
            self.local = lib
            lib.save_cache()
            self.store.settings.data['last_scan'] = time.time()
            self.store.settings.save()
            self.server.update(lib.items)
            self.merge()
            self.cloud.push_library(lib.items, self.server.info())
        self.update_status(cancelled=lib is None)

    # ------------------------------------------------------------ other computers
    def periodic(self):
        addrs = (self.server.info() or {}).get('urls')
        if addrs != self._addrs:  # new public link, or a different Wi-Fi: tell the other computers
            self._addrs = addrs
            self.cloud.push_library(self.local.items, self.server.info())
        else:
            self.cloud.sync()

    def merge(self):
        have = {sync_id(i) for i in self.local.items}
        extra = [i for i in self.remote_items if sync_id(i) not in have]  # prefer the copy on this computer
        self.lib = Library()
        self.lib.set_items(list(self.local.items) + extra)
        if self.browser.current[0] == 'show' and not self.lib.shows.get(self.browser.current[1].key):
            self.browser.current = ('shows', None)
        self.browser.set_library(self.lib)
        self.update_status()

    def _on_synced(self, progress, remotes):
        import hashlib, urllib.parse
        self.servers = [{'name': r['device'].removesuffix('.local').replace('-', ' '),
                         'base': r['base'], 'token': r['token']} for r in remotes if r.get('base')]
        items = []
        for r in remotes:
            if not r.get('base'):
                continue
            name = r['device'].removesuffix('.local').replace('-', ' ')
            tok = urllib.parse.quote(r['token'])
            for row in r['rows']:
                it = parse(row['path'], row.get('size') or 0, row.get('added') or 0)
                if it.kind not in ('movie', 'episode'):
                    continue
                key = row['id'].split(':', 1)[1]
                it.key = f'remote:{r["device"]}:{key}'
                it.remote = name
                it.src = f'{r["base"]}/v/{hashlib.sha1(key.encode()).hexdigest()[:16]}?t={tok}'
                items.append(it)
        changed_lib = {i.key for i in items} != {i.key for i in self.remote_items}
        self.remote_items = items
        if changed_lib:
            self.merge()
        if self.cloud.apply_progress(self.lib.items, progress) or changed_lib:
            if self.stack.currentWidget() is self.browser:
                self.browser.render(keep_scroll=True)

    # ------------------------------------------------------------ save a file to the library (all devices)
    def can_upload(self):
        # only activated devices (your Supabase creds) with another computer online
        return bool(self.cloud.on and self.servers)

    def _upload_target(self):
        if not self.servers:
            return None
        pref = self.store.settings.data.get('home_device')
        return next((s for s in self.servers if s['name'] == pref), self.servers[0])

    def already_shared(self, item):
        return sync_id(item) in {sync_id(i) for i in self.remote_items}

    def upload_item(self, item):
        if self._uploading:
            self.upload_status.emit('Already saving a file — one at a time.')
            return
        target = self._upload_target()
        if not target:
            self.upload_status.emit('No other computer is online to save to.')
            return
        if self.already_shared(item) or not os.path.isfile(item.path):
            self.upload_status.emit('That’s already in your library.' if self.already_shared(item)
                                    else 'Can’t find that file.')
            return
        self.store.settings.data['home_device'] = target['name']
        self._uploading = True
        title = self.browser.titles(item)[0]
        subdir = ''
        if item.kind == 'episode':
            subdir = re.sub(r'[\\/:*?"<>|]', '', item.title)[:80]
        threading.Thread(target=self._do_upload, args=(item, target, title, subdir), daemon=True).start()

    def _do_upload(self, item, target, title, subdir):
        import http.client, urllib.parse, urllib.request
        try:
            size = os.path.getsize(item.path)
            try:  # authoritative duplicate check (the cloud list can be a bit stale)
                q0 = urllib.parse.urlencode({'t': target['token'], 'id': sync_id(item)})
                if urllib.request.urlopen(f"{target['base']}/have?{q0}", timeout=10).read() == b'yes':
                    self.upload_status.emit('That’s already in your library.')
                    return
            except Exception:
                pass
            sp = urllib.parse.urlsplit(target['base'])
            q = urllib.parse.urlencode({'t': target['token'], 'name': os.path.basename(item.path), 'subdir': subdir})
            conn = (http.client.HTTPSConnection if sp.scheme == 'https' else http.client.HTTPConnection)(
                sp.hostname, sp.port, timeout=60)
            conn.putrequest('POST', f'/upload?{q}', skip_host=False, skip_accept_encoding=True)
            conn.putheader('Content-Length', str(size))
            conn.putheader('Content-Type', 'application/octet-stream')
            conn.endheaders()
            sent, last = 0, -5
            with open(item.path, 'rb') as f:
                while True:
                    buf = f.read(1024 * 512)
                    if not buf:
                        break
                    conn.send(buf)
                    sent += len(buf)
                    pct = int(sent * 100 / size) if size else 100
                    if pct >= last + 2:
                        last = pct
                        self.upload_status.emit(f'Saving “{title}” to your library… {pct}%')
            resp = conn.getresponse()
            ok = resp.status == 200
            resp.read()
            conn.close()
            self.upload_status.emit('Saved — it’s now on all your devices.' if ok
                                    else f'Couldn’t save (server said {resp.status}).')
            if ok:
                QTimer.singleShot(1500, self.cloud.sync)
        except Exception as e:
            self.upload_status.emit(f'Save failed ({type(e).__name__}). Is the other computer still on?')
        finally:
            self._uploading = False

    def _on_uploaded(self, path):
        # another device sent us a file; add it to this computer's library and share it
        try:
            st = os.stat(path)
        except OSError:
            return
        it = parse(path, st.st_size, time.time())
        if it.kind == 'video' or self.local.find(path):
            self.local.save_cache()
            return
        self.local.set_items(list(self.local.items) + [it])
        self.local.save_cache()
        self.server.update(self.local.items)
        self.merge()
        self.cloud.push_library(self.local.items, self.server.info())
        self.browser.set_cloud_status(f'Received “{it.display}” — added to your library.')

    def update_status(self, cancelled=False):
        movies = len(self.browser.movies())
        shows = len(self.lib.shows)
        eps = sum(len(s.episodes) for s in self.lib.shows.values())
        far = len({i.remote for i in self.remote_items})
        last = self.store.settings.data.get('last_scan')
        when = ''
        if last:
            mins = int((time.time() - last) / 60)
            when = 'just now' if mins < 1 else f'{mins} min ago' if mins < 60 else \
                f'{mins // 60} h ago' if mins < 1440 else time.strftime('%b %d', time.localtime(last))
        text = 'Scan stopped. ' if cancelled else ''
        if self.lib.items:
            text += f'{movies} movies · {shows} shows ({eps} episodes)'
            if far:
                text += f'\nIncludes {far} other computer' + ('s' if far > 1 else '')
            if when:
                text += f'\nLast scan {when}'
        elif not last:
            text += 'Nothing scanned yet.'
        else:
            text += 'No movies or shows found.'
        self.browser.set_scan_status(text, False)

    def hide_items(self, items):
        hidden = self.store.settings.data.setdefault('hidden', [])
        keys = {i.key for i in items}
        hidden.extend(k for k in keys if k not in hidden)
        self.store.settings.save()
        self.local.set_items([i for i in self.local.items if i.key not in keys])
        self.local.save_cache()
        self.server.update(self.local.items)
        self.merge()
        self.cloud.push_library(self.local.items, self.server.info())

    def open_settings(self):
        had = self.cloud.on
        SettingsDialog(self).exec()
        self.update_status()
        if self.cloud.on and not had:  # just connected: upload what we have, then merge
            for it in self.lib.items:
                if self.store.progress.data.get(it.key):
                    self.cloud.mark(it)
            self.cloud.flush()
            self.cloud.push_library(self.local.items, self.server.info())

    # ------------------------------------------------------------ window
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        vids = [p for p in paths if os.path.splitext(p)[1].lower() in VIDEO_EXT]
        dirs = [p for p in paths if os.path.isdir(p)]
        if vids:
            self.play_path(vids[0])
        elif dirs:
            f = self.store.settings.data.setdefault('folders', [])
            for d in dirs:
                if os.path.normpath(d) not in f:
                    f.append(os.path.normpath(d))
            self.store.settings.save()
            self.start_scan()

    def showEvent(self, e):
        super().showEvent(e)
        if sys.platform == 'win32':
            try:
                import ctypes
                hwnd = int(self.winId())
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(ctypes.c_int(1)), 4)
                c = QColor(BG)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(ctypes.c_int(c.red() | c.green() << 8 | c.blue() << 16)), 4)
            except Exception:
                pass

    def closeEvent(self, e):
        s = self.store.settings.data
        if (not self._quitting and s.get('keep_sharing', True) and self.server.port
                and QSystemTrayIcon.isSystemTrayAvailable()):
            e.ignore()
            if self.player.item:
                self.player.close_player()
            self.player.save_progress()
            self.store.progress.save()
            self.cloud.flush()
            self.hide()
            self.tray.show()
            if not s.get('tray_hint_shown'):
                s['tray_hint_shown'] = True
                self.store.settings.save()
                self.tray.showMessage('Reel is still sharing', 'Your other computers can keep streaming from here. '
                                      'Right-click the Reel icon to quit.', QIcon(app_icon(64)), 6000)
            return
        self.shutdown()
        super().closeEvent(e)
        QApplication.instance().quit()

    def bring_back(self):
        self.showMaximized() if self.was_max else self.showNormal()
        self.raise_()
        self.activateWindow()
        self.tray.hide()

    def quit_app(self):
        self._quitting = True
        self.tray.hide()
        self.shutdown()
        QApplication.instance().quit()

    def shutdown(self):
        if getattr(self, '_shut', False):
            return
        self._shut = True
        try:
            self.player.save_progress()
            self.store.settings.save()
            self.store.progress.save()
            self.store.meta.save()
            self.meta.db.save()
            self.cloud.flush(wait=True)
            self.server.stop()
            self.player.video.shutdown()
        except Exception:
            log_exc(*sys.exc_info())


class FileOpener(QObject):
    def __init__(self, w):
        super().__init__(w)
        self.w = w

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Type.FileOpen and e.file():
            QTimer.singleShot(0, lambda f=e.file(): self.w.play_path(f))
            return True
        return False


def main():
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Reel.Player')
        except Exception:
            pass
    if sys.platform == 'darwin':  # macOS only gives modern OpenGL with a core profile; mpv needs it
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 2)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication(sys.argv)
    app.setApplicationName('Reel')
    app.setWindowIcon(QIcon(app_icon(512)))  # also the Dock icon on macOS
    app.setQuitOnLastWindowClosed(False)      # Reel can keep sharing from the tray
    app.setStyle('Fusion')
    pal = QPalette()
    for role, col in ((QPalette.ColorRole.Window, BG), (QPalette.ColorRole.Base, SURFACE),
                      (QPalette.ColorRole.Text, TEXT), (QPalette.ColorRole.WindowText, TEXT),
                      (QPalette.ColorRole.Button, SURFACE2), (QPalette.ColorRole.ButtonText, TEXT),
                      (QPalette.ColorRole.Highlight, ACCENT), (QPalette.ColorRole.ToolTipBase, SURFACE2),
                      (QPalette.ColorRole.ToolTipText, TEXT), (QPalette.ColorRole.PlaceholderText, MUTED)):
        pal.setColor(role, QColor(col))
    app.setPalette(pal)
    app.setFont(font(14))
    app.setStyleSheet(f'QToolTip{{background:{SURFACE2};color:{TEXT};border:1px solid {BORDER};padding:5px 8px;border-radius:6px}}')
    import locale
    locale.setlocale(locale.LC_NUMERIC, 'C')  # libmpv needs C numeric locale
    w = Main([a for a in sys.argv[1:] if not a.startswith('-')])
    app.aboutToQuit.connect(w.shutdown)
    opener = FileOpener(w)  # macOS "Open With" / double-click delivers files as events, not argv
    app.installEventFilter(opener)
    w.showMaximized()
    if os.environ.get('REEL_SCRIPT'):  # automation hook for testing
        import runpy
        runpy.run_path(os.environ['REEL_SCRIPT'], init_globals={'w': w, 'app': app})
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
