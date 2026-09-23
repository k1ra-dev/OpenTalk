# OpenTalk

Lokale Spracheingabe für Linux: Hotkey drücken → sprechen → Hotkey erneut drücken → Text im aktiven Textfeld. Die Erkennung läuft mit [whisper.cpp](https://github.com/ggml-org/whisper.cpp) auf dem eigenen Rechner oder optional auf dem eigenen Homeserver. Keine Anmeldung und keine Cloud-API.

**Status: frühe Vorschau.** Der Hotkey schaltet die Aufnahme um, er reagiert noch nicht auf Loslassen.

| Teil | Desktop | Homeserver |
| --- | --- | --- |
| Aufnahme | PipeWire `pw-record` | — |
| Erkennung | `whisper-cli` oder eigener Server | `whisper-cli` |
| Eingabe | Hyprland: `wtype`; KDE: `kwtype`; sonst `wl-copy` | — |

## CachyOS / Arch: lokal starten

1. Dieses Projekt nach `~/Programme/opentalk` entpacken. In VS Code **Datei → Ordner öffnen** und den Projektordner auswählen.
2. Grundprogramme installieren: `sudo pacman -S --needed python python-pyqt6 pipewire libpulse git base-devel pkgconf layer-shell-qt wl-clipboard libnotify`. Für **Hyprland** kann OpenTalk den kopierten Text direkt ins zuletzt aktive Fenster einfügen. Optional `sudo pacman -S --needed wtype`. Für **KDE Wayland** [kwtype-git](https://aur.archlinux.org/packages/kwtype-git) mit `paru -S kwtype-git` installieren (AUR-Paket vorher prüfen) oder [KWtype](https://github.com/Sporif/KWtype) selbst bauen.
3. `./scripts/gui.sh` starten. Ein **Doppelklick** auf den schwebenden Kreis öffnet die Kreise für Mikrofon, Einrichtung und Schließen. Falls die Spracherkennung fehlt, über **⚙ → Jetzt einrichten** `whisper.cpp`, ein mehrsprachiges `small`-Modell und ein kleines Modell zur Spracherkennung im Benutzerordner installieren. Dafür werden etwa 466 MiB für das Hauptmodell heruntergeladen und `whisper-cli` lokal gebaut. Fehlt CMake, lädt die Einrichtung eine geprüfte portable Kopie (Linux x86_64) in den Benutzerordner. Alternativ eigene Pfade in `config.local.sh` setzen. Manuelle Installation:

   ```bash
   git clone https://github.com/ggml-org/whisper.cpp.git ~/whisper.cpp
   cd ~/whisper.cpp
   cmake -B build
   cmake --build build -j --config Release
   sh ./models/download-ggml-model.sh small
   ```

   Für die manuelle Installation die Pfade zu `ggml-small.bin` und `whisper-cli` in `config.local.sh` setzen. `small` ist ein Start für Deutsch. `base` braucht weniger Speicher; `medium` mehr. Modelle mit `.en` sind nur für Englisch.

4. Für den Hotkey bei Bedarf `config.example.sh` nach `config.local.sh` kopieren. Die persönliche Konfiguration bleibt außerhalb von Git. Dann im Projekt `./scripts/start.sh` starten, sprechen und denselben Befehl nochmals ausführen. Mit `python3 opentalk.py status` den Zustand abfragen.
5. Hotkey einrichten:

   - **KDE Plasma:** Systemeinstellungen → Tastenkürzel → Neu hinzufügen → Befehl oder Skript. Den **absoluten Pfad** zu `scripts/start.sh` als Befehl eintragen, etwa `/home/NAME/Programme/opentalk/scripts/start.sh`, und z. B. `Meta+Alt+R` wählen.
   - **Hyprland mit `hyprland.conf`:** `bind = SUPER ALT, R, exec, /home/NAME/Programme/opentalk/scripts/start.sh` zur vorhandenen Konfiguration hinzufügen.
   - **Hyprland mit `hyprland.lua`:** `hl.bind("SUPER + ALT + R", hl.dsp.exec_cmd("/home/NAME/Programme/opentalk/scripts/start.sh"))` zur vorhandenen Konfiguration hinzufügen. Seit Hyprland 0.55 ist Lua die bevorzugte Konfiguration; verwende die Form deiner installierten Version.

### Als Anwendung im App-Menü installieren

Im Projektordner `./scripts/install-desktop.sh` ausführen. Danach im App-Menü **OpenTalk** suchen und anklicken. Das Skript kopiert Programm und Symbol nach `~/.local/share` und legt `~/.local/share/applications/opentalk.desktop` an. Nach Änderungen am Projekt das Installationsskript erneut ausführen, damit die installierte Version aktualisiert wird. Das Sprachmodell und die gespeicherte Mikrofonwahl bleiben dabei erhalten.

### Schwebende Oberfläche

`./scripts/gui.sh` startet einen kleinen schwebenden Kreis. **Ein Klick** startet die Aufnahme; der nächste Klick stoppt sie. Während der Aufnahme werden ungefähr alle vier Sekunden fertige Sprachabschnitte erkannt und automatisch in das zuvor fokussierte Textfeld eingefügt. Nach dem Stoppen wird der letzte Abschnitt verarbeitet. Der Kreis bleibt ohne Tastaturfokus auch über Vollbildfenstern sichtbar. **Doppelklick** öffnet drei weitere Kreise: Mikrofonwahl, Einrichtung und Schließen. Ein weiterer Doppelklick verbirgt sie. Den Hauptkreis mit gedrückter linker Maustaste ziehen, um ihn zu verschieben; die Position bleibt gespeichert. Die Mikrofonwahl gilt auch für spätere Starts und den Hotkey. Unter Hyprland erfolgt das direkte Einfügen bei fehlendem `wtype` technisch über die Zwischenablage und einen gezielten Einfügebefehl. Reine Musikmarkierungen wie `[MUSIK]` werden verworfen. Die Ersteinrichtung braucht eine Internetverbindung; die Erkennung danach läuft lokal.

Über **Doppelklick → ⚙** lässt sich die Stärke des lokalen Whisper-Modells mit einem Regler zwischen **tiny, base, small, medium und large-v3** wählen. Vorhandene Modelle werden sofort aktiviert; fehlende Modelle können im selben Fenster heruntergeladen werden. Die Datei wird vor der Aktivierung geprüft. Der Download reicht von 75 MiB (`tiny`) bis 2,9 GiB (`large-v3`); größere Modelle brauchen mehr Zeit pro Sprachabschnitt. Ein in `config.local.sh` gesetzter Modellpfad oder ein eigener Homeserver bestimmt das Modell unabhängig vom Regler.

Die Erkennung kann je Abschnitt etwas dauern, weil `whisper-cli` das Modell momentan **für jeden Abschnitt neu lädt**. Eine Aufnahme endet nach spätestens zwei Minuten. Temporäre Audiodateien werden anschließend gelöscht. Bei Nutzung der Zwischenablage ersetzt jeder Abschnitt ihren bisherigen Inhalt und kann im Verlauf bleiben.

## Optional: Erkennung auf dem Homeserver

Auf dem Server Python sowie `whisper.cpp` und ein mehrsprachiges Modell wie oben installieren. Ein Token erzeugen und den Dienst starten:

```bash
export OPENTALK_MODEL="$HOME/whisper.cpp/models/ggml-small.bin"
export OPENTALK_WHISPER_CLI="$HOME/whisper.cpp/build/bin/whisper-cli"
export OPENTALK_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python3 opentalk.py serve --host 127.0.0.1 --port 8765
```

Für Tailscale `--host` auf die **Tailscale-IP des Servers** setzen. Auf dem Desktop in `config.local.sh` zusätzlich `OPENTALK_SERVER_URL=http://TAILSCALE-IP:8765` und dasselbe `OPENTALK_TOKEN` exportieren. `chmod 600 config.local.sh` schützt es vor anderen lokalen Benutzern. Nach Konfigurationsänderungen den laufenden Desktop-Dienst beenden und neu starten.

Im Servermodus wird die WAV-Aufnahme an **deinen** Server geschickt. HTTP selbst verschlüsselt nicht: nur über Tailscale oder eine gesicherte HTTPS-Verbindung verwenden, nicht direkt ins öffentliche Internet stellen. Der Server prüft das Token und verarbeitet Anfragen nacheinander.

## Konfiguration und Diagnose

| Variable | Zweck |
| --- | --- |
| `OPENTALK_MODEL` | Pfad zu `ggml-*.bin` auf dem Erkennungsrechner |
| `OPENTALK_WHISPER_CLI` | Pfad zu `whisper-cli` oder Name im `PATH` |
| `OPENTALK_VAD_MODEL` | Optionaler Pfad zum Silero-Modell für Sprachabschnitte |
| `OPENTALK_LANGUAGE` | `de` (Standard) oder `auto` |
| `OPENTALK_INSERT` | `auto`, `wtype`, `kwtype`, `clipboard`, `stdout` |
| `OPENTALK_SOURCE` | Optionaler PipeWire-Quellname; sonst gilt die Auswahl in der Oberfläche |
| `OPENTALK_SERVER_URL` | URL des optionalen eigenen Servers |
| `OPENTALK_TOKEN` | Gemeinsames Token mit mindestens 24 Zeichen |

Einfügen einzeln testen: Unter Hyprland `printf 'Test äöü' | wtype -`, unter KDE `kwtype 'Test äöü'` im fokussierten Textfeld. Im Terminal braucht man für manuelles Einfügen meist `Strg+Shift+V`. Wenn der Dienst nicht startet, `python3 opentalk.py daemon` im Terminal starten, um Fehler zu sehen.

## Entwickeln und mitmachen

VS Code hat vorbereitete Tasks, Debug-Konfigurationen und eine Python-Erweiterungsempfehlung. Der Debugger verwendet die oben angegebenen Standardpfade; für den Server-Debugger muss `OPENTALK_TOKEN` in der Umgebung von VS Code gesetzt sein. Tests ohne Editor: `python3 -m unittest discover -s . -p 'test_*.py' -v`. Hinweise für Beiträge und bekannte Grenzen stehen in [CONTRIBUTING.md](CONTRIBUTING.md). Lizenz dieses Codes: [MIT](LICENSE). Drittprogramme und Modelle haben eigene Lizenzen.
