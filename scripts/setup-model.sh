#!/bin/sh
set -eu
case "$(uname -s)-$(uname -m)" in
    Darwin-arm64)
        if [ -n "${XDG_DATA_HOME:-}" ]; then
            data_dir="$XDG_DATA_HOME/opentalk"
        else
            data_dir="$HOME/Library/Application Support/OpenTalk"
        fi
        ;;
    Darwin-*) echo "OpenTalk unterstützt auf macOS nur M-Prozessoren (Apple Silicon)." >&2; exit 1 ;;
    *) data_dir=${XDG_DATA_HOME:-"$HOME/.local/share"}/opentalk ;;
esac
repo="$data_dir/whisper.cpp"
mkdir -p "$data_dir"
if command -v cmake >/dev/null 2>&1; then
    cmake_cmd=cmake
elif [ "$(uname -s)-$(uname -m)" = "Linux-x86_64" ]; then
    version=4.3.2
    archive="$data_dir/cmake-$version-linux-x86_64.tar.gz"
    cmake_cmd="$data_dir/cmake-$version-linux-x86_64/bin/cmake"
    if [ ! -x "$cmake_cmd" ]; then
        echo "Lade CMake in den Benutzerordner …"
        curl -fL --retry 3 -o "$archive" "https://github.com/Kitware/CMake/releases/download/v$version/cmake-$version-linux-x86_64.tar.gz"
        printf '%s  %s\n' '791ae3604841ca03cb3889a3ad89165346e4b180ae3448efd4b0caa9ef46d245' "$archive" | sha256sum -c -
        tar -xzf "$archive" -C "$data_dir"
        rm "$archive"
    fi
else
    echo "CMake fehlt. Bitte CMake installieren und erneut versuchen." >&2
    exit 1
fi
if [ ! -d "$repo/.git" ]; then
    echo "Lade whisper.cpp …"
    git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git "$repo"
fi
echo "Baue whisper-cli …"
"$cmake_cmd" -S "$repo" -B "$repo/build" -DCMAKE_BUILD_TYPE=Release
"$cmake_cmd" --build "$repo/build" --target whisper-cli -j 2
if [ ! -s "$repo/models/ggml-small.bin" ] || [ "$(wc -c < "$repo/models/ggml-small.bin")" -lt 400000000 ]; then
    if [ -f "$repo/models/ggml-small.bin" ]; then
        rm "$repo/models/ggml-small.bin"
    fi
    echo "Lade mehrsprachiges small-Modell …"
    (cd "$repo" && sh ./models/download-ggml-model.sh small)
fi
if [ "$(wc -c < "$repo/models/ggml-small.bin")" -lt 400000000 ]; then
    echo "Modelldatei ist unvollständig." >&2
    exit 1
fi
if [ ! -s "$repo/models/ggml-silero-v6.2.0.bin" ] || [ "$(wc -c < "$repo/models/ggml-silero-v6.2.0.bin")" -lt 100000 ]; then
    if [ -f "$repo/models/ggml-silero-v6.2.0.bin" ]; then
        rm "$repo/models/ggml-silero-v6.2.0.bin"
    fi
    echo "Lade Spracherkennung für Pausen und Hintergrundgeräusche …"
    (cd "$repo" && sh ./models/download-vad-model.sh silero-v6.2.0)
fi
if [ "$(wc -c < "$repo/models/ggml-silero-v6.2.0.bin")" -lt 100000 ]; then
    echo "VAD-Modelldatei ist unvollständig." >&2
    exit 1
fi
echo "Einrichtung abgeschlossen."
