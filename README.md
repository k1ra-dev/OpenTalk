# Sprechschrift

Lokale Spracheingabe für Linux: Hotkey drücken → sprechen → Hotkey erneut drücken → Text im aktiven Textfeld. Die Erkennung läuft mit [whisper.cpp](https://github.com/ggml-org/whisper.cpp) auf dem eigenen Rechner oder optional auf dem eigenen Homeserver. Keine Anmeldung und keine Cloud-API.

**Status: frühe Vorschau.** Die Codepfade wurden mit simulierten Mikrofon- und Eingabeprogrammen getestet; ein echter Test mit Mikrofon, Modell und Wayland steht noch aus. Der Hotkey schaltet die Aufnahme um, er reagiert noch nicht auf Loslassen.

| Teil | Desktop | Homeserver |
| --- | --- | --- |
| Aufnahme | PipeWire `pw-record` | — |
| Erkennung | `whisper-cli` oder eigener Server | `whisper-cli` |
| Eingabe | Hyprland: `wtype`; KDE: `kwtype`; sonst `wl-copy` | — |

## CachyOS / Arch: lokal starten

1. Dieses Projekt nach `~/Programme/sprechschrift` entpacken. In VS Code **Datei → Ordner öffnen** und den Projektordner auswählen.
2. Grundprogramme installieren: `sudo pacman -S --needed python pipewire cmake git base-devel wl-clipboard libnotify`. Für **Hyprland** zusätzlich `sudo pacman -S --needed wtype`. Für **KDE Wayland** [kwtype-git](https://aur.archlinux.org/packages/kwtype-git) mit `paru -S kwtype-git` installieren (AUR-Paket vorher prüfen) oder [KWtype](https://github.com/Sporif/KWtype) selbst bauen. Falls die virtuelle Eingabe fehlschlägt, legt `wl-copy` das Ergebnis in die Zwischenablage.
3. `whisper.cpp` und ein **mehrsprachiges** Modell installieren:

   ```bash
   git clone https://github.com/ggml-org/whisper.cpp.git ~/whisper.cpp
   cd ~/whisper.cpp
   cmake -B build
   cmake --build build -j --config Release
   sh ./models/download-ggml-model.sh small
   ```

   `small` ist ein Start für Deutsch. `base` braucht weniger Speicher; `medium` mehr. Modelle mit `.en` sind nur für Englisch.

4. Im Projekt `config.example.sh` nach `config.local.sh` kopieren und dort bei Bedarf die Pfade ändern. Die persönliche Konfiguration bleibt außerhalb von Git. Dann im Projekt `./scripts/start.sh` starten, sprechen und denselben Befehl nochmals ausführen. Mit `python3 sprechschrift.py status` den Zustand abfragen.
5. Hotkey einrichten:

   - **KDE Plasma:** Systemeinstellungen → Tastenkürzel → Neu hinzufügen → Befehl oder Skript. Den **absoluten Pfad** zu `scripts/start.sh` als Befehl eintragen, etwa `/home/NAME/Programme/sprechschrift/scripts/start.sh`, und z. B. `Meta+Alt+R` wählen.
   - **Hyprland mit `hyprland.conf`:** `bind = SUPER ALT, R, exec, /home/NAME/Programme/sprechschrift/scripts/start.sh` zur vorhandenen Konfiguration hinzufügen.
   - **Hyprland mit `hyprland.lua`:** `hl.bind("SUPER + ALT + R", hl.dsp.exec_cmd("/home/NAME/Programme/sprechschrift/scripts/start.sh"))` zur vorhandenen Konfiguration hinzufügen. Seit Hyprland 0.55 ist Lua die bevorzugte Konfiguration; verwende die Form deiner installierten Version.

Die ersten Erkennungen können dauern, weil `whisper-cli` das Modell momentan **für jede Aufnahme neu lädt**. Eine Aufnahme endet nach spätestens zwei Minuten. Temporäre WAV-Dateien werden anschließend gelöscht. Bei Nutzung der Zwischenablage ersetzt das Ergebnis ihren bisherigen Inhalt und kann im Verlauf bleiben.

## Optional: Erkennung auf dem Homeserver

Auf dem Server Python sowie `whisper.cpp` und ein mehrsprachiges Modell wie oben installieren. Ein Token erzeugen und den Dienst starten:

```bash
export SPRECHSCHRIFT_MODEL="$HOME/whisper.cpp/models/ggml-small.bin"
export SPRECHSCHRIFT_WHISPER_CLI="$HOME/whisper.cpp/build/bin/whisper-cli"
export SPRECHSCHRIFT_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python3 sprechschrift.py serve --host 127.0.0.1 --port 8765
```

Für Tailscale `--host` auf die **Tailscale-IP des Servers** setzen. Auf dem Desktop in `config.local.sh` zusätzlich `SPRECHSCHRIFT_SERVER_URL=http://TAILSCALE-IP:8765` und dasselbe `SPRECHSCHRIFT_TOKEN` exportieren. `chmod 600 config.local.sh` schützt es vor anderen lokalen Benutzern. Nach Konfigurationsänderungen den laufenden Desktop-Dienst beenden und neu starten.

Im Servermodus wird die WAV-Aufnahme an **deinen** Server geschickt. HTTP selbst verschlüsselt nicht: nur über Tailscale oder eine gesicherte HTTPS-Verbindung verwenden, nicht direkt ins öffentliche Internet stellen. Der Server prüft das Token und verarbeitet Anfragen nacheinander.

## Konfiguration und Diagnose

| Variable | Zweck |
| --- | --- |
| `SPRECHSCHRIFT_MODEL` | Pfad zu `ggml-*.bin` auf dem Erkennungsrechner |
| `SPRECHSCHRIFT_WHISPER_CLI` | Pfad zu `whisper-cli` oder Name im `PATH` |
| `SPRECHSCHRIFT_LANGUAGE` | `de` (Standard) oder `auto` |
| `SPRECHSCHRIFT_INSERT` | `auto`, `wtype`, `kwtype`, `clipboard`, `stdout` |
| `SPRECHSCHRIFT_SERVER_URL` | URL des optionalen eigenen Servers |
| `SPRECHSCHRIFT_TOKEN` | Gemeinsames Token mit mindestens 24 Zeichen |

Einfügen einzeln testen: Unter Hyprland `printf 'Test äöü' | wtype -`, unter KDE `kwtype 'Test äöü'` im fokussierten Textfeld. Im Terminal braucht man für manuelles Einfügen meist `Strg+Shift+V`. Wenn der Dienst nicht startet, `python3 sprechschrift.py daemon` im Terminal starten, um Fehler zu sehen.

## Entwickeln und mitmachen

VS Code hat vorbereitete Tasks, Debug-Konfigurationen und eine Python-Erweiterungsempfehlung. Der Debugger verwendet die oben angegebenen Standardpfade; für den Server-Debugger muss `SPRECHSCHRIFT_TOKEN` in der Umgebung von VS Code gesetzt sein. Tests ohne Editor: `python3 -m unittest discover -s . -p 'test_*.py' -v`. Hinweise für Beiträge und bekannte Grenzen stehen in [CONTRIBUTING.md](CONTRIBUTING.md). Lizenz dieses Codes: [MIT](LICENSE). Drittprogramme und Modelle haben eigene Lizenzen.
