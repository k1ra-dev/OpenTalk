#!/usr/bin/env python3
"""Offline dictation for Linux, Windows, and Apple Silicon macOS."""

from __future__ import annotations

import argparse
import atexit
from contextlib import suppress
import ctypes
import hmac
import json
import os
import platform
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer

MAX_SECONDS = 120
MAX_WAV_BYTES = 16_000 * 2 * MAX_SECONDS + 4096
MODEL_NAMES = ("tiny", "base", "small", "medium", "large-v3")
MODEL_MIN_BYTES = {
    "tiny": 60_000_000,
    "base": 100_000_000,
    "small": 400_000_000,
    "medium": 1_300_000_000,
    "large-v3": 2_500_000_000,
}


def runtime_socket() -> Path:
    if platform.system() in ("Darwin", "Windows"):
        identity = str(os.getuid()) if hasattr(os, "getuid") else os.environ.get("USERNAME", "user")
        base = Path(tempfile.gettempdir()) / f"opentalk-{identity}"
        base.mkdir(mode=0o700, exist_ok=True)
        base.chmod(0o700)
    else:
        base = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    if not base.is_dir() or (hasattr(os, "getuid") and base.stat().st_uid != os.getuid()):
        raise RuntimeError(
            "Kein privates XDG_RUNTIME_DIR gefunden. Bitte in einer Desktop-Sitzung starten."
        )
    return base / "opentalk.sock"


def config(name: str, default: str = "") -> str:
    return os.environ.get("OPENTALK_" + name, default)


def resource_dir() -> Path:
    """Directory containing resources, including inside a PyInstaller bundle."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def bundled_executable(name: str) -> Path | None:
    suffix = ".exe" if platform.system() == "Windows" else ""
    candidate = resource_dir() / "bin" / (name + suffix)
    return candidate if candidate.is_file() else None


def local_data_dir() -> Path:
    if platform.system() == "Windows" and "XDG_DATA_HOME" not in os.environ:
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "OpenTalk"
    if platform.system() == "Darwin" and "XDG_DATA_HOME" not in os.environ:
        return Path.home() / "Library/Application Support/OpenTalk"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "opentalk"


def settings_path() -> Path:
    if platform.system() == "Windows" and "XDG_CONFIG_HOME" not in os.environ:
        return local_data_dir() / "settings.json"
    if platform.system() == "Darwin" and "XDG_CONFIG_HOME" not in os.environ:
        return Path.home() / "Library/Application Support/OpenTalk/settings.json"
    return (
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "opentalk/settings.json"
    )


def recorder_command(destination: Path, source: str = "", raw: bool = False) -> list[str]:
    """Return a native 16 kHz mono recording command for the current OS."""
    if platform.system() == "Darwin":
        if platform.machine() != "arm64":
            raise RuntimeError(
                "OpenTalk für macOS unterstützt nur Macs mit M-Prozessor (Apple Silicon)."
            )
        command = [
            recorder_dependency(),
            "-nostdin",
            "-loglevel",
            "error",
            "-f",
            "avfoundation",
            "-i",
            f":{source or 'default'}",
            "-ar",
            "16000",
            "-ac",
            "1",
        ]
        if raw:
            # LiveDictation reads this file during recording. Without flushing,
            # FFmpeg can buffer several seconds before the reader sees any PCM.
            command.extend(["-f", "s16le", "-flush_packets", "1"])
        else:
            command.extend(["-c:a", "pcm_s16le"])
        return [*command, "-y", str(destination)]
    if platform.system() == "Windows":
        if not source:
            from audio_sources import list_sources

            sources = list_sources()
            if not sources:
                raise RuntimeError("Kein Mikrofon gefunden. Mikrofon anschließen und auswählen.")
            source = sources[0][1]
        source_name = source
        # Windows stops FFmpeg by writing "q" to stdin. Do not add -nostdin
        # here; it would make that graceful shutdown mechanism ineffective.
        command = [
            recorder_dependency(),
            "-loglevel",
            "error",
            "-f",
            "dshow",
            "-i",
            f"audio={source_name}",
            "-ar",
            "16000",
            "-ac",
            "1",
        ]
        command.extend(
            ["-f", "s16le", "-flush_packets", "1"] if raw else ["-c:a", "pcm_s16le"]
        )
        return [*command, "-y", str(destination)]
    return [
        "pw-record",
        *(["--raw"] if raw else []),
        "--rate",
        "16000",
        "--channels",
        "1",
        "--format",
        "s16",
        *(["--target", source] if source else []),
        str(destination),
    ]


def subprocess_options() -> dict:
    """Native helper processes must not steal focus by opening a Windows console."""
    return {"creationflags": 0x08000000} if platform.system() == "Windows" else {}


def recorder_dependency() -> str:
    if platform.system() in ("Darwin", "Windows"):
        custom = config("FFMPEG")
        bundled = bundled_executable("ffmpeg")
        if custom or bundled:
            return custom or str(bundled)
        if platform.system() == "Windows" and not shutil.which("ffmpeg"):
            try:
                import imageio_ffmpeg

                return imageio_ffmpeg.get_ffmpeg_exe()
            except (ImportError, RuntimeError):
                pass
        return "ffmpeg"
    return "pw-record"


def stop_recorder(recorder: subprocess.Popen) -> None:
    """Ask the platform recorder to finish its output cleanly."""
    if platform.system() == "Windows":
        if recorder.stdin is not None:
            try:
                recorder.stdin.write(b"q\n")
                recorder.stdin.flush()
                return
            except (OSError, ValueError):
                pass
        recorder.terminate()
        return
    recorder.send_signal(signal.SIGINT)


def saved_source() -> str:
    try:
        source = json.loads(settings_path().read_text(encoding="utf-8")).get("source", "")
        return source if isinstance(source, str) else ""
    except (OSError, ValueError, AttributeError):
        return ""


def selected_model() -> str:
    try:
        name = json.loads(settings_path().read_text(encoding="utf-8")).get("model", "small")
        return name if name in MODEL_NAMES else "small"
    except (OSError, ValueError, AttributeError):
        return "small"


def model_file(name: str) -> Path:
    if name not in MODEL_NAMES:
        raise ValueError("Unbekanntes Whisper-Modell.")
    return local_data_dir() / "whisper.cpp/models" / f"ggml-{name}.bin"


def model_available(name: str) -> bool:
    try:
        return model_file(name).stat().st_size >= MODEL_MIN_BYTES[name]
    except OSError:
        return False


def model_path() -> Path:
    custom = config("MODEL")
    return Path(custom).expanduser() if custom else model_file(selected_model())


def engine_executable(name: str) -> str:
    bundled = bundled_executable(name)
    if bundled:
        return str(bundled)
    suffix = ".exe" if platform.system() == "Windows" else ""
    binary_dir = local_data_dir() / "whisper.cpp/build/bin"
    # Visual Studio is a multi-configuration generator; Ninja is not.
    for directory in (binary_dir, binary_dir / "Release"):
        candidate = directory / (name + suffix)
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name) or ""


def whisper_cli() -> str:
    return config("WHISPER_CLI", engine_executable("whisper-cli") or "whisper-cli")


def whisper_server() -> str:
    """Return the optional persistent whisper-server executable."""
    return config("WHISPER_SERVER", engine_executable("whisper-server"))


def vad_model_path() -> Path:
    return Path(
        config("VAD_MODEL", str(local_data_dir() / "whisper.cpp/models/ggml-silero-v6.2.0.bin"))
    ).expanduser()


def clean_transcript(value: str) -> str:
    without_music = re.sub(r"\[(?:musik|music)\]", "", value, flags=re.IGNORECASE)
    return re.sub(r"[ \t]{2,}", " ", without_music).strip()


def response_transcript(response) -> str:
    """Reject malformed server responses before they reach desktop insertion."""
    try:
        result = json.load(response)
    except (ValueError, UnicodeError) as exc:
        raise RuntimeError("Erkennung lieferte eine ungültige JSON-Antwort.") from exc
    if not isinstance(result, dict) or not isinstance(result.get("text"), str):
        raise RuntimeError("Erkennung lieferte keinen gültigen Text.")
    return clean_transcript(result["text"])


def _multipart_wav(data: bytes, fields: dict[str, str]) -> tuple[bytes, str]:
    """Encode one in-memory WAV request without adding an HTTP dependency."""
    boundary = "OpenTalk-" + secrets.token_hex(16)
    chunks = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode(),
                b"\r\n",
            ]
        )
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n',
            b"Content-Type: audio/wav\r\n\r\n",
            data,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks), boundary


class PersistentWhisperServer:
    """Keep the model loaded between segments on every supported platform."""

    def __init__(self):
        self.lock = threading.Lock()
        self.process_lock = threading.Lock()
        self.last_used = time.monotonic()
        self.sessions = 0
        self.closed = threading.Event()
        self.process: subprocess.Popen | None = None
        self.url = ""
        self.signature: tuple[str, str, str] | None = None
        self.retry_after = 0.0
        # Audio sent to our loopback child must never follow system HTTP proxies.
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _start(self, executable: str, model: Path, language: str) -> None:
        if self.closed.is_set():
            raise RuntimeError("OpenTalk wird beendet.")
        self.stop()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        secret_path = "/" + secrets.token_urlsafe(24)
        command = [
            executable,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--request-path",
            secret_path,
            "-m",
            str(model),
            "-l",
            language,
            "-t",
            config("WHISPER_THREADS", "4"),
            "-bo",
            "5",
            "-bs",
            "5",
            "-fa",
            "-sns",
            "-nt",
        ]
        vad = vad_model_path()
        if vad.is_file():
            command.extend(["--vad", "-vm", str(vad)])
        # Shutdown can run while the background thread is warming the model.
        # Publish the child under a separate lock, never holding it during HTTP.
        with self.process_lock:
            if self.closed.is_set():
                raise RuntimeError("OpenTalk wird beendet.")
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **subprocess_options(),
            )
            self.process = process
        # A cold Metal shader cache can need >10 s even on an M-series Mac.
        # This runs off the UI thread; allow first-time compilation to finish
        # instead of killing it and starting the same work again in the CLI.
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if self.closed.is_set() or process.poll() is not None:
                raise RuntimeError("Lokaler Whisper-Schnellmodus konnte nicht starten.")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    self.url = f"http://127.0.0.1:{port}{secret_path}/inference"
                    self.signature = (executable, str(model), language)
                    return
            except OSError:
                time.sleep(0.02)
        self.stop()
        raise RuntimeError("Lokaler Whisper-Schnellmodus braucht zu lange zum Starten.")

    def warm(self) -> None:
        if self.closed.is_set():
            return
        executable = whisper_server()
        model = model_path()
        language = config("LANGUAGE", "de")
        if (
            not executable
            or not model.is_file()
            or not (shutil.which(executable) or Path(executable).is_file())
        ):
            return
        signature = (executable, str(model), language)
        with self.lock:
            if time.monotonic() < self.retry_after:
                return
            if (
                self.process is not None
                and self.process.poll() is None
                and self.signature == signature
            ):
                return
            try:
                self._start(executable, model, language)
            except (OSError, RuntimeError, ValueError):
                self._failed()
                raise
            self.last_used = time.monotonic()

    def transcribe(self, data: bytes) -> str:
        with self.lock:
            if time.monotonic() < self.retry_after:
                raise RuntimeError("Whisper-Schnellmodus pausiert nach einem Fehler.")
            try:
                return self._transcribe(data)
            except (OSError, RuntimeError, ValueError, KeyError):
                self._failed()
                raise

    def _failed(self) -> None:
        # Caller holds self.lock: an older failed request must never terminate
        # the replacement process of a newer request or background warmup.
        self.stop()
        self.retry_after = time.monotonic() + 30

    def _transcribe(self, data: bytes) -> str:
        if self.closed.is_set():
            raise RuntimeError("OpenTalk wird beendet.")
        executable = whisper_server()
        model = model_path()
        language = config("LANGUAGE", "de")
        signature = (executable, str(model), language)
        if (
            self.process is None
            or self.process.poll() is not None
            or self.signature != signature
        ):
            if not executable:
                raise RuntimeError("whisper-server fehlt.")
            self._start(executable, model, language)
        body, boundary = _multipart_wav(
            data,
            {
                "response_format": "json",
                "language": language,
                "no_timestamps": "true",
                "suppress_non_speech": "true",
            },
        )
        request = urllib.request.Request(
            self.url,
            data=body,
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        with self.http.open(request, timeout=MAX_SECONDS + 30) as response:
            try:
                return response_transcript(response)
            finally:
                self.last_used = time.monotonic()

    def begin_session(self) -> None:
        with self.process_lock:
            self.sessions += 1
            self.last_used = time.monotonic()

    def end_session(self) -> None:
        with self.process_lock:
            self.sessions = max(0, self.sessions - 1)
            self.last_used = time.monotonic()

    def release_if_idle(self, seconds: float = 300) -> bool:
        """Never unload during capture, queued recognition, or model startup."""
        if not self.lock.acquire(blocking=False):
            return False
        try:
            with self.process_lock:
                if self.sessions or time.monotonic() - self.last_used < seconds:
                    return False
                process, self.process = self.process, None
                self.url = ""
                self.signature = None
            self._stop_process(process)
            return process is not None
        finally:
            self.lock.release()

    def stop(self) -> None:
        with self.process_lock:
            process, self.process = self.process, None
            self.url = ""
            self.signature = None
        self._stop_process(process)

    @staticmethod
    def _stop_process(process) -> None:
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        except ProcessLookupError:
            pass

    def shutdown(self) -> None:
        """Prevent an in-flight warmup from spawning a child after app exit."""
        with self.process_lock:
            self.closed.set()
        self.stop()


LOCAL_WHISPER_SERVER = PersistentWhisperServer()
atexit.register(LOCAL_WHISPER_SERVER.shutdown)


def warm_transcriber_async() -> None:
    """Preload the model without delaying the GUI startup."""
    if not config("SERVER_URL") and whisper_server():

        def preload() -> None:
            # warm() cleans up under its serialization lock; never stop a
            # potentially newer process after that lock has been released.
            with suppress(OSError, RuntimeError, ValueError):
                LOCAL_WHISPER_SERVER.warm()

        threading.Thread(target=preload, daemon=True).start()


def inform(message: str) -> None:
    print(message, flush=True)
    if platform.system() == "Darwin" and shutil.which("osascript"):
        escaped = message.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.run(
            ["osascript", "-e", f'display notification "{escaped}" with title "OpenTalk"'],
            capture_output=True,
            timeout=4,
            check=False,
        )
    elif shutil.which("notify-send") and os.environ.get(
        "DISPLAY", os.environ.get("WAYLAND_DISPLAY")
    ):
        subprocess.run(
            ["notify-send", "OpenTalk", message], capture_output=True, timeout=4, check=False
        )


def validate_wav(data: bytes) -> None:
    if len(data) > MAX_WAV_BYTES:
        raise ValueError("Aufnahme zu lang (maximal 120 Sekunden).")
    import io

    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000):
                raise ValueError("Erwartet: WAV mit 16 kHz, Mono, 16 Bit PCM.")
            if audio.getnframes() > MAX_SECONDS * 16000:
                raise ValueError("Aufnahme zu lang (maximal 120 Sekunden).")
            if audio.getnframes() < 1600:
                raise ValueError("Aufnahme zu kurz.")
            if len(audio.readframes(audio.getnframes())) != audio.getnframes() * 2:
                raise ValueError("WAV-Datei ist unvollständig.")
    except (wave.Error, EOFError) as exc:
        raise ValueError("Ungültige WAV-Datei.") from exc


def transcribe_local(data: bytes) -> str:
    if LOCAL_WHISPER_SERVER.closed.is_set():
        raise RuntimeError("OpenTalk wird beendet.")
    model = model_path()
    if not model.is_file():
        raise RuntimeError("Modell fehlt: OPENTALK_MODEL auf ggml-*.bin setzen.")
    cli = whisper_cli()
    if not shutil.which(cli) and not Path(cli).is_file():
        raise RuntimeError("whisper-cli fehlt: OPENTALK_WHISPER_CLI setzen.")
    if whisper_server():
        try:
            return LOCAL_WHISPER_SERVER.transcribe(data)
        except (OSError, RuntimeError, ValueError, KeyError, urllib.error.URLError):
            # Reliability wins over speed: a failed warm server is discarded and
            # this segment is retried once through the established CLI path.
            if LOCAL_WHISPER_SERVER.closed.is_set():
                raise RuntimeError("OpenTalk wird beendet.") from None
    with tempfile.TemporaryDirectory(prefix="opentalk-") as directory:
        wav = Path(directory) / "audio.wav"
        output = Path(directory) / "result"
        wav.write_bytes(data)
        command = [
            cli,
            "-m",
            str(model),
            "-f",
            str(wav),
            "-l",
            config("LANGUAGE", "de"),
            "-otxt",
            "-of",
            str(output),
            "-nt",
            "-np",
            "-sns",
            "-t",
            config("WHISPER_THREADS", "4"),
        ]
        vad_model = vad_model_path()
        if vad_model.is_file():
            command.extend(["--vad", "-vm", str(vad_model)])
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=MAX_SECONDS + 90,
                **subprocess_options(),
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Erkennung hat zu lange gedauert.") from exc
        if result.returncode != 0:
            raise RuntimeError("whisper-cli fehlgeschlagen: " + result.stderr[-600:])
        result_file = output.with_suffix(".txt")
        return clean_transcript(
            result_file.read_text(encoding="utf-8") if result_file.exists() else ""
        )


def transcribe(data: bytes) -> str:
    validate_wav(data)
    server = config("SERVER_URL").rstrip("/")
    if not server:
        return transcribe_local(data)
    if not (server.startswith("https://") or server.startswith("http://")):
        raise RuntimeError("OPENTALK_SERVER_URL braucht http:// oder https://.")
    token = config("TOKEN")
    if not token:
        raise RuntimeError("Für den Homeserver OPENTALK_TOKEN setzen.")
    request = urllib.request.Request(
        server + "/transcribe",
        data=data,
        method="POST",
        headers={"Authorization": "Bearer " + token, "Content-Type": "audio/wav"},
    )
    try:
        with urllib.request.urlopen(request, timeout=MAX_SECONDS + 95) as response:
            return response_transcript(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Server meldet HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("Erkennungsserver nicht erreichbar. Verbindung und Adresse prüfen.") from exc


def insert_text(value: str) -> None:
    if not value:
        inform("Keine Sprache erkannt.")
        return
    method = config("INSERT", "auto")
    if platform.system() == "Windows" and method in ("auto", "clipboard"):
        windows_copy_text(value)
        if method == "auto":
            windows_paste()
            inform("Text eingefügt.")
        else:
            inform("Text in Zwischenablage – mit Strg+V einfügen.")
        return
    if platform.system() == "Darwin" and method in ("auto", "clipboard"):
        if not shutil.which("pbcopy"):
            raise RuntimeError("pbcopy fehlt; die macOS-Zwischenablage ist nicht verfügbar.")
        subprocess.run(["pbcopy"], input=value.encode("utf-8"), check=True, timeout=10)
        if method == "auto" and shutil.which("osascript"):
            result = subprocess.run(
                [
                    "osascript",
                    "-e",
                    'tell application "System Events" to keystroke "v" using command down',
                ],
                capture_output=True,
                timeout=10,
                check=False,
            )
            if result.returncode == 0:
                inform("Text eingefügt.")
                return
        inform("Text in Zwischenablage – mit Cmd+V einfügen.")
        return
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if method == "auto":
        candidates = ("wtype", "kwtype") if "hyprland" in desktop else ("kwtype", "wtype")
    elif method in ("kwtype", "wtype"):
        candidates = (method,)
    else:
        candidates = ()
    for candidate in candidates:
        if not shutil.which(candidate):
            continue
        try:
            if candidate == "wtype":
                subprocess.run(
                    ["wtype", "-"],
                    input=value.encode("utf-8"),
                    check=True,
                    capture_output=True,
                    timeout=15,
                )
            else:
                subprocess.run(["kwtype", value], check=True, capture_output=True, timeout=15)
            inform("Text eingefügt.")
            return
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if method != "auto":
                raise RuntimeError(f"{candidate} konnte nicht schreiben.") from None
    if method in ("auto", "clipboard") and shutil.which("wl-copy"):
        subprocess.run(
            ["wl-copy", "--type", "text/plain;charset=utf-8"],
            input=value.encode(),
            check=True,
            timeout=10,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        inform("Text in Zwischenablage – mit Strg+V einfügen.")
        return
    if method == "stdout":
        print(value, flush=True)
        return
    raise RuntimeError("Zum Einfügen wtype, kwtype oder wl-copy installieren.")


def windows_copy_text(value: str) -> None:
    """Place Unicode text on the native Windows clipboard."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.CreateWindowExW.argtypes = [
        ctypes.c_ulong, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_ulong,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
    ]
    user32.CreateWindowExW.restype = ctypes.c_void_p
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.DestroyWindow.argtypes = [ctypes.c_void_p]
    encoded = (value + "\0").encode("utf-16-le")
    handle = kernel32.GlobalAlloc(0x0002, len(encoded))
    if not handle:
        raise RuntimeError("Windows-Zwischenablage konnte nicht reserviert werden.")
    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        kernel32.GlobalFree(handle)
        raise RuntimeError("Windows-Zwischenablage konnte nicht gesperrt werden.")
    ctypes.memmove(pointer, encoded, len(encoded))
    kernel32.GlobalUnlock(handle)
    # OpenClipboard(NULL) + EmptyClipboard leaves no owner and can make
    # SetClipboardData fail. Use a hidden, message-only window owned by this
    # worker thread; never borrow a foreground window from another process.
    owner = user32.CreateWindowExW(0, "STATIC", "OpenTalkClipboard", 0, 0, 0, 0, 0,
                                  ctypes.c_void_p(-3), None, None, None)
    if not owner:
        kernel32.GlobalFree(handle)
        raise RuntimeError("Windows-Zwischenablage konnte nicht initialisiert werden.")
    opened = False
    try:
        for _ in range(5):
            opened = bool(user32.OpenClipboard(owner))
            if opened:
                break
            time.sleep(0.02)
        if not opened:
            raise RuntimeError("Windows-Zwischenablage ist gerade belegt.")
        if not user32.EmptyClipboard():
            raise RuntimeError("Windows-Zwischenablage konnte nicht geöffnet werden.")
        if not user32.SetClipboardData(13, handle):  # CF_UNICODETEXT
            raise RuntimeError("Text konnte nicht in die Zwischenablage geschrieben werden.")
        handle = None  # Ownership was transferred to the system.
    finally:
        if opened:
            user32.CloseClipboard()
        if handle is not None:
            kernel32.GlobalFree(handle)
        user32.DestroyWindow(owner)


def windows_paste() -> None:
    user32 = ctypes.windll.user32
    user32.keybd_event(0x11, 0, 0, 0)  # Ctrl down
    user32.keybd_event(0x56, 0, 0, 0)  # V down
    user32.keybd_event(0x56, 0, 0x0002, 0)  # V up
    user32.keybd_event(0x11, 0, 0x0002, 0)  # Ctrl up


class Dictation:
    def __init__(self, on_result=None, on_error=None, source: str | None = None):
        self.recorder: subprocess.Popen | None = None
        self.temp: tempfile.TemporaryDirectory | None = None
        self.audio_path: Path | None = None
        self.busy = False
        self.lock = threading.Lock()
        self.session = 0
        self.closed = False
        self.source = source if source is not None else config("SOURCE", saved_source())
        self.on_result = on_result or (lambda value: insert_text(value))
        self.on_error = on_error or (lambda message: inform("Fehler: " + message))

    def toggle(self) -> str:
        with self.lock:
            if self.closed:
                return "Aufnahme verworfen."
            if self.busy:
                return "Erkennung läuft bereits."
            if self.recorder:
                self.busy = True
                self.session += 1
                recorder, audio_path, temp = self.recorder, self.audio_path, self.temp
                self.recorder = self.audio_path = self.temp = None
                threading.Thread(
                    target=self.finish, args=(recorder, audio_path, temp), daemon=True
                ).start()
                return "Aufnahme beendet. Erkenne Text …"
            self.temp = tempfile.TemporaryDirectory(prefix="opentalk-")
            self.audio_path = Path(self.temp.name) / "audio.wav"
            command = recorder_command(self.audio_path, self.source)
            try:
                self.recorder = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE if platform.system() == "Windows" else None,
                    **subprocess_options(),
                )
            except OSError:
                self.temp.cleanup()
                self.temp = self.audio_path = None
                raise RuntimeError(
                    f"{recorder_dependency()} fehlt. Aufnahme-Abhängigkeit installieren."
                ) from None
            time.sleep(0.12)
            if self.recorder.poll() is not None:
                error = self.recorder.stderr.read().decode(errors="replace")[-350:]
                self.temp.cleanup()
                self.temp = self.audio_path = self.recorder = None
                raise RuntimeError("Mikrofon konnte nicht starten: " + error)
            self.session += 1
            timer = threading.Timer(MAX_SECONDS, self.auto_stop, args=(self.session,))
            timer.daemon = True
            timer.start()
            return "Aufnahme läuft … Hotkey erneut drücken zum Beenden."

    def auto_stop(self, session):
        with self.lock:
            active = self.recorder is not None and self.session == session
        if active:
            try:
                inform(self.toggle())
            except Exception as exc:
                inform(str(exc))

    def finish(self, recorder, audio_path, temp):
        try:
            stop_recorder(recorder)
            try:
                recorder.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                recorder.kill()
                recorder.communicate()
            data = audio_path.read_bytes()
            self.on_result(transcribe(data))
        except Exception as exc:
            self.on_error(str(exc))
        finally:
            temp.cleanup()
            with self.lock:
                self.busy = False

    def cancel(self) -> None:
        """Discard an active recording when a foreground UI closes."""
        with self.lock:
            recorder, temp = self.recorder, self.temp
            self.recorder = self.audio_path = self.temp = None
            self.session += 1
            self.closed = True
        if recorder is not None:
            stop_recorder(recorder)
            try:
                recorder.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                recorder.kill()
                recorder.communicate()
        if temp is not None:
            temp.cleanup()


def send_command(command: str) -> str:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2)
        client.connect(str(runtime_socket()))
        client.sendall((command + "\n").encode())
        return client.recv(4096).decode().strip()


def run_daemon():
    import fcntl

    path = runtime_socket()
    with (path.parent / "opentalk.lock").open("w") as lockfile:
        try:
            fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("OpenTalk läuft schon.") from exc
        path.unlink(missing_ok=True)
        engine = Dictation()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(path))
            path.chmod(0o600)
            server.listen(4)
            try:
                while True:
                    with server.accept()[0] as client:
                        command = client.recv(128).decode().strip()
                        try:
                            answer = (
                                engine.toggle()
                                if command == "toggle"
                                else ("Aufnahme läuft" if engine.recorder else "Bereit")
                                if command == "status"
                                else "Unbekannter Befehl"
                            )
                        except Exception as exc:
                            answer = "Fehler: " + str(exc)
                        client.sendall(answer.encode())
                        if command == "toggle":
                            inform(answer)
            finally:
                path.unlink(missing_ok=True)


def toggle():
    try:
        print(send_command("toggle"))
        return
    except (ConnectionError, FileNotFoundError, TimeoutError):
        pass
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "daemon"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(30):
        time.sleep(0.1)
        try:
            print(send_command("toggle"))
            return
        except (ConnectionError, FileNotFoundError, TimeoutError):
            continue
    raise RuntimeError(
        "Hintergrunddienst startet nicht. `python opentalk.py daemon` im Terminal prüfen."
    )


def make_handler(token: str):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/transcribe":
                self.send_error(404)
                return
            supplied = self.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied, "Bearer " + token):
                self.send_error(401)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                size = 0
            if not 0 < size <= MAX_WAV_BYTES:
                self.send_error(413)
                return
            try:
                value = transcribe_local_checked(self.rfile.read(size))
                result = json.dumps({"text": value}, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(result)))
                self.end_headers()
                self.wfile.write(result)
            except ValueError as exc:
                self.send_error(400, str(exc))
            except Exception as exc:
                print("Transkription fehlgeschlagen:", exc, file=sys.stderr)
                self.send_error(500, "Transkription fehlgeschlagen")

    return Handler


def transcribe_local_checked(data: bytes) -> str:
    validate_wav(data)
    return transcribe_local(data)


def main():
    parser = argparse.ArgumentParser(
        description="Lokale Spracheingabe für Linux, macOS und Windows"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("toggle", "daemon", "status"):
        commands.add_parser(name)
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        if args.command == "toggle":
            toggle()
        elif args.command == "daemon":
            run_daemon()
        elif args.command == "status":
            print(send_command("status"))
        elif args.command == "serve":
            token = config("TOKEN")
            if len(token) < 24:
                raise RuntimeError("OPENTALK_TOKEN muss mindestens 24 Zeichen lang sein.")
            if not model_path().is_file():
                raise RuntimeError("OPENTALK_MODEL auf eine vorhandene Modelldatei setzen.")
            with HTTPServer((args.host, args.port), make_handler(token)) as server:
                print(f"OpenTalk hört auf {args.host}:{args.port}", flush=True)
                server.serve_forever()
    except (RuntimeError, OSError) as exc:
        print("Fehler:", exc, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
