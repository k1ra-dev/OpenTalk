"""Discover selectable PipeWire recording sources through PulseAudio compatibility."""
from __future__ import annotations

import json
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
    try:
        response = subprocess.run(["pactl", "-f", "json", "list", "sources"],
                                  capture_output=True, text=True, check=True, timeout=5)
        return parse_sources(response.stdout)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as exc:
        raise RuntimeError("Mikrofone konnten nicht gelesen werden (pactl / PipeWire prüfen).") from exc
