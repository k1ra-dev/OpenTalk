#!/usr/bin/env python3
"""Offline dictation for Linux desktops; optional private Whisper server."""
from __future__ import annotations

import argparse
import hmac
import json
import os
from pathlib import Path
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


def runtime_socket() -> Path:
    base = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    if not base.is_dir() or base.stat().st_uid != os.getuid():
        raise RuntimeError("Kein privates XDG_RUNTIME_DIR gefunden. Bitte in einer Desktop-Sitzung starten.")
    return base / "opentalk.sock"


def config(name: str, default: str = "") -> str:
    return os.environ.get("OPENTALK_" + name, default)


def inform(message: str) -> None:
    print(message, flush=True)
    if shutil.which("notify-send") and os.environ.get("DISPLAY", os.environ.get("WAYLAND_DISPLAY")):
        subprocess.run(["notify-send", "OpenTalk", message], capture_output=True, timeout=4, check=False)


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
    except (wave.Error, EOFError) as exc:
        raise ValueError("Ungültige WAV-Datei.") from exc


def transcribe_local(data: bytes) -> str:
    model = Path(config("MODEL")).expanduser()
    if not model.is_file():
        raise RuntimeError("Modell fehlt: OPENTALK_MODEL auf ggml-*.bin setzen.")
    cli = config("WHISPER_CLI", "whisper-cli")
    if not shutil.which(cli) and not Path(cli).is_file():
        raise RuntimeError("whisper-cli fehlt: OPENTALK_WHISPER_CLI setzen.")
    with tempfile.TemporaryDirectory(prefix="opentalk-") as directory:
        wav = Path(directory) / "audio.wav"
        output = Path(directory) / "result"
        wav.write_bytes(data)
        command = [cli, "-m", str(model), "-f", str(wav), "-l", config("LANGUAGE", "de"),
                   "-otxt", "-of", str(output), "-nt", "-np"]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=MAX_SECONDS + 90)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Erkennung hat zu lange gedauert.") from exc
        if result.returncode != 0:
            raise RuntimeError("whisper-cli fehlgeschlagen: " + result.stderr[-600:])
        return (output.with_suffix(".txt").read_text(encoding="utf-8")).strip()


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
    request = urllib.request.Request(server + "/transcribe", data=data, method="POST",
                                     headers={"Authorization": "Bearer " + token,
                                              "Content-Type": "audio/wav"})
    try:
        with urllib.request.urlopen(request, timeout=MAX_SECONDS + 95) as response:
            return json.load(response)["text"]
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Server meldet HTTP {exc.code}.") from exc


def insert_text(value: str) -> None:
    if not value:
        inform("Keine Sprache erkannt.")
        return
    method = config("INSERT", "auto")
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
                subprocess.run(["wtype", "-"], input=value.encode("utf-8"), check=True,
                               capture_output=True, timeout=15)
            else:
                subprocess.run(["kwtype", value], check=True, capture_output=True, timeout=15)
            inform("Text eingefügt.")
            return
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if method != "auto":
                raise RuntimeError(f"{candidate} konnte nicht schreiben.") from None
    if method in ("auto", "clipboard") and shutil.which("wl-copy"):
        subprocess.run(["wl-copy", "--type", "text/plain;charset=utf-8"], input=value.encode(),
                       check=True, timeout=10, capture_output=True)
        inform("Text in Zwischenablage – mit Strg+V einfügen.")
        return
    if method == "stdout":
        print(value, flush=True)
        return
    raise RuntimeError("Zum Einfügen wtype, kwtype oder wl-copy installieren.")


class Dictation:
    def __init__(self):
        self.recorder: subprocess.Popen | None = None
        self.temp: tempfile.TemporaryDirectory | None = None
        self.audio_path: Path | None = None
        self.busy = False
        self.lock = threading.Lock()
        self.session = 0

    def toggle(self) -> str:
        with self.lock:
            if self.busy:
                return "Erkennung läuft bereits."
            if self.recorder:
                self.busy = True
                self.session += 1
                recorder, audio_path, temp = self.recorder, self.audio_path, self.temp
                self.recorder = self.audio_path = self.temp = None
                threading.Thread(target=self.finish, args=(recorder, audio_path, temp), daemon=True).start()
                return "Aufnahme beendet. Erkenne Text …"
            self.temp = tempfile.TemporaryDirectory(prefix="opentalk-")
            self.audio_path = Path(self.temp.name) / "audio.wav"
            command = ["pw-record", "--rate", "16000", "--channels", "1", "--format", "s16",
                       str(self.audio_path)]
            try:
                self.recorder = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            except OSError:
                self.temp.cleanup()
                self.temp = self.audio_path = None
                raise RuntimeError("pw-record fehlt. PipeWire installieren.") from None
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
            recorder.send_signal(signal.SIGINT)
            try:
                recorder.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                recorder.kill()
                recorder.communicate()
            data = audio_path.read_bytes()
            insert_text(transcribe(data))
        except Exception as exc:
            inform("Fehler: " + str(exc))
        finally:
            temp.cleanup()
            with self.lock:
                self.busy = False


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
                            answer = engine.toggle() if command == "toggle" else (
                                "Aufnahme läuft" if engine.recorder else "Bereit") if command == "status" else "Unbekannter Befehl"
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
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "daemon"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    for _ in range(30):
        time.sleep(.1)
        try:
            print(send_command("toggle"))
            return
        except (ConnectionError, FileNotFoundError, TimeoutError):
            continue
    raise RuntimeError("Hintergrunddienst startet nicht. `python opentalk.py daemon` im Terminal prüfen.")


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
    parser = argparse.ArgumentParser(description="Lokale Spracheingabe für Linux mit optionalem Homeserver")
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
            if not Path(config("MODEL")).expanduser().is_file():
                raise RuntimeError("OPENTALK_MODEL auf eine vorhandene Modelldatei setzen.")
            with HTTPServer((args.host, args.port), make_handler(token)) as server:
                print(f"OpenTalk hört auf {args.host}:{args.port}", flush=True)
                server.serve_forever()
    except (RuntimeError, OSError) as exc:
        print("Fehler:", exc, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
