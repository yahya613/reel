# Reel for Windows - installer.
#   powershell -ExecutionPolicy Bypass -File install\windows\install.ps1
# Installs to %LOCALAPPDATA%\Programs\Reel with its own Python environment, the mpv video engine
# and the Cloudflare sharing tunnel, then adds Desktop + Start menu shortcuts.
param(
    [string]$Dest = "$env:LOCALAPPDATA\Programs\Reel",
    [switch]$NoShortcuts,
    [switch]$NoLaunch
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
function Say($t) { Write-Host "`n==> $t" -ForegroundColor Cyan }
$UA = @{ 'User-Agent' = 'reel-installer' }

Say 'Installing Reel for Windows'

# 1. Python 3.12+ ------------------------------------------------------------------
$py = $null
foreach ($v in '3.14', '3.13', '3.12') {
    try {
        $exe = (& py "-$v" -c "import sys; print(sys.executable)" 2>$null)
        if ($LASTEXITCODE -eq 0 -and $exe) { $py = $exe.Trim(); break }
    } catch {}
}
if (-not $py) {
    Say 'Installing Python 3.13 (winget)'
    winget install --id Python.Python.3.13 --scope user --silent --accept-package-agreements --accept-source-agreements
    $py = "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
    if (-not (Test-Path $py)) { throw 'Python install failed - install Python 3.13 from python.org and run this again.' }
}
Write-Host "Python: $py"

# 2. App files + private environment ------------------------------------------------------
Say "Copying Reel to $Dest"
New-Item -ItemType Directory -Force "$Dest\lib", "$Dest\tools" | Out-Null
foreach ($f in 'reel.pyw', 'library.py', 'media.py', 'player.py', 'browse.py', 'theme.py', 'cloud.py', 'server.py',
               'supabase.sql', 'requirements.txt') {
    Copy-Item (Join-Path $Root $f) $Dest -Force
}
Copy-Item (Join-Path $Root 'tools\seal.py') "$Dest\tools" -Force
if (-not (Test-Path "$Dest\.venv\Scripts\python.exe")) { & $py -m venv "$Dest\.venv" }
$vpy = "$Dest\.venv\Scripts\python.exe"
& $vpy -m pip install --quiet --upgrade pip
& $vpy -m pip install --quiet -r "$Dest\requirements.txt"
if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }

# 3. mpv video engine (libmpv) ------------------------------------------------------
if (-not (Test-Path "$Dest\lib\libmpv-2.dll")) {
    Say 'Downloading the mpv video engine'
    $rel = Invoke-RestMethod 'https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/latest' -Headers $UA
    $asset = $rel.assets | Where-Object { $_.name -like 'mpv-dev-x86_64-2*.7z' } | Select-Object -First 1
    $tmp = Join-Path $env:TEMP "reel-mpv-$(Get-Random)"
    New-Item -ItemType Directory $tmp | Out-Null
    Invoke-WebRequest $asset.browser_download_url -OutFile "$tmp\mpv.7z" -Headers $UA
    & tar -xf "$tmp\mpv.7z" -C $tmp libmpv-2.dll 2>$null   # Windows' built-in tar reads 7z
    if (-not (Test-Path "$tmp\libmpv-2.dll") -or (Get-Item "$tmp\libmpv-2.dll").Length -lt 1MB) {
        Invoke-WebRequest 'https://www.7-zip.org/a/7zr.exe' -OutFile "$tmp\7zr.exe" -Headers $UA  # official 7-Zip
        & "$tmp\7zr.exe" e "$tmp\mpv.7z" "-o$tmp" libmpv-2.dll -y | Out-Null
    }
    if (-not (Test-Path "$tmp\libmpv-2.dll") -or (Get-Item "$tmp\libmpv-2.dll").Length -lt 1MB) { throw 'Could not unpack the mpv engine.' }
    Copy-Item "$tmp\libmpv-2.dll" "$Dest\lib\" -Force
    Remove-Item $tmp -Recurse -Force
}

# 4. Cloudflare tunnel (lets your other computers stream from anywhere) ---------------
if (-not (Test-Path "$Dest\lib\cloudflared.exe")) {
    Say 'Downloading the sharing tunnel (cloudflared)'
    $rel = Invoke-RestMethod 'https://api.github.com/repos/cloudflare/cloudflared/releases/latest' -Headers $UA
    $asset = $rel.assets | Where-Object { $_.name -eq 'cloudflared-windows-amd64.exe' }
    Invoke-WebRequest $asset.browser_download_url -OutFile "$Dest\lib\cloudflared.exe" -Headers $UA
}

# 5. Cloud sync settings (encrypted in the repo) -------------------------------------
$enc = Join-Path $Root 'secrets\seed.json.enc'
if ((Test-Path $enc) -and -not (Test-Path "$Dest\seed.json")) {
    Say 'Unlock your cloud sync settings'
    & $vpy "$Dest\tools\seal.py" open $enc "$Dest\seed.json"
}

# 6. Icon + shortcuts --------------------------------------------------------------
& $vpy -c "import sys; sys.path.insert(0, sys.argv[1]); from PyQt6.QtWidgets import QApplication; a = QApplication([]); from theme import app_icon; app_icon(256).save(sys.argv[2])" $Dest "$Dest\reel.ico"
$pyw = "$Dest\.venv\Scripts\pythonw.exe"
if (-not $NoShortcuts) {
    $ws = New-Object -ComObject WScript.Shell
    foreach ($dir in [Environment]::GetFolderPath('Desktop'), "$env:APPDATA\Microsoft\Windows\Start Menu\Programs") {
        $lnk = $ws.CreateShortcut("$dir\Reel.lnk")
        $lnk.TargetPath = $pyw
        $lnk.Arguments = "`"$Dest\reel.pyw`""
        $lnk.WorkingDirectory = $Dest
        $lnk.IconLocation = "$Dest\reel.ico"
        $lnk.Description = 'Reel - movies and TV'
        $lnk.Save()
    }
}

Say 'Done! Reel is installed.'
Write-Host '   Windows may ask to let Reel through the firewall - click Allow so your other computers can stream.'
if (-not $NoLaunch) { Start-Process $pyw -ArgumentList "`"$Dest\reel.pyw`"" -WorkingDirectory $Dest }

