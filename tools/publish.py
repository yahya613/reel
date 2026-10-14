"""Publish Reel: refresh the one-paste installer (secret gist) and/or make a GitHub release with download zips.

    python tools/publish.py gist              # create/update the loader gist from the current files
    python tools/publish.py release v1.0.0    # tag + release with Reel-Windows.zip and Reel-Mac.zip

Auth comes from Git Credential Manager (account below); the token is never printed.
"""
import io, json, os, subprocess, sys, urllib.request, zipfile

OWNER = 'yahya613'
REPO = 'reel'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GIST_FILE = os.path.join(ROOT, 'tools', 'gist_id.txt')
APP_FILES = ['reel.pyw', 'library.py', 'media.py', 'player.py', 'browse.py', 'theme.py', 'cloud.py', 'server.py',
             'downloads.py', 'subsync.py', 'supabase.sql', 'requirements.txt', 'tools/seal.py', 'secrets/seed.json.enc',
             'install/mac/install.sh', 'install/windows/install.ps1']

GET_SH = r'''#!/bin/bash
# Reel one-paste installer for Mac (layer 2).
# Layer 1 (what you paste):  curl -fsSL {base}/get.sh | bash
# Layer 3: install/mac/install.sh sets up Homebrew, Python, mpv and Reel.app - no Python needed beforehand.
main() {{
  set -e
  BASE="{base}"
  DIR="$HOME/.reel-setup"
  rm -rf "$DIR"; mkdir -p "$DIR"
  printf "\n\033[1;34m==>\033[0m \033[1mDownloading Reel\033[0m\n"
  curl -fsSL "$BASE/manifest.txt" -o "$DIR/manifest.txt"
  while IFS= read -r f; do
    f="${{f%$'\r'}}"
    [ -z "$f" ] && continue
    dest="$DIR/${{f//__//}}"
    mkdir -p "$(dirname "$dest")"
    curl -fsSL "$BASE/$f" -o "$dest"
  done < "$DIR/manifest.txt"
  bash "$DIR/install/mac/install.sh" </dev/tty
}}
main "$@"
'''

GET_PS1 = r'''# Reel one-paste installer for Windows (layer 2).
# Layer 1 (what you paste in PowerShell):
#   [Net.ServicePointManager]::SecurityProtocol='Tls12'; irm {base}/get.ps1 | iex
# Layer 3: install\windows\install.ps1 installs Python (if missing), mpv and Reel with shortcuts.
& {{
  $ErrorActionPreference = 'Stop'
  $ProgressPreference = 'SilentlyContinue'
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  $base = '{base}'
  $dir = Join-Path $env:TEMP 'reel-setup'
  if (Test-Path $dir) {{ Remove-Item $dir -Recurse -Force }}
  New-Item -ItemType Directory $dir | Out-Null
  Write-Host "`n==> Downloading Reel" -ForegroundColor Cyan
  $list = ((Invoke-WebRequest "$base/manifest.txt" -UseBasicParsing).Content -split "`n") | ForEach-Object {{ $_.Trim() }} | Where-Object {{ $_ }}
  foreach ($f in $list) {{
    $dest = Join-Path $dir ($f -replace '__', '\')
    New-Item -ItemType Directory -Force (Split-Path $dest) | Out-Null
    Invoke-WebRequest "$base/$f" -OutFile $dest -UseBasicParsing
  }}
  powershell -NoProfile -ExecutionPolicy Bypass -File "$dir\install\windows\install.ps1"
}}
'''

# App files refreshed by a quick update (no Python/mpv/brew re-download).
RUNTIME = ['reel.pyw', 'library.py', 'media.py', 'player.py', 'browse.py', 'theme.py', 'cloud.py', 'server.py',
           'downloads.py', 'subsync.py', 'supabase.sql', 'requirements.txt', 'tools/seal.py']

UPDATE_SH = '''#!/bin/bash
# Update an existing Reel install (Mac). Paste:  curl -fsSL {base}/update.sh | bash
main() {{
  set -e
  BASE="{base}"; DEST="$HOME/Reel"
  [ -f "$DEST/reel.pyw" ] || {{ echo "Reel isn't installed in ~/Reel - run the full installer instead."; exit 1; }}
  printf "\\n\\033[1;34m==>\\033[0m \\033[1mUpdating Reel\\033[0m\\n"
  for f in {files}; do
    dest="$DEST/${{f//__//}}"; mkdir -p "$(dirname "$dest")"
    curl -fsSL "$BASE/$f" -o "$dest"
  done
  "$DEST/.venv/bin/python" -m pip install --quiet -r "$DEST/requirements.txt" >/dev/null 2>&1 || true
  pkill -f 'Reel/reel.pyw' 2>/dev/null || true; sleep 1
  echo "Updated. Reopening Reel…"
  open -a "$HOME/Applications/Reel.app" 2>/dev/null || ( "$DEST/.venv/bin/python" "$DEST/reel.pyw" >/dev/null 2>&1 & )
}}
main "$@"
'''

UPDATE_PS1 = '''# Update an existing Reel install (Windows). Paste in PowerShell:
#   [Net.ServicePointManager]::SecurityProtocol='Tls12'; irm {base}/update.ps1 | iex
& {{
  $ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'
  [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
  $base='{base}'
  $dest = Join-Path $env:LOCALAPPDATA 'Programs\\Reel'
  if (-not (Test-Path "$dest\\reel.pyw")) {{ $dest = 'C:\\Reel' }}
  if (-not (Test-Path "$dest\\reel.pyw")) {{ Write-Host 'Reel not found - run the full installer first.' -ForegroundColor Yellow; return }}
  Write-Host "`n==> Updating Reel" -ForegroundColor Cyan
  Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object {{ $_.CommandLine -like '*reel.pyw*' }} |
    ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}
  foreach ($f in @({winfiles})) {{
    $d = Join-Path $dest ($f -replace '__', '\\')
    New-Item -ItemType Directory -Force (Split-Path $d) | Out-Null
    Invoke-WebRequest "$base/$f" -OutFile $d -UseBasicParsing
  }}
  $py = Join-Path $dest '.venv\\Scripts\\python.exe'
  if (Test-Path $py) {{ & $py -m pip install --quiet -r "$dest\\requirements.txt" 2>$null }}
  $pyw = Join-Path $dest '.venv\\Scripts\\pythonw.exe'
  if (-not (Test-Path $pyw)) {{ $pyw = 'pythonw' }}
  Write-Host 'Updated. Reopening Reel…' -ForegroundColor Green
  Start-Process $pyw -ArgumentList "`"$dest\\reel.pyw`"" -WorkingDirectory $dest
}}
'''


def token():
    out = subprocess.run(['git', 'credential', 'fill'], input=f'protocol=https\nhost=github.com\nusername={OWNER}\n\n',
                         capture_output=True, text=True, check=True).stdout
    return next(l[9:] for l in out.splitlines() if l.startswith('password='))


def api(method, url, body=None, data=None, ctype='application/json'):
    if not url.startswith('http'):
        url = 'https://api.github.com' + url
    payload = data if data is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=payload, method=method, headers={
        'Authorization': f'Bearer {token()}', 'Accept': 'application/vnd.github+json', 'User-Agent': 'reel-publish',
        'Content-Type': ctype})
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def read(rel):
    return open(os.path.join(ROOT, rel), encoding='utf-8-sig').read().replace('\r\n', '\n')


def gist():
    gid = open(GIST_FILE).read().strip() if os.path.exists(GIST_FILE) else None
    if not gid:
        g = api('POST', '/gists', {'description': 'Reel installer', 'public': False,
                                   'files': {'README.md': {'content': '# Reel installer\nSee get.sh / get.ps1.\n'}}})
        gid = g['id']
        open(GIST_FILE, 'w').write(gid + '\n')
    base = f'https://gist.githubusercontent.com/{OWNER}/{gid}/raw'
    files = {f.replace('/', '__'): {'content': read(f)} for f in APP_FILES}
    files['manifest.txt'] = {'content': '\n'.join(f.replace('/', '__') for f in APP_FILES) + '\n'}
    files['get.sh'] = {'content': GET_SH.format(base=base)}
    files['get.ps1'] = {'content': GET_PS1.format(base=base)}
    files['update.sh'] = {'content': UPDATE_SH.format(base=base, files=' '.join(f.replace('/', '__') for f in RUNTIME))}
    files['update.ps1'] = {'content': UPDATE_PS1.format(
        base=base, winfiles=','.join(f"'{f.replace('/', '__')}'" for f in RUNTIME))}
    win = f"[Net.ServicePointManager]::SecurityProtocol='Tls12'; irm {base}/{{}} | iex"
    files['README.md'] = {'content':
        f'# Reel installer\n\n## Install\n**Mac** (Terminal):\n```\ncurl -fsSL {base}/get.sh | bash\n```\n'
        f'**Windows** (PowerShell):\n```\n{win.format("get.ps1")}\n```\n\n'
        f'## Update (keeps settings; faster)\n**Mac**:\n```\ncurl -fsSL {base}/update.sh | bash\n```\n'
        f'**Windows**:\n```\n{win.format("update.ps1")}\n```\n'}
    api('PATCH', f'/gists/{gid}', {'description': 'Reel installer', 'files': files})
    print('gist', gid)
    print('INSTALL MAC', f'curl -fsSL {base}/get.sh | bash')
    print('INSTALL WIN', win.format('get.ps1'))
    print('UPDATE  MAC', f'curl -fsSL {base}/update.sh | bash')
    print('UPDATE  WIN', win.format('update.ps1'))


def release(tag):
    zips = {}
    for name in ('Reel-Windows', 'Reel-Mac'):
        zips[name] = subprocess.run(['git', '-C', ROOT, 'archive', '--format=zip', f'--prefix={name}/', 'HEAD'],
                                    capture_output=True, check=True).stdout
    rel = api('POST', f'/repos/{OWNER}/{REPO}/releases', {
        'tag_name': tag, 'name': f'Reel {tag}', 'target_commitish': 'main',
        'body': 'Downloads:\n- **Reel-Windows.zip**: unzip, then double-click `Install Reel (Windows).bat`\n'
                '- **Reel-Mac.zip**: unzip, then run `bash ~/Downloads/Reel-Mac/install/mac/install.sh` in Terminal\n\n'
                'Both installers ask for your Reel passphrase to unlock cloud sync (Enter skips).'})
    up = rel['upload_url'].split('{')[0]
    for name, data in zips.items():
        api('POST', f'{up}?name={name}.zip', data=data, ctype='application/zip')
        print('uploaded', name, len(data), 'bytes')
    print('release', rel['html_url'])


if __name__ == '__main__':
    if sys.argv[1:2] == ['gist']:
        gist()
    elif sys.argv[1:2] == ['release'] and len(sys.argv) == 3:
        release(sys.argv[2])
    else:
        print(__doc__)
