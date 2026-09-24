# Mitmachen

Dieses Projekt ist eine frühe Vorschau. Bitte beschreibe bei Fehlern das Betriebssystem, die Desktop-Umgebung, die Einfügemethode, Schritte zum Nachstellen und die beobachtete Ausgabe. Keine Aufnahmen, Tokens oder privaten Transkripte in öffentliche Issues hochladen.

1. Repository forken und für die Änderung einen Branch erstellen.
2. `python3 -m unittest discover -s . -p 'test_*.py' -v` ausführen.
3. Änderungen an Aufnahme oder Desktop-Eingabe auch auf einem echten Linux-Desktop bzw. einem
   Apple-Silicon-Mac prüfen; simulierte Tests ersetzen diese Prüfung nicht. Intel-Macs gehören
   ausdrücklich nicht zum unterstützten Zielsystem.
4. Pull Request mit kurzer Beschreibung und Testschritten stellen.

Bekannte Aufgaben: vollständiger Diktat-Test auf Hyprland und KDE Wayland; Hotkey mit Gedrückthalten; schnellere Erkennung mit dauerhaft geladenem Modell; Installation ohne Terminal; bessere Fehleranzeige; andere Betriebssysteme.
