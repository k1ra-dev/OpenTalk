import os
from pathlib import Path
import platform

root = Path(SPECPATH).parent
whisper_cli = os.environ.get("WHISPER_CLI_BINARY", "")
whisper_server = os.environ.get("WHISPER_SERVER_BINARY", "")
ffmpeg = os.environ.get("FFMPEG_BINARY", "")

if not whisper_cli or not Path(whisper_cli).is_file():
    raise SystemExit("WHISPER_CLI_BINARY fehlt oder zeigt nicht auf whisper-cli")

binaries = [(whisper_cli, "bin")]
if platform.system() in ("Darwin", "Windows"):
    if platform.machine() != "arm64":
        if platform.system() == "Darwin":
            raise SystemExit("Das macOS-Release darf nur auf arm64 gebaut werden")
    if not ffmpeg or not Path(ffmpeg).is_file():
        raise SystemExit("FFMPEG_BINARY fehlt für das macOS-/Windows-Release")
    binaries.append((ffmpeg, "bin"))
if not whisper_server or not Path(whisper_server).is_file():
    raise SystemExit("WHISPER_SERVER_BINARY fehlt für das Release")
binaries.append((whisper_server, "bin"))

datas = [
    (str(root / "assets" / "opentalk.svg"), "assets"),
    (str(root / "README.md"), "."),
    (str(root / "LICENSE"), "."),
    (str(root / "layer_shell_bridge.cpp"), "."),
]

hotkey_backend = {
    "Darwin": "pynput.keyboard._darwin",
    "Windows": "pynput.keyboard._win32",
    "Linux": "pynput.keyboard._xorg",
}.get(platform.system())

a = Analysis(
    [str(root / "opentalk_gui.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[hotkey_backend] if hotkey_backend else [],
    # Source Windows installs use imageio's FFmpeg. Releases already carry the
    # same executable in bin/; excluding the fallback avoids a second full copy.
    excludes=["imageio_ffmpeg"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OpenTalk",
    console=False,
)
model_helper = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="opentalk-model-setup",
    console=True,
)
collection = COLLECT(
    exe,
    model_helper,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="OpenTalk",
)

if platform.system() == "Darwin":
    app = BUNDLE(
        collection,
        name="OpenTalk.app",
        bundle_identifier="dev.k1ra.opentalk",
        info_plist={
            "CFBundleDisplayName": "OpenTalk",
            "LSMinimumSystemVersion": "13.3",
            "LSUIElement": True,
            "NSMicrophoneUsageDescription":
                "OpenTalk benötigt das Mikrofon für die lokale Spracheingabe.",
        },
    )
