#!/bin/sh
set -eu

if [ "$(uname -s)-$(uname -m)" != "Darwin-arm64" ]; then
    echo "Dieser Installer ist ausschließlich für Macs mit M-Prozessor (Apple Silicon)." >&2
    echo "Intel-Macs werden nicht unterstützt." >&2
    exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew fehlt. Zuerst von https://brew.sh installieren." >&2
    exit 1
fi
brew_prefix=$(brew --prefix)
export PATH="$brew_prefix/bin:/usr/bin:/bin:/usr/sbin:/sbin"
python_bin=""
python_prefix=$(brew --prefix python 2>/dev/null || true)
for candidate in "$python_prefix/libexec/bin/python3" "$brew_prefix"/bin/python3.[0-9]*; do
    if [ -x "$candidate" ] && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' 2>/dev/null; then
        python_bin=$candidate
        break
    fi
done
if [ -z "$python_bin" ]; then
    echo "Homebrew-Python fehlt. Installieren mit: brew install python" >&2
    exit 1
fi

for dependency in cmake ffmpeg git; do
    if ! command -v "$dependency" >/dev/null 2>&1; then
        echo "$dependency fehlt. Mit Homebrew installieren: brew install python cmake ffmpeg git" >&2
        exit 1
    fi
done

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ -n "${XDG_DATA_HOME:-}" ]; then
    data_dir="$XDG_DATA_HOME/opentalk"
else
    data_dir="$HOME/Library/Application Support/OpenTalk"
fi
app_source="$data_dir/app"
venv="$data_dir/venv"
app_bundle="$HOME/Applications/OpenTalk.app"

mkdir -p "$app_source/scripts" "$app_bundle/Contents/MacOS" "$app_bundle/Contents/Resources"
cp "$project_dir/opentalk.py" "$project_dir/opentalk_gui.py" \
   "$project_dir/audio_sources.py" "$project_dir/live_dictation.py" \
   "$project_dir/model_setup.py" "$app_source/"
cp "$project_dir/scripts/gui.sh" "$project_dir/scripts/setup-model.sh" \
   "$project_dir/scripts/download-model.sh" "$app_source/scripts/"
if [ -f "$project_dir/config.local.sh" ]; then
    cp "$project_dir/config.local.sh" "$app_source/config.local.sh"
    chmod 600 "$app_source/config.local.sh"
fi

if [ ! -x "$venv/bin/python" ]; then
    "$python_bin" -m venv "$venv"
fi
"$venv/bin/python" -m pip install --upgrade PyQt6 pynput

launcher="$app_bundle/Contents/MacOS/OpenTalk"
cat > "$launcher" <<EOF
#!/bin/sh
export PATH="$brew_prefix/bin:/usr/bin:/bin:/usr/sbin:/sbin"
exec "$venv/bin/python" "$app_source/opentalk_gui.py"
EOF
chmod +x "$launcher" "$app_source/scripts/"*.sh

cat > "$app_bundle/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>OpenTalk</string>
  <key>CFBundleDisplayName</key><string>OpenTalk</string>
  <key>CFBundleIdentifier</key><string>dev.k1ra.opentalk</string>
  <key>CFBundleExecutable</key><string>OpenTalk</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>LSUIElement</key><true/>
  <key>NSMicrophoneUsageDescription</key>
  <string>OpenTalk benötigt das Mikrofon für die lokale Spracheingabe.</string>
</dict></plist>
EOF

echo "OpenTalk wurde als $app_bundle installiert."
echo "Beim ersten Start Mikrofon und Bedienungshilfen erlauben."
