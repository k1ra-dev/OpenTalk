#!/bin/sh
# Source this from another launcher. Explicit overrides win over the checkout
# venv; installed launchers use .python-path to retain their original interpreter.
if [ -z "${OPENTALK_PYTHON:-}" ]; then
    if [ -x "$project_dir/.venv/bin/python" ]; then
        OPENTALK_PYTHON="$project_dir/.venv/bin/python"
    elif [ -f "$project_dir/.python-path" ]; then
        IFS= read -r OPENTALK_PYTHON < "$project_dir/.python-path"
    else
        OPENTALK_PYTHON=python3
    fi
fi
export OPENTALK_PYTHON
