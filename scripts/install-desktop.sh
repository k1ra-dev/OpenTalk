#!/bin/sh
set -eu

if [ "$(uname -s)" != "Linux" ]; then
    echo "Dieser Installer ist nur für Linux. Auf einem M-Mac bitte install-macos.sh verwenden." >&2
    exit 1
fi

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
data_home=${XDG_DATA_HOME:-"$HOME/.local/share"}
app_dir="$data_home/opentalk/app"
applications_dir="$data_home/applications"
icons_dir="$data_home/icons/hicolor/scalable/apps"

mkdir -p "$app_dir/scripts" "$app_dir/build" "$applications_dir" "$icons_dir"
cp "$project_dir/opentalk.py" "$project_dir/opentalk_gui.py" \
   "$project_dir/audio_sources.py" "$project_dir/live_dictation.py" "$project_dir/model_setup.py" \
   "$project_dir/layer_shell_bridge.cpp" "$app_dir/"
cp "$project_dir/scripts/gui.sh" "$project_dir/scripts/setup-model.sh" \
   "$project_dir/scripts/download-model.sh" "$app_dir/scripts/"
if [ -f "$project_dir/config.local.sh" ]; then
    cp "$project_dir/config.local.sh" "$app_dir/config.local.sh"
    chmod 600 "$app_dir/config.local.sh"
fi
if [ -f "$project_dir/build/libopentalk-layer.so" ]; then
    cp "$project_dir/build/libopentalk-layer.so" "$app_dir/build/"
fi
chmod +x "$app_dir/scripts/gui.sh" "$app_dir/scripts/setup-model.sh" \
    "$app_dir/scripts/download-model.sh"
cp "$project_dir/assets/opentalk.svg" "$icons_dir/opentalk.svg"

desktop_file="$applications_dir/opentalk.desktop"
cat > "$desktop_file" <<EOF
[Desktop Entry]
Type=Application
Name=OpenTalk
GenericName=Spracheingabe
Comment=Lokale Spracheingabe direkt ins Textfeld
Exec=$app_dir/scripts/gui.sh
Path=$app_dir
Icon=opentalk
Terminal=false
Categories=Utility;Accessibility;
StartupNotify=false
EOF

if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$desktop_file"
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$applications_dir" >/dev/null
fi
echo "OpenTalk wurde im App-Menü installiert."
