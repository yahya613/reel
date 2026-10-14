"""Share this computer's library with your other computers (like a Plex server).

Each Reel runs a small HTTP server; other Reels find it through Supabase and stream from it.
Only files in the library are served, and every request needs this install's secret token.
"""
import os, re, sys, json, time, shutil, socket, hashlib, secrets, threading, mimetypes, subprocess, urllib.parse, urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from library import SUB_EXT, VIDEO_EXT

PORTS = range(8642, 8652)
CHUNK = 1024 * 1024


def vid(item):
    return hashlib.sha1(item.key.encode()).hexdigest()[:16]


def safe_name(name):
    """A filename with no path tricks — just the base name, cleaned."""
    name = urllib.parse.unquote(name or '').replace('\\', '/').split('/')[-1]
    name = re.sub(r'[\x00-\x1f<>:"|?*]', '', name).strip().strip('.')
    return name[:180]


def local_addresses():
    """LAN first, then Tailscale (100.64/10), then anything else."""
    found = []
    try:  # primary interface (no packets are sent)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))
        found.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    out = []
    for a in found:
        if a not in out and not a.startswith(('127.', '169.254.')):
            out.append(a)
    tail = [a for a in out if a.startswith('100.') and 64 <= int(a.split('.')[1]) <= 127]
    return [a for a in out if a not in tail] + tail


def subtitle_files(path):
    """External subtitles next to a video (and in a Subs/ folder), like mpv's sub-auto."""
    d, base = os.path.dirname(path), os.path.splitext(os.path.basename(path))[0].lower()
    cands = []
    for folder in (d, os.path.join(d, 'Subs'), os.path.join(d, 'subs'), os.path.join(d, 'Subs', os.path.basename(path)[:-4])):
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for n in names:
            if os.path.splitext(n)[1].lower() in SUB_EXT and os.path.splitext(n)[1].lower() != '.idx':
                if n.lower().startswith(base[:12]) or folder != d:
                    p = os.path.join(folder, n)
                    if p not in cands:
                        cands.append(p)
    return cands[:20]


class MediaServer:
    def __init__(self, store):
        self.store = store
        s = store.settings.data
        if not s.get('share_token'):
            s['share_token'] = secrets.token_urlsafe(18)
            store.settings.save()
        self.token = s['share_token']
        self.files = {}
        self.port = None
        self.httpd = None
        self.tunnel = None
        self.on_upload = None   # main window sets this; called (on its thread) with the saved path
        self.have = set()       # sync_ids already here, so other devices don't upload duplicates

    def library_dir(self):
        d = self.store.settings.data.get('upload_dir')
        if not d:
            home = os.path.expanduser('~')
            base = os.path.join(home, 'Movies') if sys.platform == 'darwin' else os.path.join(home, 'Videos')
            d = os.path.join(base, 'Reel Library')
        return d

    def update(self, items):
        self.files = {vid(i): i.path for i in items if not i.remote}
        from cloud import sync_id
        self.have = {sync_id(i) for i in items if not i.remote}

    def start(self, items):
        self.update(items)
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *a):
                pass

            def _deny(self, code=404):
                self.send_response(code)
                self.send_header('Content-Length', '0')
                self.end_headers()

            def do_HEAD(self):
                self.do_GET(head=True)

            def do_POST(self):
                u = urllib.parse.urlsplit(self.path)
                q = urllib.parse.parse_qs(u.query)
                if q.get('t', [''])[0] != server.token:
                    return self._deny(403)
                if u.path.rstrip('/') != '/upload':
                    return self._deny()
                name = safe_name(q.get('name', [''])[0])
                subdir = safe_name(q.get('subdir', [''])[0]) if q.get('subdir', [''])[0] else ''
                if not name or os.path.splitext(name)[1].lower() not in VIDEO_EXT:
                    return self._reply(400, b'bad name')
                try:
                    length = int(self.headers.get('Content-Length') or 0)
                except ValueError:
                    length = 0
                folder = os.path.join(server.library_dir(), subdir) if subdir else server.library_dir()
                try:
                    os.makedirs(folder, exist_ok=True)
                except OSError:
                    return self._reply(500, b'cannot write')
                dest = os.path.join(folder, name)
                # Always read the whole body (even if it's a duplicate) so the sender finishes cleanly.
                exists = os.path.exists(dest) and os.path.getsize(dest) == length
                tmp = dest + '.part'
                got = 0
                try:
                    with open(os.devnull if exists else tmp, 'wb') as f:
                        while got < length:
                            buf = self.rfile.read(min(CHUNK, length - got))
                            if not buf:
                                break
                            f.write(buf)
                            got += len(buf)
                    if exists:
                        return self._reply(200, b'exists')
                    if got < length:
                        raise IOError('short upload')
                    os.replace(tmp, dest)
                except Exception:
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                    return self._reply(500, b'write failed')
                if server.on_upload:
                    server.on_upload(dest)
                self._reply(200, b'saved')

            def _reply(self, code, body):
                self.send_response(code)
                self.send_header('Content-Type', 'text/plain')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

            def do_GET(self, head=False):
                u = urllib.parse.urlsplit(self.path)
                q = urllib.parse.parse_qs(u.query)
                if q.get('t', [''])[0] != server.token:
                    return self._deny(403)
                parts = [p for p in u.path.split('/') if p]
                if parts == ['ping']:
                    return self._reply(200, b'reel') if not head else self._reply(200, b'')
                if parts == ['have']:  # does this computer already have this title?
                    yes = q.get('id', [''])[0] in server.have
                    return self._reply(200, b'yes' if yes else b'no') if not head else self._reply(200, b'')
                if len(parts) < 2 or parts[1] not in server.files:
                    return self._deny()
                path = server.files[parts[1]]
                if parts[0] == 'subs':
                    names = [os.path.basename(p) for p in subtitle_files(path)]
                    body = json.dumps(names).encode()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    if not head:
                        self.wfile.write(body)
                    return
                if parts[0] == 'sub' and len(parts) == 3:
                    subs = subtitle_files(path)
                    try:
                        path = subs[int(parts[2])]
                    except (ValueError, IndexError):
                        return self._deny()
                elif parts[0] != 'v':
                    return self._deny()
                self.send_file(path, head)

            def send_file(self, path, head):
                try:
                    size = os.path.getsize(path)
                    f = open(path, 'rb')
                except OSError:
                    return self._deny()
                with f:
                    start, end = 0, size - 1
                    rng = self.headers.get('Range', '')
                    if rng.startswith('bytes='):
                        a, _, b = rng[6:].split(',')[0].partition('-')
                        if a:
                            start = int(a)
                            end = int(b) if b else size - 1
                        elif b:  # suffix range: last N bytes
                            start = max(0, size - int(b))
                        if start >= size:
                            self.send_response(416)
                            self.send_header('Content-Range', f'bytes */{size}')
                            self.send_header('Content-Length', '0')
                            self.end_headers()
                            return
                        end = min(end, size - 1)
                        self.send_response(206)
                        self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                    else:
                        self.send_response(200)
                    length = end - start + 1
                    ctype = mimetypes.guess_type(path)[0] or 'application/octet-stream'
                    if path.lower().endswith('.mkv'):
                        ctype = 'video/x-matroska'
                    self.send_header('Content-Type', ctype)
                    self.send_header('Accept-Ranges', 'bytes')
                    self.send_header('Content-Length', str(length))
                    self.end_headers()
                    if head:
                        return
                    f.seek(start)
                    try:
                        while length > 0:
                            buf = f.read(min(CHUNK, length))
                            if not buf:
                                break
                            self.wfile.write(buf)
                            length -= len(buf)
                    except (ConnectionError, OSError):
                        pass

        class Quiet(ThreadingHTTPServer):
            # on Windows SO_REUSEADDR lets a second Reel bind the SAME port and steal requests
            allow_reuse_address = sys.platform != 'win32'

            def handle_error(self, request, client_address):
                pass  # players drop connections all the time when seeking

        for port in PORTS:
            try:
                self.httpd = Quiet(('0.0.0.0', port), Handler)
                self.httpd.daemon_threads = True
                self.port = port
                break
            except OSError:
                continue
        if self.httpd:
            threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self.port

    def info(self):
        if not self.port:
            return None
        addrs = local_addresses()
        urls = [f'http://{a}:{self.port}' for a in addrs]
        if self.tunnel and self.tunnel.url:
            urls.append(self.tunnel.url)
        return {'addrs': addrs, 'port': self.port, 'token': self.token, 'urls': urls}

    def stop(self):
        if self.tunnel:
            self.tunnel.stop()
        if self.httpd:
            self.httpd.shutdown()


def cloudflared_path():
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib')
    for p in (os.path.join(here, 'cloudflared.exe'), os.path.join(here, 'cloudflared'),
              '/opt/homebrew/bin/cloudflared', '/usr/local/bin/cloudflared', shutil.which('cloudflared') or ''):
        if p and os.path.isfile(p):
            return p
    return None


class Tunnel:
    """A free Cloudflare quick tunnel: gives this computer a public https link, no account or router setup.
    The link changes each time it starts; Reel publishes the current one through Supabase."""

    def __init__(self, port, token, on_change):
        self.port, self.token, self.on_change = port, token, on_change
        self.url = None
        self.proc = None
        self.stopped = False

    def start(self):
        exe = cloudflared_path()
        if not exe or not self.port:
            return False
        threading.Thread(target=self._run, args=(exe,), daemon=True).start()
        return True

    def _run(self, exe):
        while not self.stopped:
            flags = 0x08000000 if sys.platform == 'win32' else 0  # no console window
            try:
                self.proc = subprocess.Popen([exe, 'tunnel', '--url', f'http://127.0.0.1:{self.port}', '--no-autoupdate'],
                                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                             creationflags=flags)
            except OSError:
                return
            for line in self.proc.stdout:
                m = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', line)
                if m and not self.url:
                    threading.Thread(target=self._verify, args=(m.group(0),), daemon=True).start()
            # tunnel died: forget the link and try again shortly
            if self.url:
                self.url = None
                self.on_change()
            time.sleep(10)

    def _verify(self, url):
        time.sleep(12)  # asking before the name exists gets "not found" cached for minutes
        for _ in range(30):
            if self.stopped:
                return
            try:
                if urllib.request.urlopen(f'{url}/ping?t={urllib.parse.quote(self.token)}', timeout=8).read() == b'reel':
                    self.url = url
                    self.on_change()
                    return
            except Exception:
                pass
            time.sleep(5)

    def stop(self):
        self.stopped = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
