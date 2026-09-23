#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ -f "$project_dir/config.local.sh" ]; then
    . "$project_dir/config.local.sh"
fi
exec python3 "$project_dir/sprechschrift.py" toggle
