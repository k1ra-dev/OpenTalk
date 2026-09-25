#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ -f "$project_dir/config.local.sh" ]; then
    . "$project_dir/config.local.sh"
fi
. "$project_dir/scripts/python.sh"
exec "$OPENTALK_PYTHON" "$project_dir/opentalk.py" toggle
