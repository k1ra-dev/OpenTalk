#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ -f "$project_dir/config.local.sh" ]; then
    . "$project_dir/config.local.sh"
fi
case "${XDG_CURRENT_DESKTOP:-}" in
    *Hyprland*|*hyprland*)
        if [ -n "${WAYLAND_DISPLAY:-}" ]; then
            export QT_QPA_PLATFORM=wayland
        fi
        ;;
esac
. "$project_dir/scripts/python.sh"
exec "$OPENTALK_PYTHON" "$project_dir/opentalk_gui.py"
