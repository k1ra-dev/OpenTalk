#!/bin/sh
set -eu

if [ "$(uname -s)" != "Linux" ]; then
    echo "Dieser Installer ist nur für Linux. Auf einem M-Mac bitte install-macos.sh verwenden." >&2
    exit 1
fi

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec "$project_dir/scripts/install-desktop.sh"
