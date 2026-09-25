#!/usr/bin/env python3
"""Small, non-activating dictation overlay for Linux, Windows, and Apple Silicon macOS."""

from __future__ import annotations

import json
import os
import platform
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import ctypes
import threading

from PyQt6 import sip
from PyQt6.QtCore import QLockFile, QMicrophonePermission, QPoint, QProcess, QRect, Qt, QTimer, QUrl, pyqtSignal, qVersion
from PyQt6.QtGui import QColor, QCursor, QDesktopServices, QKeySequence, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QPlainTextEdit,
    QSlider,
    QToolTip,
    QKeySequenceEdit,
    QVBoxLayout,
    QWidget,
)

import audio_sources
from live_dictation import LiveDictation
from hotkeys import HotkeyState
import opentalk

WINDOW_TITLE = "OpenTalk Overlay"
ADDRESS = re.compile(r"^0x[0-9a-fA-F]+$")
CIRCLE = 68
SATELLITE = 56
MENU_WIDTH = 260
MENU_HEIGHT = 204


def default_hotkey() -> str:
    return "Meta+Shift+Space" if platform.system() == "Darwin" else "Ctrl+Alt+R"


def selected_hotkey() -> str:
    value = read_settings().get("hotkey", default_hotkey())
    return value if isinstance(value, str) and value else default_hotkey()


def translate_qt_hotkey(value: str) -> str:
    """Convert between physical key names and Qt's macOS Ctrl/Meta convention.

    Qt maps Ctrl to the Mac Command key, whereas pynput maps cmd to Command.
    Swap only at the editor boundary; applying this conversion twice is identity.
    """
    if platform.system() != "Darwin":
        return value
    return re.sub(
        r"\b(Ctrl|Meta)\b", lambda match: {"Ctrl": "Meta", "Meta": "Ctrl"}[match[0]], value
    )


def pynput_hotkey(value: str) -> str:
    names = {
        "ctrl": "ctrl",
        "control": "ctrl",
        "alt": "alt",
        "shift": "shift",
        "meta": "cmd",
        "cmd": "cmd",
        "win": "cmd",
        "space": "space",
        "return": "enter",
        "enter": "enter",
        "tab": "tab",
        "escape": "esc",
    }
    parts = [part.strip().lower() for part in value.split("+") if part.strip()]
    converted = []
    for part in parts:
        key = names.get(part, part)
        converted.append(key if len(key) == 1 else f"<{key}>")
    modifiers = {"<ctrl>", "<alt>", "<shift>", "<cmd>"}
    if (
        len(converted) < 2
        or not any(key in modifiers for key in converted)
        or sum(key not in modifiers for key in converted) != 1
        or len(set(converted)) != len(converted)
        or "," in value
    ):
        raise ValueError("Bitte mindestens eine Sondertaste und eine Taste wählen.")
    return "+".join(converted)


def macos_accessibility_trusted(prompt: bool = False) -> bool:
    """Return whether macOS permits global hotkeys and simulated paste events."""
    if platform.system() != "Darwin":
        return True
    try:
        from ApplicationServices import (
            AXIsProcessTrusted,
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )

        if prompt:
            return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}))
        return bool(AXIsProcessTrusted())
    except (ImportError, AttributeError):
        return False


def microphone_denied() -> bool:
    # Read-only check. The recorder triggers the OS microphone prompt on first
    # use; checking status must not start recording or open a permission dialog.
    return (
        platform.system() == "Darwin"
        and QApplication.instance() is not None
        and QApplication.instance().checkPermission(QMicrophonePermission())
        == Qt.PermissionStatus.Denied
    )


def model_helper_command(*arguments: str) -> tuple[str, list[str]]:
    if getattr(sys, "frozen", False):
        suffix = ".exe" if platform.system() == "Windows" else ""
        helper = Path(sys.executable).with_name("opentalk-model-setup" + suffix)
        return str(helper), list(arguments)
    return sys.executable, [str(Path(__file__).resolve().parent / "model_setup.py"), *arguments]


def hyprctl(*args: str) -> str:
    result = subprocess.run(
        ["hyprctl", *args], capture_output=True, text=True, check=True, timeout=3
    )
    return result.stdout.strip()


def active_target() -> str:
    if not shutil.which("hyprctl"):
        return ""
    try:
        client = json.loads(hyprctl("activewindow", "-j"))
        address = client.get("address", "")
        if client.get("pid") == os.getpid() or not ADDRESS.fullmatch(address):
            return ""
        return address
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""


def setup_problem() -> str | None:
    dependency = opentalk.recorder_dependency()
    if platform.system() == "Darwin" and platform.machine() != "arm64":
        return "macOS wird nur auf Macs mit M-Prozessor unterstützt."
    if not shutil.which(dependency) and not Path(dependency).is_file():
        return f"{Path(dependency).name} fehlt: Aufnahme-Abhängigkeit installieren."
    if opentalk.config("SERVER_URL"):
        if not opentalk.config("TOKEN"):
            return "Homeserver-Token fehlt."
    elif not opentalk.model_path().is_file() or not (
        shutil.which(opentalk.whisper_cli()) or Path(opentalk.whisper_cli()).is_file()
    ):
        return "Erkennung fehlt · ⚙"
    return None


def read_settings() -> dict:
    path = opentalk.settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_setting(name: str, value) -> None:
    """Update one setting atomically so an interrupted write cannot corrupt it."""
    path = opentalk.settings_path()
    data = read_settings()
    data[name] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(json.dumps(data), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def apply_layer_shell(window: QWidget) -> bool:
    if not os.environ.get("WAYLAND_DISPLAY") or not os.environ.get(
        "QT_QPA_PLATFORM", "wayland"
    ).startswith("wayland"):
        return False
    project = opentalk.resource_dir()
    source = project / "layer_shell_bridge.cpp"
    library = opentalk.local_data_dir() / f"cache/libopentalk-layer-{qVersion()}.so"
    try:
        # LayerShellQt is supplied by the distribution. Do not hand a QWindow
        # from bundled/pip Qt to a bridge built against a different Qt runtime.
        version = subprocess.run(
            ["pkg-config", "--modversion", "Qt6Core"], capture_output=True,
            text=True, check=True, timeout=5,
        ).stdout.strip()
        if version != qVersion():
            return False
        if not library.is_file() or library.stat().st_mtime < source.stat().st_mtime:
            library.parent.mkdir(parents=True, exist_ok=True)
            flags = subprocess.run(
                ["pkg-config", "--cflags", "--libs", "Qt6Gui", "Qt6Core"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            subprocess.run(
                [
                    "g++",
                    "-shared",
                    "-fPIC",
                    "-std=c++17",
                    str(source),
                    "-o",
                    str(library),
                    *shlex.split(flags.stdout),
                    "-lLayerShellQtInterface",
                ],
                capture_output=True,
                check=True,
                timeout=30,
            )
        window.winId()
        pointer = sip.unwrapinstance(window.windowHandle())
        bridge = ctypes.CDLL(str(library))
        bridge.opentalk_layer.argtypes = [ctypes.c_void_p]
        bridge.opentalk_layer.restype = ctypes.c_int
        bridge.opentalk_set_screen.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        bridge.opentalk_set_screen.restype = None
        bridge.opentalk_set_size.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        bridge.opentalk_set_size.restype = None
        bridge.opentalk_set_position.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        bridge.opentalk_set_position.restype = None
        if bridge.opentalk_layer(pointer) != 0:
            return False
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        bridge.opentalk_set_screen(pointer, sip.unwrapinstance(screen))
        window._layer_bridge = bridge
        window._layer_screen = screen
        return True
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def insert_into_target(value: str, target: str) -> str:
    if not value:
        return "Keine Sprache erkannt."
    if platform.system() == "Darwin":
        if not shutil.which("pbcopy"):
            return "Zwischenablage konnte nicht beschrieben werden: pbcopy fehlt."
        try:
            subprocess.run(["pbcopy"], input=value.encode("utf-8"), check=True, timeout=10)
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
            return (
                "Text eingefügt."
                if result.returncode == 0
                else "Text kopiert – Bedienungshilfen erlauben oder mit Cmd+V einfügen."
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return "Zwischenablage konnte nicht beschrieben werden."
    if platform.system() == "Windows":
        try:
            opentalk.windows_copy_text(value)
            opentalk.windows_paste()
            return "Text eingefügt."
        except (OSError, RuntimeError):
            return "Text konnte nicht in das aktive Fenster eingefügt werden."
    if target and ADDRESS.fullmatch(target) and shutil.which("hyprctl") and shutil.which("wl-copy"):
        try:
            subprocess.run(
                ["wl-copy", "--type", "text/plain;charset=utf-8"],
                input=value.encode(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=10,
            )
            if active_target() != target:
                focus = hyprctl("dispatch", f'hl.dsp.focus({{ window = "address:{target}" }})')
                if focus != "ok":
                    return "Zielfenster konnte nicht aktiviert werden."
            action = (
                f'hl.dsp.send_shortcut({{ mods = "CTRL", key = "V", window = "address:{target}" }})'
            )
            if hyprctl("dispatch", action) == "ok":
                return "Text eingefügt."
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
        return "Einfügen ins Textfeld fehlgeschlagen."
    for tool, command, kwargs in (
        ("wtype", ["wtype", "-"], {"input": value.encode()}),
        ("kwtype", ["kwtype", value], {}),
    ):
        if shutil.which(tool):
            try:
                subprocess.run(command, capture_output=True, check=True, timeout=15, **kwargs)
                return "Text eingefügt."
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                pass
    if not shutil.which("wl-copy"):
        return "Einfügen fehlgeschlagen: wtype oder wl-clipboard installieren."
    try:
        subprocess.run(
            ["wl-copy", "--type", "text/plain;charset=utf-8"],
            input=value.encode(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return "Zwischenablage konnte nicht beschrieben werden."
    return "Text kopiert – mit Strg+V einfügen."


class SetupDialog(QDialog):
    MODEL_LABELS = ("Tiny", "Base", "Small", "Medium", "Large v3")
    MODEL_SIZES = ("75 MiB", "142 MiB", "466 MiB", "1,5 GiB", "2,9 GiB")

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle("OpenTalk Einstellungen")
        self.resize(520, 465)
        self.setStyleSheet("""
            QDialog { background-color: #17212d; }
            QLabel { color: #edf3fa; }
            QLabel#heading { font-size: 17px; font-weight: 700; }
            QLabel#muted { color: #adbdcb; }
            QPushButton { color: #f4f7fb; background-color: #2b4053;
                          border: 1px solid #496074; border-radius: 11px;
                          padding: 8px 12px; font-weight: 600; }
            QPushButton:hover { background-color: #3b5670; }
            QPushButton:disabled { color: #8794a2; background-color: #243240; }
            QPlainTextEdit { color: #dfebf5; background-color: #203141;
                             border: 1px solid #496074; border-radius: 10px; }
            QSlider::groove:horizontal { background: #3b5265; height: 6px; border-radius: 3px; }
            QSlider::handle:horizontal { background: #ee637c; width: 19px; margin: -7px 0;
                                         border-radius: 9px; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        hotkey_heading = QLabel("Globaler Hotkey")
        hotkey_heading.setObjectName("heading")
        layout.addWidget(hotkey_heading)
        hotkey_row = QHBoxLayout()
        self.hotkey_edit = QKeySequenceEdit(QKeySequence(translate_qt_hotkey(selected_hotkey())))
        self.hotkey_edit.setMaximumSequenceLength(1)
        self.hotkey_button = QPushButton("Übernehmen")
        self.hotkey_button.clicked.connect(self.apply_hotkey)
        hotkey_row.addWidget(self.hotkey_edit, 1)
        hotkey_row.addWidget(self.hotkey_button)
        layout.addLayout(hotkey_row)
        self.hotkey_info = QLabel()
        self.hotkey_info.setObjectName("muted")
        self.hotkey_info.setWordWrap(True)
        layout.addWidget(self.hotkey_info)
        self.hold_checkbox = QCheckBox("Zum Sprechen Hotkey gedrückt halten")
        self.hold_checkbox.setStyleSheet("color: #edf3fa;")
        self.hold_checkbox.setChecked(read_settings().get("hold_to_talk") is True)
        self.hold_checkbox.toggled.connect(self.apply_hold_mode)
        layout.addWidget(self.hold_checkbox)
        self.sleep_checkbox = QCheckBox("Modell nach 5 Minuten Pause aus dem Speicher laden")
        self.sleep_checkbox.setStyleSheet("color: #edf3fa;")
        self.sleep_checkbox.setChecked(read_settings().get("model_sleep", True) is not False)
        self.sleep_checkbox.toggled.connect(self.apply_sleep_mode)
        layout.addWidget(self.sleep_checkbox)
        self.permission_info = QLabel()
        self.permission_info.setObjectName("muted")
        self.permission_info.setWordWrap(True)
        layout.addWidget(self.permission_info)
        self.permission_button = QPushButton("Berechtigungen öffnen")
        self.permission_button.clicked.connect(self.open_permissions)
        layout.addWidget(self.permission_button)
        self.copy_button = QPushButton("Letztes Diktat kopieren")
        self.copy_button.clicked.connect(parent.copy_last_transcript)
        layout.addWidget(self.copy_button)
        heading = QLabel("Whisper-Modell")
        heading.setObjectName("heading")
        layout.addWidget(heading)
        explanation = QLabel(
            "Nach rechts werden die Modelle genauer, aber die Erkennung dauert länger."
        )
        explanation.setObjectName("muted")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, len(opentalk.MODEL_NAMES) - 1)
        self.slider.setTickInterval(1)
        self.slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider.setPageStep(1)
        self.slider.setValue(opentalk.MODEL_NAMES.index(opentalk.selected_model()))
        self.slider.valueChanged.connect(self.model_changed)
        self.slider.sliderReleased.connect(self.activate_if_installed)
        layout.addWidget(self.slider)
        labels = QHBoxLayout()
        for text in self.MODEL_LABELS:
            label = QLabel(text)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            labels.addWidget(label, 1)
        layout.addLayout(labels)

        self.model_info = QLabel()
        self.model_info.setWordWrap(True)
        layout.addWidget(self.model_info)
        self.download_button = QPushButton()
        self.download_button.clicked.connect(self.download_model)
        layout.addWidget(self.download_button)

        self.info = QLabel()
        self.info.setObjectName("muted")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.install_button = QPushButton("Lokale Erkennung einrichten")
        self.install_button.clicked.connect(self.start_install)
        layout.addWidget(self.install_button)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.document().setMaximumBlockCount(150)
        self.log.setFixedHeight(86)
        layout.addWidget(self.log)
        self.log.hide()

        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        self.operation: str | None = None
        self.model_locked = bool(opentalk.config("SERVER_URL") or opentalk.config("MODEL"))
        self.slider.setEnabled(not self.model_locked)
        self.refresh_model_info()
        self.refresh_engine_info()
        self.hotkey_info.setText(parent.hotkey_status)
        self.refresh_permissions()

    def apply_hold_mode(self, enabled: bool) -> None:
        try:
            save_setting("hold_to_talk", enabled)
        except OSError:
            self.hold_checkbox.blockSignals(True)
            self.hold_checkbox.setChecked(self.parent().hold_to_talk)
            self.hold_checkbox.blockSignals(False)
            self.hotkey_info.setText("Hotkey-Modus konnte nicht gespeichert werden.")
            return
        self.parent().on_hotkey_released()
        self.parent().hold_to_talk = enabled

    def apply_sleep_mode(self, enabled: bool) -> None:
        try:
            save_setting("model_sleep", enabled)
        except OSError:
            self.sleep_checkbox.blockSignals(True)
            self.sleep_checkbox.setChecked(not enabled)
            self.sleep_checkbox.blockSignals(False)
            self.info.setText("Ruhemodus konnte nicht gespeichert werden.")
            return
        self.parent().configure_model_sleep()

    def refresh_permissions(self) -> None:
        if platform.system() == "Darwin":
            missing = []
            if microphone_denied():
                missing.append("Mikrofonzugriff fehlt")
            if not macos_accessibility_trusted():
                missing.append("Bedienungshilfen für Hotkey/Einfügen fehlen")
            self.permission_info.setText(" · ".join(missing))
            self.permission_info.setVisible(bool(missing))
            self.permission_button.setVisible(bool(missing))
        else:
            self.permission_info.hide()
            self.permission_button.setVisible(platform.system() == "Windows")

    def open_permissions(self) -> None:
        if platform.system() == "Darwin":
            pane = "Privacy_Microphone" if microphone_denied() else "Privacy_Accessibility"
            url = "x-apple.systempreferences:com.apple.preference.security?" + pane
        else:
            url = "ms-settings:privacy-microphone"
        QDesktopServices.openUrl(QUrl(url))

    def apply_hotkey(self) -> None:
        value = translate_qt_hotkey(
            self.hotkey_edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        )
        if not value:
            self.hotkey_info.setText("Der Hotkey darf nicht leer sein.")
            return
        try:
            pynput_hotkey(value)
            save_setting("hotkey", value)
            status = self.parent().configure_hotkey()
            self.hotkey_info.setText(status)
        except (OSError, ValueError) as exc:
            self.hotkey_info.setText(str(exc))

    def chosen_model(self) -> str:
        return opentalk.MODEL_NAMES[self.slider.value()]

    def model_changed(self) -> None:
        self.refresh_model_info()
        if not self.slider.isSliderDown():
            self.activate_if_installed()

    def activate_if_installed(self) -> None:
        name = self.chosen_model()
        if self.model_locked or not opentalk.model_available(name) or self.operation:
            return
        if name != opentalk.selected_model():
            try:
                save_setting("model", name)
            except OSError:
                self.info.setText("Modellwahl konnte nicht gespeichert werden.")
                return
            self.info.setText(f"{name} ist aktiv. Die nächste Erkennung verwendet dieses Modell.")
            self.parent().update_status()
        self.refresh_model_info()

    def refresh_model_info(self) -> None:
        name = self.chosen_model()
        size = self.MODEL_SIZES[self.slider.value()]
        installed = opentalk.model_available(name)
        active = opentalk.selected_model()
        if self.model_locked:
            self.model_info.setText("Ein eigener Modellpfad oder Homeserver ist konfiguriert.")
        elif installed:
            self.model_info.setText(f"{name} · {size} · installiert  |  Aktuell: {active}")
        else:
            self.model_info.setText(
                f"{name} · {size} · noch nicht installiert  |  Aktuell: {active}"
            )
        self.download_button.setText(
            f"{name} herunterladen ({size})" if not installed else f"{name} ist installiert"
        )
        self.download_button.setEnabled(
            not installed and not self.model_locked and not self.operation
        )

    def refresh_engine_info(self) -> None:
        self.install_button.setVisible(not self.model_locked and setup_problem() is not None)
        if opentalk.config("SERVER_URL"):
            self.info.setText("Der Homeserver bestimmt das Whisper-Modell.")
            self.install_button.setEnabled(False)
        elif opentalk.config("MODEL"):
            self.info.setText("OPENTALK_MODEL überschreibt die Modellwahl in der Oberfläche.")
            self.install_button.setEnabled(False)
        elif setup_problem() is None:
            self.info.setText("Die lokale Spracherkennung ist eingerichtet.")
            self.install_button.setEnabled(False)
        else:
            self.info.setText(
                "whisper.cpp und das Standardmodell können lokal eingerichtet werden."
            )
            self.install_button.setEnabled(not self.operation)

    def start_install(self) -> None:
        if self.operation:
            return
        self.operation = "setup"
        self.install_button.setEnabled(False)
        self.slider.setEnabled(False)
        self.download_button.setEnabled(False)
        self.log.clear()
        self.log.show()
        self.info.setText("Einrichtung läuft …")
        mode = "--setup-models" if opentalk.bundled_executable("whisper-cli") else "--setup-engine"
        program, arguments = model_helper_command(mode)
        self.process.start(program, arguments)

    def download_model(self) -> None:
        name = self.chosen_model()
        if self.operation or self.model_locked or opentalk.model_available(name):
            return
        self.operation = name
        self.slider.setEnabled(False)
        self.install_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.log.clear()
        self.log.show()
        self.info.setText(f"Lade {name} herunter und prüfe die Datei …")
        program, arguments = model_helper_command("--download-model", name)
        self.process.start(program, arguments)

    def read_output(self) -> None:
        output = bytes(self.process.readAllStandardOutput()).decode(errors="replace")
        for line in output.replace("\r", "\n").splitlines()[-10:]:
            if line.strip():
                self.log.appendPlainText(line.strip())

    def process_error(self, error: QProcess.ProcessError) -> None:
        # FailedToStart does not emit finished: explicitly unlock the controls so
        # a missing helper never leaves setup stuck on "Einrichtung läuft".
        if error == QProcess.ProcessError.FailedToStart and self.operation is not None:
            self.log.appendPlainText(self.process.errorString())
            self.finished(1, QProcess.ExitStatus.NormalExit)

    def finished(self, code: int, _status) -> None:
        self.read_output()
        operation = self.operation
        self.operation = None
        self.slider.setEnabled(not self.model_locked)
        if operation == "setup":
            self.info.setText(
                "Einrichtung abgeschlossen."
                if code == 0
                else "Einrichtung fehlgeschlagen. Ausgabe unten prüfen."
            )
        elif operation is not None:
            if code == 0 and opentalk.model_available(operation):
                try:
                    save_setting("model", operation)
                    self.info.setText(f"{operation} ist installiert und aktiv.")
                except OSError:
                    self.info.setText(
                        "Modell installiert, Auswahl konnte nicht gespeichert werden."
                    )
            else:
                self.info.setText("Download fehlgeschlagen. Ausgabe unten prüfen.")
        self.refresh_model_info()
        if operation != "setup" or code == 0:
            self.parent().update_status()
        self.install_button.setEnabled(not self.model_locked and setup_problem() is not None)
        self.install_button.setVisible(self.install_button.isEnabled())


class Overlay(QWidget):
    chunk_ready = pyqtSignal(str)
    error_ready = pyqtSignal(str)
    finished_ready = pyqtSignal()
    hotkey_pressed = pyqtSignal()
    hotkey_released = pyqtSignal()
    hotkey_cleared = pyqtSignal()
    level_ready = pyqtSignal(float)
    notice_ready = pyqtSignal(str)
    start_ready = pyqtSignal(object, str)
    insertion_ready = pyqtSignal(str)
    sources_ready = pyqtSignal(object, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        if platform.system() == "Darwin":
            # Qt normally hides macOS tool windows as soon as another app becomes
            # active. Keep the dictation bubble visible while the user works in
            # the target app (for example a browser or text editor).
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setFixedSize(CIRCLE, CIRCLE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Klick: Aufnahme · Doppelklick: Optionen · Ziehen: verschieben")

        position = read_settings().get("position")
        self.anchor = (
            QPoint(position["x"], position["y"])
            if isinstance(position, dict)
            and type(position.get("x")) is int
            and type(position.get("y")) is int
            else None
        )
        self.layer_shell = False
        self.expanded = True
        self.menu_below = False
        self.menu_main_x = 96
        self.state = "idle"
        self.engine: LiveDictation | None = None
        self.starting = False
        self.stop_after_start = False
        self.closing = False
        self.inserting = False
        self.sources_loading = False
        self.source_menu: QMenu | None = None
        self.hotkey_listener = None
        self.hotkey_error = ""
        self.hotkey_status = ""
        self.hold_to_talk = read_settings().get("hold_to_talk") is True
        self.push_active = False
        self.hotkey_keys_held = False
        self.deferred_text: list[str] = []
        self.mic_level = 0.0
        self.local_session = False
        self.setup_dialog: SetupDialog | None = None
        self.source = opentalk.saved_source()
        self.target = ""
        self.output_started = False
        self.transcript_parts: list[str] = []
        self.pending_parts: list[str] = []
        self.clipboard_only = False
        self.drag_offset: QPoint | None = None
        self.press_point: QPoint | None = None
        self.ignore_release = False
        self.drag_timer = QTimer(self)
        self.drag_timer.setInterval(40)
        self.drag_timer.timeout.connect(self.update_drag)
        self.click_timer = QTimer(self)
        self.click_timer.setSingleShot(True)
        self.click_timer.timeout.connect(self.toggle_recording)
        self.screen_timer = QTimer(self)
        self.screen_timer.timeout.connect(self.follow_screen)
        self.model_idle_timer = QTimer(self)
        self.model_idle_timer.setInterval(60_000)
        self.model_idle_timer.timeout.connect(self.release_idle_model)
        self.configure_model_sleep()
        self.pin_attempts = 0

        self.mic_button = self.round_button("🎙", "Mikrofon auswählen", self.show_sources)
        self.settings_button = self.round_button("⚙", "Erkennung einrichten", self.open_setup)
        self.close_button = self.round_button("×", "OpenTalk schließen", self.close)
        self.layout_satellites()
        self.set_expanded(False)

        self.chunk_ready.connect(self.on_chunk)
        self.error_ready.connect(self.on_error)
        self.finished_ready.connect(self.on_finished)
        self.hotkey_pressed.connect(self.on_hotkey_pressed)
        self.hotkey_released.connect(self.on_hotkey_released)
        self.hotkey_cleared.connect(self.on_hotkey_cleared)
        self.level_ready.connect(self.on_level)
        self.notice_ready.connect(self.on_notice)
        self.start_ready.connect(self.on_started)
        self.insertion_ready.connect(self.on_inserted)
        self.sources_ready.connect(self.on_sources)
        self.layer_shell = apply_layer_shell(self)
        # Only layer-shell windows need polling to follow the active monitor.
        # Avoid a permanent wake-up timer on macOS, Windows and normal X11.
        if self.layer_shell:
            self.screen_timer.start(1500)
        self.place()
        self.show()
        self.configure_hotkey()
        if not self.layer_shell:
            QTimer.singleShot(350, self.pin)
        self.update_status()

    def configure_hotkey(self) -> str:
        self.hotkey_error = ""
        if self.hotkey_listener is not None:
            self.on_hotkey_released()
            self.on_hotkey_cleared()
            self.hotkey_listener.stop()
            self.hotkey_listener = None
        value = selected_hotkey()
        if not macos_accessibility_trusted(prompt=True):
            message = (
                "macOS-Bedienungshilfen fehlen: OpenTalk beziehungsweise Python "
                "unter Datenschutz & Sicherheit erlauben und OpenTalk neu starten."
            )
            self.hotkey_error = message
            self.hotkey_status = "Hotkey nicht aktiv: macOS-Bedienungshilfen fehlen."
            self.set_status(message, error=True)
            return self.hotkey_status
        try:
            from pynput import keyboard

            keys = keyboard.HotKey.parse(pynput_hotkey(value))
            state = None
            listener = keyboard.Listener(
                on_press=lambda key: state.press(key),
                on_release=lambda key: state.release(key),
            )
            state = HotkeyState(
                keys, listener.canonical,
                lambda down: self.hotkey_pressed.emit() if down else self.hotkey_released.emit(),
                self.hotkey_cleared.emit,
            )
            self.hotkey_listener = listener
            self.hotkey_listener.start()
            label = QKeySequence(translate_qt_hotkey(value)).toString(
                QKeySequence.SequenceFormat.NativeText
            )
            self.hotkey_status = f"Aktiv: {label}"
            self.update_status()
            return self.hotkey_status
        except Exception as exc:
            self.hotkey_error = f"Hotkey {value} konnte nicht registriert werden: {exc}"
            self.hotkey_status = f"Hotkey nicht aktiv: {exc}"
            self.set_status(self.hotkey_error, error=True)
            return self.hotkey_status

    def configure_model_sleep(self) -> None:
        if not opentalk.config("SERVER_URL") and read_settings().get("model_sleep", True) is not False:
            self.model_idle_timer.start()
        else:
            self.model_idle_timer.stop()

    def release_idle_model(self) -> None:
        if self.engine is None and opentalk.LOCAL_WHISPER_SERVER.process is not None:
            threading.Thread(target=opentalk.LOCAL_WHISPER_SERVER.release_if_idle, daemon=True).start()

    def on_hotkey_pressed(self) -> None:
        if self.setup_dialog is not None and self.setup_dialog.hotkey_edit.hasFocus():
            return
        self.hotkey_keys_held = True
        if self.hold_to_talk:
            if self.engine is None:
                self.toggle_recording()
                self.push_active = self.engine is not None
        else:
            self.toggle_recording()

    def on_hotkey_released(self) -> None:
        if self.push_active:
            self.push_active = False
            if self.engine is not None and (self.starting or self.engine.recording):
                self.toggle_recording()

    def on_hotkey_cleared(self) -> None:
        # Pasting with physical Cmd/Ctrl/Shift still held can trigger a different
        # shortcut in the target app. Capture stops on release; insertion waits
        # until all keys of the dictation shortcut have been released.
        self.hotkey_keys_held = False
        pending, self.deferred_text = self.deferred_text, []
        for text in pending:
            self.insert_chunk(text)
        self.insert_next()
        if pending and self.engine is None and not self.pending_parts and self.state != "error":
            self.state = "idle"
            self.set_status("Bereit")
            self.update()

    def on_level(self, level: float) -> None:
        self.mic_level = level if self.engine is not None and self.engine.recording else 0.0
        self.update()

    def on_notice(self, message: str) -> None:
        if self.engine is not None and self.engine.recording and self.state != "error":
            self.set_status(message)
            if message.startswith("Kein Mikrofonpegel"):
                QToolTip.showText(self.mapToGlobal(self.rect().center()), message, self)
            else:
                QToolTip.hideText()

    def round_button(self, label: str, tooltip: str, handler) -> QPushButton:
        button = QPushButton(label, self)
        button.setFixedSize(SATELLITE, SATELLITE)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(tooltip)
        button.setStyleSheet("""
            QPushButton { color: #f3f6fa; background-color: #263849;
                          border: 1px solid #496074; border-radius: 28px;
                          font-size: 22px; font-weight: 600; }
            QPushButton:hover { background-color: #3c5368; border-color: #7790a5; }
        """)
        button.clicked.connect(handler)
        return button

    def layout_satellites(self) -> None:
        y = 128 if self.menu_below else 20
        self.mic_button.move(20, y)
        self.settings_button.move(102, y)
        self.close_button.move(184, y)

    def main_rect(self) -> QRect:
        return (
            QRect(self.menu_main_x, 0 if self.menu_below else 126, CIRCLE, CIRCLE)
            if self.expanded
            else QRect(0, 0, CIRCLE, CIRCLE)
        )

    def set_status(self, message: str, error: bool = False) -> None:
        self.setToolTip(message + "\nKlick: Aufnahme · Doppelklick: Optionen · Ziehen: verschieben")
        if error:
            self.state = "error"
            self.update()
            QToolTip.showText(QCursor.pos(), message, self)

    def update_status(self) -> None:
        problem = setup_problem() or self.hotkey_error
        if problem:
            self.set_status(problem, error=True)
        elif self.state == "error":
            self.state = "idle"
            self.set_status("Bereit")
            self.update()

    def set_expanded(self, visible: bool) -> None:
        if self.expanded == visible and self.width() == (MENU_WIDTH if visible else CIRCLE):
            return
        if visible and self.anchor is not None:
            screen = self.current_screen().geometry()
            self.menu_below = self.anchor.y() < MENU_HEIGHT - CIRCLE
            self.menu_main_x = (
                0
                if self.anchor.x() < 96
                else MENU_WIDTH - CIRCLE
                if self.anchor.x() > screen.width() - 164
                else 96
            )
            self.layout_satellites()
        self.expanded = visible
        self.setFixedSize(MENU_WIDTH, MENU_HEIGHT) if visible else self.setFixedSize(CIRCLE, CIRCLE)
        for button in (self.mic_button, self.settings_button, self.close_button):
            button.setVisible(visible)
        if self.layer_shell:
            self._layer_bridge.opentalk_set_size(
                sip.unwrapinstance(self.windowHandle()), self.width(), self.height()
            )
        if self.anchor is not None:
            self.place()
        self.update()

    def current_screen(self):
        if self.layer_shell:
            return self._layer_screen
        return QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()

    def place(self) -> None:
        screen = self.current_screen()
        area = screen.availableGeometry()
        geometry = screen.geometry()
        if self.anchor is None:
            self.anchor = QPoint(
                area.x() - geometry.x() + (area.width() - CIRCLE) // 2,
                area.y() - geometry.y() + area.height() - CIRCLE - 24,
            )
        x = max(0, min(self.anchor.x() - self.main_rect().x(), geometry.width() - self.width()))
        y = max(0, min(self.anchor.y() - self.main_rect().y(), geometry.height() - self.height()))
        if self.layer_shell:
            self._layer_bridge.opentalk_set_position(sip.unwrapinstance(self.windowHandle()), x, y)
        else:
            self.move(geometry.x() + x, geometry.y() + y)

    def cursor_position(self) -> QPoint:
        if self.layer_shell and shutil.which("hyprctl"):
            try:
                result = subprocess.run(
                    ["hyprctl", "cursorpos", "-j"],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=0.3,
                )
                point = json.loads(result.stdout)
                return QPoint(point["x"], point["y"])
            except (
                OSError,
                ValueError,
                KeyError,
                subprocess.CalledProcessError,
                subprocess.TimeoutExpired,
            ):
                pass
        return QCursor.pos()

    def begin_drag(self) -> None:
        screen = self.current_screen()
        self.drag_offset = self.cursor_position() - screen.geometry().topLeft() - self.anchor
        self.click_timer.stop()
        self.drag_timer.start()
        self.grabMouse()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def update_drag(self) -> None:
        if self.drag_offset is None:
            return
        point = self.cursor_position()
        screen = QApplication.screenAt(point)
        if screen is None:
            return
        if self.layer_shell and screen != self._layer_screen:
            self._layer_bridge.opentalk_set_screen(
                sip.unwrapinstance(self.windowHandle()), sip.unwrapinstance(screen)
            )
            self._layer_screen = screen
        self.anchor = point - screen.geometry().topLeft() - self.drag_offset
        self.anchor.setX(max(0, min(self.anchor.x(), screen.geometry().width() - CIRCLE)))
        self.anchor.setY(max(0, min(self.anchor.y(), screen.geometry().height() - CIRCLE)))
        self.place()

    def end_drag(self) -> None:
        self.update_drag()
        self.drag_timer.stop()
        self.releaseMouse()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.drag_offset = None
        try:
            save_setting("position", {"x": self.anchor.x(), "y": self.anchor.y()})
        except OSError:
            self.set_status("Position nicht gespeichert", error=True)

    def follow_screen(self) -> None:
        if self.layer_shell and self.drag_offset is None:
            screen = QApplication.screenAt(self.cursor_position())
            if screen is not None and screen != self._layer_screen:
                self._layer_bridge.opentalk_set_screen(
                    sip.unwrapinstance(self.windowHandle()), sip.unwrapinstance(screen)
                )
                self._layer_screen = screen
                self.place()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.main_rect().adjusted(3, 3, -3, -3)
        colors = {
            "idle": ("#223a4d", "#6d8ba2"),
            "recording": ("#e75975", "#ff9cb0"),
            "processing": ("#4d6f89", "#90b9d1"),
            "error": ("#956244", "#e6a16d"),
        }
        fill, stroke = colors[self.state]
        painter.setPen(QPen(QColor(stroke), 2))
        painter.setBrush(QColor(fill))
        painter.drawEllipse(rect)
        if self.engine is not None and self.engine.recording and self.mic_level > 0:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#a9f0c3"), 3, cap=Qt.PenCapStyle.RoundCap))
            painter.drawArc(rect.adjusted(4, 4, -4, -4), 90 * 16, -int(360 * 16 * self.mic_level))
        center = rect.center()
        painter.setPen(
            QPen(
                QColor("#f8fbff"),
                3,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.setBrush(QColor("#f8fbff"))
        if self.engine is not None and self.engine.recording:
            painter.drawRoundedRect(center.x() - 9, center.y() - 9, 18, 18, 3, 3)
        elif self.state == "processing":
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawArc(center.x() - 13, center.y() - 13, 26, 26, 30 * 16, 285 * 16)
        else:
            painter.drawRoundedRect(center.x() - 6, center.y() - 13, 12, 20, 6, 6)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawArc(center.x() - 12, center.y() - 8, 24, 25, 180 * 16, 180 * 16)
            painter.drawLine(center.x(), center.y() + 11, center.x(), center.y() + 18)
            painter.drawLine(center.x() - 7, center.y() + 18, center.x() + 7, center.y() + 18)

    def mousePressEvent(self, event) -> None:
        if not self.main_rect().contains(event.position().toPoint()):
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.press_point = None
            self.begin_drag()
        elif event.button() == Qt.MouseButton.LeftButton:
            self.press_point = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event) -> None:
        if self.drag_offset is not None:
            self.update_drag()
        elif (
            self.press_point is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and (event.globalPosition().toPoint() - self.press_point).manhattanLength() > 8
        ):
            self.press_point = None
            self.begin_drag()

    def mouseReleaseEvent(self, event) -> None:
        if self.drag_offset is not None:
            self.end_drag()
            return
        if self.ignore_release:
            self.ignore_release = False
            self.press_point = None
            return
        if event.button() == Qt.MouseButton.LeftButton and self.press_point is not None:
            self.press_point = None
            self.click_timer.start(QApplication.doubleClickInterval())

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.main_rect().contains(
            event.position().toPoint()
        ):
            self.click_timer.stop()
            self.press_point = None
            self.ignore_release = True
            self.set_expanded(not self.expanded)

    def show_sources(self) -> None:
        if self.sources_loading or self.closing:
            return
        self.sources_loading = True
        self.mic_button.setEnabled(False)
        self.set_status("Mikrofone werden gesucht …")

        def discover():
            try:
                self.sources_ready.emit(audio_sources.list_sources(), "")
            except Exception as exc:
                self.sources_ready.emit([], str(exc))

        threading.Thread(target=discover, daemon=True).start()

    def on_sources(self, sources: list, error: str) -> None:
        self.sources_loading = False
        self.mic_button.setEnabled(True)
        if self.closing:
            return
        if error:
            self.set_status(error, error=True)
            return
        if self.source_menu is not None:
            self.source_menu.deleteLater()
        menu = QMenu(self)
        self.source_menu = menu
        menu.setStyleSheet(
            "QMenu { background: #203141; color: #f3f6fa; border: 1px solid #496074; }"
            "QMenu::item:selected { background: #3e5970; }"
        )
        for label, name in [("Standardmikrofon", ""), *sources]:
            action = menu.addAction(("✓  " if name == self.source else "    ") + label)
            action.setData(name)
        menu.triggered.connect(self.select_source)
        menu.popup(self.mic_button.mapToGlobal(self.mic_button.rect().bottomLeft()))

    def select_source(self, selected) -> None:
        self.source = selected.data()
        try:
            save_setting("source", self.source)
        except OSError:
            self.set_status("Mikrofonwahl nicht gespeichert", error=True)
        self.set_expanded(False)
        self.set_status("Mikrofon: " + selected.text().lstrip("✓ ").strip())

    def open_setup(self) -> None:
        if self.setup_dialog is None:
            self.setup_dialog = SetupDialog(self)
        self.setup_dialog.refresh_permissions()
        self.setup_dialog.show()
        self.setup_dialog.raise_()

    def toggle_recording(self) -> None:
        if self.closing:
            return
        if self.starting:
            self.stop_after_start = True
            self.set_status("Aufnahme wird gestoppt …")
            return
        if self.engine is not None and self.engine.recording:
            self.engine.stop()
            self.mic_level = 0.0
            self.state = "processing"
            self.set_status("Letzte Wörter werden erkannt …")
            self.update()
            return
        # The worker can finish before Qt delivers its final queued signals.
        # Only on_finished may release the session and allow the next recording.
        if self.engine is not None:
            self.set_status("Letzte Wörter werden noch erkannt …")
            return
        if self.inserting or (self.pending_parts and not self.clipboard_only):
            self.set_status("Erkannten Text noch fertig einfügen …")
            return
        if self.deferred_text:
            self.set_status("Hotkey vollständig loslassen, um den Text einzufügen.")
            return
        if microphone_denied():
            self.set_status("Mikrofonzugriff fehlt · ⚙ → Berechtigungen öffnen", error=True)
            self.set_expanded(True)
            return
        problem = setup_problem()
        if problem:
            self.set_status(problem, error=True)
            self.set_expanded(True)
            return
        self.target = active_target()
        if shutil.which("hyprctl") and not self.target:
            self.set_status("Zuerst ein Textfeld in einem Fenster aktivieren.", error=True)
            return
        self.output_started = False
        self.pending_parts = []
        self.clipboard_only = False
        self.engine = LiveDictation(
            self.chunk_ready.emit,
            self.error_ready.emit,
            self.finished_ready.emit,
            source=self.source,
            on_level=self.level_ready.emit,
            on_notice=self.notice_ready.emit,
        )
        opentalk.LOCAL_WHISPER_SERVER.begin_session()
        self.local_session = True
        opentalk.warm_transcriber_async()
        self.starting = True
        self.stop_after_start = False
        self.transcript_parts = []
        self.state = "processing"
        self.set_status("Mikrofon wird gestartet …")
        self.update()
        engine = self.engine

        def start():
            error = ""
            try:
                engine.start()
                if self.closing:
                    engine.cancel()
            except Exception as exc:
                error = str(exc)
            self.start_ready.emit(engine, error)

        threading.Thread(target=start, daemon=True).start()

    def on_started(self, engine: LiveDictation, error: str) -> None:
        if self.closing or self.engine is not engine:
            return
        self.starting = False
        if error:
            opentalk.LOCAL_WHISPER_SERVER.end_session()
            self.local_session = False
            self.engine = None
            self.push_active = False
            self.set_status(error, error=True)
            return
        if self.stop_after_start:
            self.toggle_recording()
            return
        self.state = "recording"
        self.set_status("Aufnahme läuft · Klick zum Stoppen")
        self.update()

    def on_chunk(self, text: str) -> None:
        if self.closing:
            return
        text = text.strip()
        if not text:
            return
        self.transcript_parts.append(text)
        if self.hotkey_keys_held:
            self.deferred_text.append(text)
            self.set_status("Text erkannt · Hotkey loslassen zum Einfügen")
            return
        self.insert_chunk(text)

    def insert_chunk(self, text: str) -> None:
        self.pending_parts.append(text)
        self.insert_next()

    def insert_next(self) -> None:
        # Exactly one paste at a time. Qt and clipboard recovery stay on the
        # GUI thread; potentially slow native tools run in a daemon worker.
        if self.closing or self.inserting or not self.pending_parts or self.hotkey_keys_held:
            return
        if self.clipboard_only:
            self.copy_pending_transcript()
            return
        self.inserting = True
        piece = (" " if self.output_started else "") + self.pending_parts[0]
        target = self.target

        def insert():
            try:
                message = insert_into_target(piece, target)
            except Exception as exc:
                message = f"Einfügen fehlgeschlagen: {exc}"
            self.insertion_ready.emit(message)

        threading.Thread(target=insert, daemon=True).start()

    def on_inserted(self, message: str) -> None:
        self.inserting = False
        if self.closing:
            return
        if message == "Text eingefügt.":
            self.pending_parts.pop(0)
            self.output_started = True
            if self.state != "error":
                self.state = "recording" if self.engine and self.engine.recording else "processing"
                if self.engine is None and not self.pending_parts and not self.deferred_text:
                    self.state = "idle"
                self.set_status("Bereit" if self.state == "idle" else "Text wird direkt eingefügt")
            self.insert_next()
            self.update()
        else:
            # Keep all uninserted segments together. Repeated paste attempts
            # could otherwise lose text or insert the accumulated text twice.
            self.clipboard_only = True
            self.copy_pending_transcript(message)

    def copy_pending_transcript(self, reason: str = "") -> None:
        QApplication.clipboard().setText(" ".join(self.pending_parts))
        shortcut = "Cmd+V" if platform.system() == "Darwin" else "Strg+V"
        self.set_status(
            (reason + "\n" if reason else "")
            + f"Nicht eingefügter Text wird gesammelt – mit {shortcut} einfügen.",
            error=True,
        )

    def copy_last_transcript(self) -> None:
        if self.inserting:
            self.set_status("Einfügen läuft noch · danach das Diktat kopieren.")
            return
        if self.transcript_parts:
            QApplication.clipboard().setText(" ".join(self.transcript_parts))
            message = "Letztes Diktat kopiert."
        else:
            message = "Noch kein Diktat vorhanden."
        if self.setup_dialog is not None:
            self.setup_dialog.info.setText(message)
        self.set_status(message)

    def on_error(self, message: str) -> None:
        if not self.closing:
            self.set_status("Fehler: " + message, error=True)

    def on_finished(self) -> None:
        if self.closing:
            return
        self.engine = None
        self.starting = False
        self.mic_level = 0.0
        self.push_active = False
        if self.local_session:
            opentalk.LOCAL_WHISPER_SERVER.end_session()
            self.local_session = False
        if self.state != "error":
            self.state = "processing" if self.deferred_text or self.pending_parts else "idle"
            self.set_status(
                "Hotkey loslassen zum Einfügen" if self.deferred_text
                else "Text wird eingefügt …" if self.pending_parts
                else "Bereit" if self.output_started else "Keine Sprache erkannt"
            )
        self.update()

    def pin(self) -> None:
        if not shutil.which("hyprctl"):
            return
        try:
            clients = json.loads(hyprctl("clients", "-j"))
            window = next(
                (
                    item
                    for item in clients
                    if item.get("pid") == os.getpid() and item.get("title") == WINDOW_TITLE
                ),
                None,
            )
            if window is None and self.pin_attempts < 10:
                self.pin_attempts += 1
                QTimer.singleShot(300, self.pin)
            elif window and not window.get("pinned"):
                address = window.get("address", "")
                if ADDRESS.fullmatch(address):
                    hyprctl("dispatch", f'hl.dsp.window.pin({{ window = "address:{address}" }})')
        except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            self.set_status("Anheften fehlgeschlagen", error=True)

    def closeEvent(self, event) -> None:
        self.closing = True
        self.click_timer.stop()
        self.drag_timer.stop()
        self.screen_timer.stop()
        self.model_idle_timer.stop()
        if self.hotkey_listener is not None:
            self.hotkey_listener.stop()
            self.hotkey_listener = None
        if self.engine is not None:
            self.engine.cancel()
        if self.local_session:
            opentalk.LOCAL_WHISPER_SERVER.end_session()
            self.local_session = False
        if (
            self.setup_dialog is not None
            and self.setup_dialog.process.state() != QProcess.ProcessState.NotRunning
        ):
            self.setup_dialog.process.terminate()
            if not self.setup_dialog.process.waitForFinished(3000):
                self.setup_dialog.process.kill()
                self.setup_dialog.process.waitForFinished(1000)
        super().closeEvent(event)
        QApplication.quit()


def acquire_instance_lock() -> QLockFile | None:
    """Acquire the GUI lock, recovering safely from a crashed prior process."""
    lock_path = opentalk.runtime_socket().parent / "opentalk-gui.lock"
    lock = QLockFile(str(lock_path))
    lock.setStaleLockTime(0)
    if lock.tryLock(100):
        return lock
    # A hard kill can leave a lock behind on macOS. QLockFile verifies the
    # recorded process before removing it, so a real running instance stays
    # protected while a stale lock no longer prevents future launches.
    if lock.removeStaleLockFile() and lock.tryLock(100):
        return lock
    return None


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in ("--setup-models", "--download-model", "--setup-engine"):
        import model_setup

        return model_setup.main(sys.argv[1:])
    lock = acquire_instance_lock()
    if lock is None:
        return 0
    app = QApplication(sys.argv)
    app.setApplicationName("OpenTalk")
    # Keep an explicit owner reference for the complete Qt event-loop lifetime.
    app._opentalk_overlay = Overlay()
    opentalk.warm_transcriber_async()
    try:
        return app.exec()
    finally:
        opentalk.LOCAL_WHISPER_SERVER.shutdown()


if __name__ == "__main__":
    sys.exit(main())
