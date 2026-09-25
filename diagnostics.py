"""On-demand, read-only configuration checks. Never record or paste text."""

import platform
import shutil
import ctypes
from contextlib import suppress
from dataclasses import dataclass
import os
import subprocess
from pathlib import Path

import audio_sources
import opentalk


@dataclass(frozen=True)
class Hardware:
    system: str
    architecture: str
    cpu: str
    threads: int | None
    ram_gib: float | None
    available_gib: float | None = None


class _MemoryStatus(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32),
                *[(name, ctypes.c_uint64) for name in
                  ("total", "available", "page_total", "page_available", "virtual_total",
                   "virtual_available", "extended_available")]]


def _sysctl(key: str) -> str:
    return subprocess.run(["/usr/sbin/sysctl", "-n", key], capture_output=True,
                          text=True, check=True, timeout=2).stdout.strip()


def scan_hardware() -> Hardware:
    """Bounded local queries only; no benchmark, GPU driver probe or download."""
    system, architecture = platform.system(), platform.machine()
    cpu = architecture
    total = available = None
    try:
        if system == "Darwin":
            total = int(_sysctl("hw.memsize"))
        elif system == "Windows":
            status = _MemoryStatus()
            status.length = ctypes.sizeof(status)
            query = ctypes.windll.kernel32.GlobalMemoryStatusEx
            query.argtypes = [ctypes.POINTER(_MemoryStatus)]
            query.restype = ctypes.c_int
            if query(ctypes.byref(status)):
                total, available = status.total, status.available
        elif system == "Linux":
            values = {}
            for line in Path("/proc/meminfo").read_text().splitlines():
                parts = line.split()
                if parts and parts[0] in ("MemTotal:", "MemAvailable:"):
                    values[parts[0]] = int(parts[1]) * 1024
            total, available = values.get("MemTotal:"), values.get("MemAvailable:")
    except (OSError, ValueError, IndexError, AttributeError, subprocess.SubprocessError):
        pass
    if system == "Darwin":
        with suppress(OSError, subprocess.SubprocessError):
            cpu = _sysctl("machdep.cpu.brand_string") or architecture
    # Available RAM is a momentary estimate, not memory reserved for OpenTalk.
    return Hardware(system, architecture, cpu, os.cpu_count(),
                    total / 2**30 if total and total > 0 else None,
                    available / 2**30 if available is not None and available >= 0 else None)


def recommend_model(hardware: Hardware) -> list[str]:
    """Conservative live-dictation heuristics, NOT measured model performance.

    RAM thresholds reserve headroom for other apps, not just model weights.
    A detected GPU does not prove the installed Whisper build can use it.
    """
    ram, threads = hardware.ram_gib, hardware.threads
    details = (f"Hardware · {hardware.cpu} · {threads or '?'} logische CPU-Kerne · "
               + (f"{ram:.1f} GiB RAM" if ram is not None else "RAM unbekannt"))
    if hardware.system == "Darwin" and hardware.architecture != "arm64":
        return [details, "MODELL · Keine Empfehlung: Intel-Macs werden nicht unterstützt."]
    if ram is None or threads is None:
        return [details, "MODELL · Hardware nicht vollständig lesbar; keine verlässliche Empfehlung."]
    apple = hardware.system == "Darwin" and hardware.architecture == "arm64"
    if apple and ram >= 24 and threads >= 8:
        model, reason = "medium", "Apple Silicon und viel RAM: Qualität bei moderater Latenz anstreben."
    elif (apple and ram >= 8 and threads >= 4) or (ram >= 16 and threads >= 8):
        model, reason = "small", "Ausgewogener Ausgangspunkt für Tempo und Genauigkeit."
    elif ram >= 8 and threads >= 4:
        model, reason = "base", "Konservative Wahl für reaktionsschnelle CPU-Erkennung."
    else:
        model, reason = "tiny", "Begrenzte Ressourcen: Geschwindigkeit vor Genauigkeit."
    if hardware.available_gib is not None:
        details += f" · derzeit {hardware.available_gib:.1f} GiB verfügbar"
        if hardware.available_gib < 2:
            model, reason = "tiny", "Wenig freier RAM; andere Programme schließen und erneut prüfen."
        elif hardware.available_gib < 4 and model in ("small", "medium"):
            model, reason = "base", "Aktuell wenig freier RAM; kleinere Wahl für mehr Reserven."
    result = [details, f"MODELL · Empfehlung: {model} (Einschätzung für Live-Diktat).", reason]
    if model == "medium":
        result.append("Schneller: small. Mehr Qualitätsreserve: large-v3 testen "
                      "(bei mindestens 32 GiB RAM; deutlich höhere Latenz möglich)."
                      if ram >= 32 else "Für geringere Verzögerung: small verwenden.")
    result.append("Apple Silicon ist Metal-fähig; Beschleunigung im installierten Build nicht geprüft."
                  if apple else "CPU-basierte Einschätzung; GPU-Beschleunigung nicht geprüft/eingerechnet.")
    result.append("Kein Geschwindigkeitstest: mit eigenen Aufnahmen vergleichen. "
                  "RAM-Auslastung, Sprache und Hintergrundprogramme beeinflussen das Ergebnis.")
    return result


def check_system() -> list[str]:
    results = [] if opentalk.config("SERVER_URL") else recommend_model(scan_hardware())
    system = platform.system()
    if system == "Darwin" and platform.machine() != "arm64":
        results.append("FEHLER · macOS benötigt einen M-Prozessor.")
    recorder = opentalk.recorder_dependency()
    if not (shutil.which(recorder) or Path(recorder).is_file()):
        results.append("FEHLER · Aufnahmeprogramm fehlt: " + Path(recorder).name)
    else:
        results.append("OK · Aufnahmeprogramm vorhanden.")
        try:
            sources = audio_sources.list_sources()
            results.append(
                f"OK · {len(sources)} Mikrofonquelle(n) gefunden."
                if sources else "HINWEIS · Keine Mikrofonquelle gefunden."
            )
            selected = opentalk.config("SOURCE", opentalk.saved_source())
            if selected and selected not in {source for _, source in sources}:
                results.append("HINWEIS · Gespeichertes Mikrofon nicht in der Geräteliste.")
        except (OSError, RuntimeError, ValueError):
            results.append("FEHLER · Mikrofone nicht lesbar; Gerät und Berechtigungen prüfen.")
    if opentalk.config("SERVER_URL"):
        results.append("HINWEIS · Homeserver eingestellt; Verbindung wurde nicht getestet.")
        if len(opentalk.config("TOKEN")) < 24:
            results.append("FEHLER · Homeserver-Token fehlt oder ist kürzer als 24 Zeichen.")
    else:
        model = opentalk.model_path()
        minimum = 1 if opentalk.config("MODEL") else opentalk.MODEL_MIN_BYTES[opentalk.selected_model()]
        try:
            ready = model.stat().st_size >= minimum
        except OSError:
            ready = False
        results.append("OK · Modelldatei vorhanden (keine Integritätsprüfung)." if ready
                       else "FEHLER · Modell fehlt oder ist unvollständig.")
        for label, executable in (("Erkennung", opentalk.whisper_cli()),
                                  ("Schnellmodus", opentalk.whisper_server())):
            ready = bool(executable and (shutil.which(executable) or Path(executable).is_file()))
            results.append(f"{'OK' if ready else 'HINWEIS'} · {label}: "
                           + ("Programm vorhanden." if ready else "Programm fehlt."))
    results.append("Nicht geprüft: tatsächliche Aufnahme, Textqualität und Einfügen ins Zielfenster.")
    return results
