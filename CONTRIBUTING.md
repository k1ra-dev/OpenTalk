# Mitmachen

Dieses Projekt ist eine frühe Vorschau. Bitte beschreibe bei Fehlern das Betriebssystem, die Desktop-Umgebung, die Einfügemethode, Schritte zum Nachstellen und die beobachtete Ausgabe. Keine Aufnahmen, Tokens oder privaten Transkripte in öffentliche Issues hochladen.

1. Repository forken und für die Änderung einen Branch erstellen.
   Python 3.10+ verwenden und `requirements-dev.txt` in einer virtuellen Umgebung installieren.
2. **Jede Verhaltensänderung braucht passende Tests.** Vorhandene Tests müssen angepasst und
   neue Fehlerfälle als Regressionstest ergänzt werden. Falls eine Änderung nachweislich keinen
   automatisierbaren Test zulässt, muss der Pull Request begründen, warum, und die manuelle
   Prüfung dokumentieren.
3. `python3 -m ruff check .` und danach
   `python3 -m unittest discover -s . -p 'test_*.py' -v` ausführen.
4. Änderungen an Aufnahme oder Desktop-Eingabe auch auf einem echten Linux-Desktop, einem
   Apple-Silicon-Mac beziehungsweise Windows prüfen; simulierte Tests ersetzen diese Prüfung
   nicht. Intel-Macs gehören ausdrücklich nicht zum unterstützten Zielsystem.
5. Pull Request mit kurzer Beschreibung, Teständerungen und manuellen Testschritten stellen.

## Testbereiche

- `tests/test_model_recommendation.py`: native Hardware-Abfragen, Ressourcen-Grenzen,
  Speicherdruck, fehlende Daten und konservative Modellempfehlungen

- `tests/test_new_tools.py`: Wörterbuch-Hinweise, nicht-invasive Systemprüfung und Benchmark-Auswertung
- Erkennungsänderungen zusätzlich mit dem lokalen Vergleich in `benchmarks/README.md` prüfen;
  simulierte CI-Ergebnisse sind kein Nachweis tatsächlicher Spracherkennungsqualität.

- `tests/test_core.py`: Audio-Validierung sowie lokale und Server-Transkription
- `tests/test_live_dictation.py`: Aufnahme-Lebenszyklus, Chunking, Abbruch und Fehlerfälle
- `tests/test_audio_processing.py`: verlustfreie Pausenschnitte, Pegel und leise Schlusswörter
- `tests/test_hotkeys.py`: Drücken/Loslassen, Tastenwiederholung und mehrere Modifikatortasten
- `tests/test_platforms.py`: Linux-, macOS- und Windows-Pfade, Recorder, Eingabe und Mikrofone
- `tests/test_gui.py`: Hotkeys, Einstellungen, Fensterflags und Einzelinstanz-Sperre
- `tests/test_model_setup.py`: sichere, atomare und prüfsummenvalidierte Modelldownloads
- `tests/test_checkout.py`: sauberer Checkout, Leerzeichen in Pfaden, Starter und Shell-Syntax
- `tests/test_source_launcher.py`: aktueller Entwickler-Code, Shell-Konfiguration und Zugriffsfehler
- `tests/test_windows_clipboard.py`: Clipboard-Besitz, Unicode und Freigabe bei Fehlern
- `tests/test_opentalk.py`: Ende-zu-Ende-nahe Pipeline- und HTTP-Integrationstests

GitHub Actions führt die vollständige Suite und den Paket-Build auf echten Linux-,
Apple-Silicon-macOS- und Windows-Runnern aus. Ein grüner Lauf ist Voraussetzung zum Mergen.

Änderungen an Abhängigkeiten oder Modulen immer auch mit `requirements*.txt`, den Installern,
dem PyInstaller-Spec und beiden CI-Workflows abgleichen. Ein sauberer Checkout darf keine
vorhandenen Modelle, Build-Artefakte, Entwicklerpfade oder persönliche Konfiguration voraussetzen.
POSIX-Shell-Syntax wird lokal geprüft, PowerShell-Syntax auf dem Windows-Runner; der zusätzliche
Linux-Testjob prüft die minimale Python-Version 3.10.

Bekannte Aufgaben: vollständige manuelle Diktat-Tests auf Hyprland, KDE Wayland und Windows;
Vergleichstests für verschiedene
Mikrofone, Dialekte und Hintergrundgeräusche. Push-to-talk, Pegelanzeige, Pausenschnitte,
plattformübergreifender Schnellmodus mit Ruhefunktion und fertige App-Pakete sind implementiert.
