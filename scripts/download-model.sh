#!/bin/sh
set -eu

model=${1:-}
case "$model" in
    tiny) sha1=bd577a113a864445d4c299885e0cb97d4ba92b5f ;;
    base) sha1=465707469ff3a37a2b9b8d8f89f2f99de7299dac ;;
    small) sha1=55356645c2b361a969dfd0ef2c5a50d530afd8d5 ;;
    medium) sha1=fd9727b6e1217c2f614f9b698455c4ffd82463b4 ;;
    large-v3) sha1=ad82bf6a9043ceed055076d0fd39f5f186ff8062 ;;
    *) echo "Unbekanntes Whisper-Modell." >&2; exit 2 ;;
esac

data_dir=${XDG_DATA_HOME:-"$HOME/.local/share"}/opentalk
repo="$data_dir/whisper.cpp"
destination="$repo/models/ggml-$model.bin"
if [ ! -f "$repo/models/download-ggml-model.sh" ]; then
    echo "whisper.cpp fehlt. Zuerst die lokale Erkennung einrichten." >&2
    exit 1
fi
if [ -f "$destination" ] && printf '%s  %s\n' "$sha1" "$destination" | sha1sum -c -; then
    echo "Modell $model ist bereits installiert."
    exit 0
fi

temporary=$(mktemp -d "$repo/models/.opentalk-download.XXXXXX")
trap 'rm -rf "$temporary"' EXIT HUP INT TERM
echo "Lade das mehrsprachige Whisper-Modell $model …"
sh "$repo/models/download-ggml-model.sh" "$model" "$temporary"
printf '%s  %s\n' "$sha1" "$temporary/ggml-$model.bin" | sha1sum -c -
mv "$temporary/ggml-$model.bin" "$destination"
echo "Modell $model ist bereit."
