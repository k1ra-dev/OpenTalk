"""Discover selectable recording sources on Linux, macOS, and Windows."""
from __future__ import annotations

import json
import platform
import re
import subprocess


def parse_sources(data: str) -> list[tuple[str, str]]:
    result = []
    for item in json.loads(data):
        name = item.get("name", "")
        if not name or name.endswith(".monitor") or item.get("monitor_source"):
            continue
        ports = item.get("ports") or []
        active = item.get("active_port")
        active_port = next((port for port in ports if port.get("name") == active), None)
        if active_port and active_port.get("availability") == "not available":
            continue
        result.append((item.get("description") or name, name))
    return sorted(result, key=lambda source: source[0].casefold())


def list_sources() -> list[tuple[str, str]]:
    from opentalk import recorder_dependency

    if platform.system() == "Darwin":
        if platform.machine() != "arm64":
            raise RuntimeError("macOS wird nur auf Macs mit M-Prozessor unterstützt.")
        try:
            response = subprocess.run(
                [recorder_dependency(), "-hide_banner", "-list_devices", "true",
                 "-f", "avfoundation", "-i", ""],
                capture_output=True, text=True, timeout=5)
            devices = []
            in_audio = False
            for line in response.stderr.splitlines():
                if "AVFoundation audio devices:" in line:
                    in_audio = True
                    continue
                if in_audio:
                    match = re.search(r"\[(\d+)\]\s+(.+)$", line)
                    if match:
                        devices.append((match.group(2).strip(), match.group(1)))
            if devices:
                return devices
            raise ValueError("keine Audiogeräte in ffmpeg-Ausgabe")
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            raise RuntimeError("Mikrofone konnten nicht gelesen werden (ffmpeg prüfen).") from exc
    if platform.system() == "Windows":
        try:
            response = subprocess.run(
                [recorder_dependency(), "-hide_banner", "-list_devices", "true",
                 "-f", "dshow", "-i", "dummy"],
                capture_output=True, text=True, timeout=5)
            devices = []
            for line in response.stderr.splitlines():
                match = re.search(r'"(.+)"\s+\(audio\)\s*$', line)
                if match:
                    devices.append((match.group(1), match.group(1)))
            if devices:
                return devices
            raise ValueError("keine Audiogeräte in ffmpeg-Ausgabe")
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            raise RuntimeError("Mikrofone konnten nicht gelesen werden (FFmpeg/DirectShow prüfen).") from exc
    try:
        response = subprocess.run(["pactl", "-f", "json", "list", "sources"],
                                  capture_output=True, text=True, check=True, timeout=5)
        return parse_sources(response.stdout)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as exc:
        raise RuntimeError("Mikrofone konnten nicht gelesen werden (pactl / PipeWire prüfen).") from exc
