# Lokale Erkennungsvergleiche

Hier werden **keine privaten Aufnahmen mitgeliefert oder hochgeladen**. Lege eigene,
gleichbleibende Testaufnahmen und ihr exakt gesprochenes Transkript in `benchmarks/local/` ab
(gitignoriert). WAV: PCM, 16 kHz, Mono, 16 Bit, 0,1–120 Sekunden pro Datei.
Sinnvolle Fälle: kurze Sätze, Fachbegriffe/Namen, Zahlen, leise Sprache und Hintergrundgeräusche.

`benchmarks/local/cases.json` beispielsweise:

```json
[
  {"audio": "kurz.wav", "text": "Heute teste ich die lokale Spracherkennung."},
  {"audio": "namen.wav", "text": "Kira arbeitet mit OpenTalk und PipeWire."}
]
```

Mit dem Python-Interpreter deiner OpenTalk-Umgebung:

```sh
python benchmark.py benchmarks/local/cases.json > benchmarks/local/baseline.json
python benchmark.py benchmarks/local/cases.json --baseline benchmarks/local/baseline.json > benchmarks/local/current.json
```

Der Bericht enthält **keine Transkripte**, sondern Fehlerzahlen, Laufzeiten und einen
Korpus-Fingerabdruck. WER zählt Einfügungen, Löschungen und Ersetzungen; Groß-/Kleinschreibung
und Satzzeichen werden ignoriert. Gesamt-WER wird nach Referenzwortzahl gewichtet.
RTF = Erkennungszeit / Audiolänge; kleiner ist schneller. Der erste Fall enthält den Modellstart
(inklusive möglicher Shader-Kompilierung). Das ist **kein** Mikrofon-/Einfüge-Latenztest.

Für belastbare Vergleiche denselben Rechner, dieselben Einstellungen und ähnliche Systemlast
nutzen, Shader-Cache-Zustand beachten und mehrere komplette Läufe durchführen.
Die Grenzwerte sind standardmäßig +0,02 absolute WER und Faktor 1,2 Laufzeit; anpassbar mit
`--max-wer-increase` / `--max-slowdown`. Ein überschrittener Grenzwert liefert Exitcode 1,
ungültige Eingaben Exitcode 2. Nur derselbe Korpus ist vergleichbar.

Die Erkennung läuft immer lokal, auch wenn ein Homeserver konfiguriert ist. Das lokale Modell
muss bereits eingerichtet sein. Kein Modelldownload, keine Texteingabe, kein Mikrofonzugriff.
Die normalen CI-Tests prüfen die Auswertung mit simulierten Ergebnissen, nicht die tatsächliche
Erkennungsgenauigkeit. Dafür sind diese expliziten Läufe mit echten Aufnahmen erforderlich.

## CPU-Threads vergleichen

Für jede Variante einen eigenen Prozess starten; `--threads` gilt nur für diesen Lauf
und ändert keine App-Einstellungen. `--warmup` erkennt die erste Aufnahme einmal vorab,
ohne diesen Vorlauf zu werten. Dadurch lässt sich die laufende Erkennung ohne Modellstart
vergleichen (beim CLI-Fallback bleibt das Laden pro Aufnahme weiterhin enthalten).

```sh
python benchmark.py benchmarks/local/cases.json --threads 4 --warmup
python benchmark.py benchmarks/local/cases.json --threads 6 --warmup
python benchmark.py benchmarks/local/cases.json --threads 8 --warmup
```

Mehrfach und mit wechselnder Reihenfolge testen; nicht parallel ausführen. Kleinere RTF
bei gleicher Wortfehlerrate ist besser. Warm- und Kaltläufe nicht miteinander vergleichen.
Mehr Threads sind nicht automatisch schneller, insbesondere bei GPU-Beschleunigung.
