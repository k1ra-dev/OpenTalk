#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"

case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) package=mac ;;
    Linux-x86_64) package=linux ;;
    *) echo "Release-Build nur für Linux x86_64 oder macOS arm64." >&2; exit 1 ;;
esac

if [ -z "${WHISPER_CLI_BINARY:-}" ] || [ ! -x "$WHISPER_CLI_BINARY" ]; then
    echo "WHISPER_CLI_BINARY muss auf ein ausführbares whisper-cli zeigen." >&2
    exit 1
fi
if [ "$package" = mac ] && { [ -z "${FFMPEG_BINARY:-}" ] || [ ! -x "$FFMPEG_BINARY" ]; }; then
    echo "FFMPEG_BINARY muss beim Mac-Build auf ein ausführbares FFmpeg zeigen." >&2
    exit 1
fi

rm -rf build/OpenTalk build/OpenTalk-binaries dist/OpenTalk dist/OpenTalk.app artifacts
mkdir -p artifacts build/OpenTalk-binaries
cp "$WHISPER_CLI_BINARY" build/OpenTalk-binaries/whisper-cli
chmod +x build/OpenTalk-binaries/whisper-cli
WHISPER_CLI_BINARY="$project_dir/build/OpenTalk-binaries/whisper-cli"
export WHISPER_CLI_BINARY
if [ "$package" = mac ]; then
    cp "$FFMPEG_BINARY" build/OpenTalk-binaries/ffmpeg
    chmod +x build/OpenTalk-binaries/ffmpeg
    FFMPEG_BINARY="$project_dir/build/OpenTalk-binaries/ffmpeg"
    export FFMPEG_BINARY
fi
python_cmd=${PYTHON:-python3}
PYINSTALLER_CONFIG_DIR=${PYINSTALLER_CONFIG_DIR:-"${TMPDIR:-/tmp}/opentalk-pyinstaller-cache"}
export PYINSTALLER_CONFIG_DIR
"$python_cmd" -m PyInstaller --clean --noconfirm packaging/OpenTalk.spec

if [ "$package" = mac ]; then
    codesign --force --deep --sign - dist/OpenTalk.app
    ditto -c -k --sequesterRsrc --keepParent \
        dist/OpenTalk.app artifacts/OpenTalk-macOS-arm64.zip
else
    tar -C dist -czf artifacts/OpenTalk-Linux-x86_64.tar.gz OpenTalk
fi

echo "Release-Datei erstellt:"
ls -lh artifacts/OpenTalk-*
