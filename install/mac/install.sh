#!/bin/bash
# Reel for Mac - installer.
#   From the repo:   bash install/mac/install.sh
#   From a download: bash ~/Downloads/Reel-Mac/install/mac/install.sh
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$HERE/../../reel.pyw" ]; then ROOT="$(cd "$HERE/../.." && pwd)"; else ROOT="$HERE"; fi
DEST="$HOME/Reel"
APP="$HOME/Applications/Reel.app"
say() { printf "\n\033[1;34m==>\033[0m \033[1m%s\033[0m\n" "$1"; }
load_brew() { for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)" && return 0; done; return 1; }

say "Installing Reel for Mac"
command -v brew >/dev/null 2>&1 || load_brew || {
  say "Installing Homebrew first (it asks for your Mac password - typing is invisible, that's normal)"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  load_brew
}

say "Installing the mpv video engine, Python and the sharing tunnel (a few minutes the first time)"
brew install mpv python@3.13 cloudflared
PY="$(brew --prefix python@3.13)/bin/python3.13"

say "Copying Reel to $DEST"
mkdir -p "$DEST/tools"
for f in reel.pyw library.py media.py player.py browse.py theme.py cloud.py server.py supabase.sql requirements.txt; do
  [ -f "$ROOT/$f" ] && cp "$ROOT/$f" "$DEST/"
done
[ -f "$ROOT/tools/seal.py" ] && cp "$ROOT/tools/seal.py" "$DEST/tools/"
[ -d "$DEST/.venv" ] || "$PY" -m venv "$DEST/.venv"
"$DEST/.venv/bin/python" -m pip install --quiet --upgrade pip
"$DEST/.venv/bin/python" -m pip install --quiet --upgrade PyQt6 python-mpv cryptography

# cloud settings: plain seed.json (older downloads) or the encrypted one from the repo
if [ -f "$ROOT/seed.json" ]; then
  cp "$ROOT/seed.json" "$DEST/seed.json"
elif [ -f "$ROOT/secrets/seed.json.enc" ] && [ ! -f "$DEST/seed.json" ]; then
  say "Unlock your cloud sync settings"
  "$DEST/.venv/bin/python" "$DEST/tools/seal.py" open "$ROOT/secrets/seed.json.enc" "$DEST/seed.json" </dev/tty || true
fi

say "Building Reel.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cat > "$APP/Contents/MacOS/Reel" <<EOF
#!/bin/bash
export DYLD_FALLBACK_LIBRARY_PATH="$(brew --prefix)/lib:/usr/local/lib:/usr/lib"
export PATH="$(brew --prefix)/bin:\$PATH"
exec "$DEST/.venv/bin/python" "$DEST/reel.pyw" "\$@"
EOF
chmod +x "$APP/Contents/MacOS/Reel"

TMP="$(mktemp -d)"
QT_QPA_PLATFORM=offscreen "$DEST/.venv/bin/python" - "$DEST" "$TMP/icon.png" <<'PYEOF'
import sys; sys.path.insert(0, sys.argv[1])
from PyQt6.QtGui import QGuiApplication
app = QGuiApplication([])
from theme import app_icon
app_icon(1024).save(sys.argv[2])
PYEOF
mkdir -p "$TMP/Reel.iconset"
for s in 16 32 128 256 512; do
  sips -z $s $s "$TMP/icon.png" --out "$TMP/Reel.iconset/icon_${s}x${s}.png" >/dev/null
  d=$((s * 2)); sips -z $d $d "$TMP/icon.png" --out "$TMP/Reel.iconset/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$TMP/Reel.iconset" -o "$APP/Contents/Resources/Reel.icns" || true

cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Reel</string>
  <key>CFBundleDisplayName</key><string>Reel</string>
  <key>CFBundleIdentifier</key><string>app.reel.player</string>
  <key>CFBundleExecutable</key><string>Reel</string>
  <key>CFBundleIconFile</key><string>Reel</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.entertainment</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSDownloadsFolderUsageDescription</key><string>Reel looks for movies and shows in your Downloads.</string>
  <key>NSDesktopFolderUsageDescription</key><string>Reel looks for movies and shows on your Desktop.</string>
  <key>NSDocumentsFolderUsageDescription</key><string>Reel looks for movies and shows in Documents.</string>
  <key>NSRemovableVolumesUsageDescription</key><string>Reel looks for movies and shows on external drives.</string>
  <key>CFBundleDocumentTypes</key><array><dict>
    <key>CFBundleTypeName</key><string>Video</string>
    <key>CFBundleTypeRole</key><string>Viewer</string>
    <key>LSHandlerRank</key><string>Alternate</string>
    <key>LSItemContentTypes</key><array>
      <string>public.movie</string><string>public.video</string><string>public.mpeg-4</string>
      <string>com.apple.quicktime-movie</string><string>org.matroska.mkv</string><string>public.avi</string>
    </array>
  </dict></array>
</dict></plist>
EOF
touch "$APP"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP" 2>/dev/null || true
rm -rf "$TMP"

say "Done! Reel is in ~/Applications/Reel.app. Opening it now…"
echo "   Tip: drag it to your Dock. If macOS asks to access Downloads/Desktop, click Allow."
open "$APP"
