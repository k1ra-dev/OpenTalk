# OpenTalk

<p align="center">
  <em>Local voice dictation for Linux, Windows, and Apple Silicon Macs.</em>
</p>

**OpenTalk** turns your voice into text **100% locally** using [whisper.cpp](https://github.com/ggml-org/whisper.cpp). No cloud APIs, no accounts, no telemetry — your voice never leaves your machine (unless *you* choose your own home server as the recognition backend).

```
Hotkey / Click → Speak → Stop → Text lands in the focused window ✨
```

## Highlights

- 🖥️ **Floating overlay bubble** — draggable, stays on top where the desktop permits, no keyboard focus stealing
- ⚡ **Pause-aware live dictation** — recognises phrases at short pauses, with a bounded fallback for continuous speech
- 🚀 **Persistent local recognition** — keeps Whisper loaded between segments on all platforms; Metal acceleration on Apple Silicon
- 🎚️ **Model switcher in the GUI** — tiny, base, small, medium, large-v3 (75 MiB – 2.9 GiB), with checksum-verified downloads
- 🎙️ **Microphone picker** — choose a PipeWire, macOS, or Windows input in the UI
- 🟢 **Live microphone level** — a small ring on the recording bubble, with missing-signal and permission hints
- 🧠 **VAD segmentation** — optional Silero voice-activity detection splits speech cleanly
- 🔒 **Privacy first** — recognition runs locally on whisper.cpp; optional self-hosted server mode with token auth
- ⌨️ **Native text insertion** — Wayland tools, macOS Cmd+V, or Windows Ctrl+V
- 📋 **Recover your text** — Settings → **Letztes Diktat kopieren** copies the full latest dictation; failed insertion collects uninserted segments on the clipboard
- 🧩 **Desktop integration** — install as an app, bind a global hotkey, drag & reposition the bubble
- 🏠 **Optional home-server mode** — offload recognition to your own server (great for laptops / ARM)

## How it works

| Part | Desktop | Home server |
| --- | --- | --- |
| Recording | Linux: PipeWire · macOS: AVFoundation · Windows: DirectShow | — |
| Recognition | Persistent `whisper-server`, CLI fallback, or your server | Local Whisper backend |
| Text insertion | Linux: `wtype`/`kwtype` · macOS: Cmd+V · Windows: Ctrl+V | — |

## Installation

Linux, macOS, and Windows receive separate packages. The macOS build is limited to
**Apple Silicon (M1, M2, M3, M4 and newer M processors), macOS 13.3+**; Intel Macs are not supported.
Windows packages target Windows 10/11 x86_64. Linux packages are built on Ubuntu 24.04;
older distributions may need a source build because of their system-library versions.

### Ready-to-run downloads (no Git clone)

- **[Download for macOS — Apple Silicon only](https://github.com/k1ra-dev/OpenTalk/releases/latest/download/OpenTalk-macOS-arm64.zip)**
- **[Download for Linux — x86_64](https://github.com/k1ra-dev/OpenTalk/releases/latest/download/OpenTalk-Linux-x86_64.tar.gz)**
- **[Download for Windows — x86_64](https://github.com/k1ra-dev/OpenTalk/releases/latest/download/OpenTalk-Windows-x86_64.zip)**

Extract the matching download and launch `OpenTalk.app` on macOS or `OpenTalk`/`OpenTalk.exe`
inside the Linux/Windows folder. The packages already contain Python, PyQt, `whisper-cli`, `whisper-server`,
and FFmpeg where needed. On first launch, use **double-click → ⚙ → Set up now** to download
the speech model. macOS may require right-clicking the unsigned app and choosing **Open** the
first time.

The source installation below remains available for development.

### Global hotkey

OpenTalk assigns a default shortcut for each platform (permissions and desktop support are required):

| System | Default hotkey |
| --- | --- |
| macOS | `Cmd+Shift+Space` |
| Windows | `Ctrl+Alt+R` |
| Linux | `Ctrl+Alt+R` |

Double-click the bubble and change the shortcut directly in **Settings → Global hotkey**.
Enable **Zum Sprechen Hotkey gedrückt halten** for push-to-talk: press the shortcut to start,
release a shortcut key to stop. Text is inserted after all shortcut keys are released, avoiding
accidental modified paste commands. The default remains press-to-start / press-to-stop;
clicking the bubble always works as a toggle. Push-to-talk needs the app's global keyboard
listener; an external Wayland command shortcut alone only supports toggle mode.
macOS requires Accessibility permission for global shortcuts. On some Wayland compositors,
global shortcut registration is restricted by the desktop; the existing KDE/Hyprland system
shortcut remains the fallback.

### Get the project

```bash
git clone https://github.com/k1ra-dev/OpenTalk.git ~/Programme/opentalk
cd ~/Programme/opentalk
```

### Linux (Arch / CachyOS)

Install the Linux dependencies:

```bash
sudo pacman -S --needed python python-pyqt6 pipewire libpulse git base-devel pkgconf \
    cmake python-pip layer-shell-qt wl-clipboard libnotify
python -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r requirements.txt
```

For other distributions, use Python **3.10+**, PyQt **6.5+**, Git, CMake, a C++ compiler,
PipeWire's `pw-record`, PulseAudio's `pactl`, and `wl-clipboard`. A source environment can be
created with `python3 -m venv .venv` followed by `.venv/bin/python -m pip install -r requirements.txt`.
The launchers automatically select `.venv/bin/python`. Layer-shell additionally needs the
distribution's Qt6/LayerShellQt development libraries matching the running Qt version; the
regular overlay is the fallback. The bridge cache is stored in the writable user-data directory.
Global hotkeys and automatic insertion remain compositor-dependent on Wayland.

Optional but recommended:

- **Hyprland:** `sudo pacman -S --needed wtype` (direct insertion into the last-active window)
- **KDE Wayland:** [kwtype-git](https://aur.archlinux.org/packages/kwtype-git) via `paru -S kwtype-git` (review the AUR package before installing)

Install the Linux desktop version:

```bash
./scripts/install-linux.sh
```

This adds **OpenTalk** to the app menu (`~/.local/share`). Re-run the installer after code
changes; your selected model and microphone are kept.

Or run it directly from the checkout:

```bash
./scripts/gui.sh
```

A floating circle appears. **Click** it to start/stop dictation, **double-click** to open the
menu (microphone picker, setup ⚙, close).

### macOS (M processors only, no Intel)

The Mac version requires [Homebrew](https://brew.sh/) and an `arm64` terminal. Install
Homebrew first, then run:

```bash
brew install python cmake ffmpeg git
./scripts/install-macos.sh
open "$HOME/Applications/OpenTalk.app"
```

The installer stops with an explicit error on Intel Macs. On first launch, allow microphone
access. For automatic insertion into the previously active text field, also enable OpenTalk
under **System Settings → Privacy & Security → Accessibility**. Without that permission, the
recognized text remains on the clipboard and can be inserted with `Cmd+V`.
For source installations macOS may list the process as **Python**. Allow that entry when
OpenTalk reports missing Accessibility permission.

The default source installer copies the Python files; run it again after code changes.
For development, install the app launcher **once with `--dev`**:

```bash
./scripts/install-macos.sh --dev
open "$HOME/Applications/OpenTalk.app"
```

This launcher reads the current Python files and `config.local.sh` directly from this checkout.
After edits, quit OpenTalk completely and open it again; moving the checkout requires running
the installer again. Alternatively, quit the running app and launch from the terminal:

```bash
OPENTALK_PYTHON="$HOME/Library/Application Support/OpenTalk/venv/bin/python" ./scripts/gui.sh
```

Restart this command after editing code. Python source changes are not hot-reloaded into a
running process.

If the developer checkout is in Desktop, Documents or Downloads, Finder launches additionally
need permission to read that protected folder. Allow OpenTalk/Python under **Privacy & Security
→ Files and Folders**, or keep the checkout in an unprotected development directory such as
`~/Developer/OpenTalk` and rerun the developer installer. The app displays a startup error if
macOS denies access; it never silently switches to an older copied version of your code.

### Windows (x86_64, source checkout)

Install **Python 3.10+ (64-bit, added to PATH)** and Git. For building the recognition engine,
also install CMake (added to PATH) and Visual Studio Build Tools with **Desktop development
with C++**, including the Windows SDK. Open a new PowerShell after installing the tools:

```powershell
git clone https://github.com/k1ra-dev/OpenTalk.git
cd OpenTalk
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-windows.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\gui.ps1
```

The installer creates a local `.venv` and a Start-menu shortcut pointing to this checkout.
FFmpeg is supplied by `imageio-ffmpeg`; no separate FFmpeg installation is required.
Use **Settings → Set up now** to build both recognition helpers and download the models.
Allow microphone access for desktop apps in Windows privacy settings. Automatic input into
an elevated/admin application may be blocked by Windows; use manual paste in that case.
After updating code, restart OpenTalk; rerun the installer when dependencies change.
Optional overrides belong in `config.local.ps1` (see `config.example.ps1`).

### One-time speech-model setup

If speech recognition is missing, go to **double-click → ⚙ → Set up now**. This installs
`whisper.cpp`, a multilingual `small` model, and a small VAD model into your user directory
(~466 MiB for `small`, plus the VAD model). Source installations need Git, CMake and a C++
toolchain; ready-to-run packages only download models. New source setups build the pinned
whisper.cpp version `v1.9.4`. Existing manually maintained source checkouts are reused,
never reset or overwritten. Models and build sources live outside the OpenTalk checkout.

<details>
<summary>Manual whisper.cpp installation (alternative)</summary>

```bash
git clone https://github.com/ggml-org/whisper.cpp.git ~/whisper.cpp
cd ~/whisper.cpp
cmake -B build
cmake --build build -j --config Release
sh ./models/download-ggml-model.sh small
```

Then point `config.local.sh` to your `ggml-small.bin` and `whisper-cli` paths.
`small` is a solid start for German; `base` uses less memory, `medium` more.
Models ending in `.en` are English-only.
</details>

### Linux global hotkey (optional)

- **KDE Plasma:** System Settings → Shortcuts → Add New → Command or Script → absolute path
  to `scripts/start.sh`, e.g. `Meta+Alt+R`
- **Hyprland (`hyprland.conf`):**
  `bind = SUPER ALT, R, exec, /home/NAME/Programme/opentalk/scripts/start.sh`
- **Hyprland (`hyprland.lua`, Hyprland ≥ 0.55):**
  `hl.bind("SUPER + ALT + R", hl.dsp.exec_cmd("/home/NAME/Programme/opentalk/scripts/start.sh"))`

## Using OpenTalk

### Hotkey mode (toggle)

Run `./scripts/start.sh` (or your hotkey), speak, run it again. Check state with
`python3 opentalk.py status`.

### Floating bubble

| Action | Result |
| --- | --- |
| **Click** | Start / stop recording |
| **Double-click** | Show/hide menu bubbles (mic, setup, close) |
| **Drag** | Move the bubble (position is saved) |

While recording, the bubble's green ring shows the microphone level. Capture and metering
continue independently of recognition. If no audio arrives, OpenTalk reports a microphone or
permission problem; a silent input produces a hint without discarding quiet speech.

Phrases are preferably sent for recognition after about 360 ms of quiet, once at least 1.2 s
of audio has accumulated. Continuous speech is capped at 5 s on macOS and 6 s elsewhere,
plus recognition time. This lightweight energy check only chooses cuts: it does not remove
quiet words, run an extra neural model, or upload audio. A hard-limit cut can still split a word.
Only entirely zero-valued audio skips recognition; short final speech is padded, not dropped.
FFmpeg writes packets immediately so its output buffer does not delay live processing.
Pure music markers like `[MUSIC]` are discarded. Recording auto-ends after 2 minutes;
temporary audio files are deleted afterwards.

If automatic insertion fails, all subsequent uninserted segments are collected together on the
clipboard for manual paste after stopping. **Settings → Letztes Diktat kopieren** recovers the
complete latest dictation, including segments already inserted. This recovery text is held only
in memory until the next recording starts or the app closes; it is not saved as a transcript file.
On Windows, the automatic microphone choice uses the first detected DirectShow input; select a
specific microphone in the picker if needed.

### Choosing a model

Double-click the bubble → ⚙: slide between **tiny → large-v3**. Installed models activate
instantly; missing ones can be downloaded in the same window (checksum-verified before use).
A model path set in `config.local.sh` or a home server overrides the slider.

| Model | Size | Notes |
| --- | --- | --- |
| `tiny` | 75 MiB | Fastest, lowest accuracy |
| `base` | 142 MiB | Light |
| `small` | 466 MiB | **Default** — good German start |
| `medium` | 1.5 GiB | Better, slower |
| `large-v3` | 2.9 GiB | Best, slowest |

On every supported platform, `whisper-server` keeps the model loaded between segments. This trades
resident memory for lower latency. If the fast path fails, OpenTalk retries with `whisper-cli`.
After a server failure, retries pause for 30 seconds while the CLI remains available. Local
audio requests bypass system HTTP proxies. Home-server mode does not preload a local model.
The setting **Modell nach 5 Minuten Pause aus dem Speicher laden** is enabled by default.
It releases the model after roughly 5–6 idle minutes, never during a recording or pending
recognition. Starting another recording preloads it again while audio is captured. Disable this
setting to keep the model warm for the lowest startup latency. No model or decoder-quality
settings are reduced by the sleep mode.

## Optional: home-server recognition

Offload transcription to your own server (useful for laptops or weaker devices).

**On the server:**

```bash
export OPENTALK_MODEL="$HOME/whisper.cpp/models/ggml-small.bin"
export OPENTALK_WHISPER_CLI="$HOME/whisper.cpp/build/bin/whisper-cli"
export OPENTALK_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python3 opentalk.py serve --host 127.0.0.1 --port 8765
```

For Tailscale, set `--host` to your server's **Tailscale IP**. On the desktop, add
`OPENTALK_SERVER_URL` and the same `OPENTALK_TOKEN` to `config.local.sh`
(`chmod 600 config.local.sh` protects it from other local users).

> **Security note:** HTTP does not encrypt. Use Tailscale or a secured HTTPS connection —
> do not expose the server to the public internet. The server verifies the token and
> processes requests sequentially.

## Configuration reference

| Variable | Purpose |
| --- | --- |
| `OPENTALK_MODEL` | Path to a `ggml-*.bin` model on the recognition machine |
| `OPENTALK_WHISPER_CLI` | Path to `whisper-cli` (or name in `PATH`) |
| `OPENTALK_WHISPER_SERVER` | Path to persistent `whisper-server`; an empty value disables the fast path |
| `OPENTALK_WHISPER_THREADS` | Recognition threads, default `4`; more is not always faster |
| `OPENTALK_PYTHON` | Interpreter override for source launchers |
| `OPENTALK_VAD_MODEL` | Optional path to the Silero VAD model |
| `OPENTALK_LANGUAGE` | `de` (default) or `auto` |
| `OPENTALK_INSERT` | `auto`, `wtype`, `kwtype`, `clipboard`, `stdout` |
| `OPENTALK_SOURCE` | PipeWire name, AVFoundation index, or Windows DirectShow device name |
| `OPENTALK_FFMPEG` | Optional custom FFmpeg path on macOS or Windows |
| `OPENTALK_CHUNK_SECONDS` | Segment target (1–10 s), default 3 s on macOS / 4 s elsewhere; pauses can finish earlier, continuous speech gets up to 2 s extra |
| `OPENTALK_SERVER_URL` | URL of your optional home server |
| `OPENTALK_TOKEN` | Shared token, minimum 24 characters |

Personal overrides live in `config.local.sh` (Linux/macOS; gitignored, `chmod 600`) or
`config.local.ps1` (Windows). Templates: `config.example.sh` / `config.example.ps1`.
These files are loaded by the source launchers, not by a direct `python opentalk_gui.py` invocation.

## Troubleshooting

- **Linux insertion test:** Hyprland `printf 'Test äöü' | wtype -`; KDE `kwtype 'Test äöü'`.
- **Mac insertion test:** `printf 'Test äöü' | pbcopy`, then `Cmd+V`. If automatic insertion
  fails, check the Accessibility permission.
- **Service won't start:** run `python3 opentalk.py daemon` in a terminal to see the error.
- **Setup downloads:** first-time setup needs an internet connection; recognition afterwards
  runs fully offline.

## Development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m ruff check .
.venv/bin/python -m unittest discover -s tests -v
```

On Windows use `.venv\Scripts\python.exe` instead. On Arch, an environment created with
`--system-site-packages` can reuse the matching system PyQt/LayerShellQt installation.
VS Code tasks use the selected Python interpreter, including on Windows.
Every behavior change must update/add its regression tests; see [CONTRIBUTING.md](CONTRIBUTING.md).
The POSIX command-daemon (`scripts/start.sh`, `opentalk.py daemon`) is separate from the GUI;
Windows uses the GUI and its native hotkey.

GitHub users only receive changes after they are committed and pushed. Release download links
refer to the latest **published tag**, not uncommitted changes or the current `main` checkout.

VS Code launch configs, tasks, and a Python extension recommendation are included.
Contribution notes and known limitations: [CONTRIBUTING.md](CONTRIBUTING.md).
License: [MIT](LICENSE). Third-party tools and models carry their own licenses.

## Project layout

```
opentalk.py            # Core: recording, transcription, insertion, server mode
opentalk_gui.py        # PyQt6 floating bubble + setup dialog + model switcher
audio_sources.py       # PipeWire / macOS AVFoundation / Windows DirectShow sources
live_dictation.py      # Streaming segment recognition
audio_processing.py    # Lightweight PCM levels and pause-aware segmentation
hotkeys.py             # Key press/release tracking without a platform dependency
model_setup.py         # Cross-platform engine setup and verified model downloads
requirements*.txt      # Runtime and development dependencies
layer_shell_bridge.cpp # Layer-shell overlay for Wayland
tests/                 # Unit, integration, GUI, and cross-platform regression tests
packaging/             # PyInstaller configuration for release apps
scripts/
├── gui.sh             # Launch the floating bubble
├── start.sh           # Toggle-mode launcher (hotkey target)
├── install-desktop.sh # Install as desktop application
├── install-linux.sh   # Linux-only installer entry point
├── install-macos.sh   # Apple-Silicon-only .app installer
├── install-windows.ps1 # Source environment and Windows Start-menu shortcut
├── gui.ps1            # Windows source launcher
├── python.sh          # Shared POSIX interpreter selection
├── build-release.sh   # Build a downloadable package for the current platform
├── setup-model.sh     # Build pinned whisper.cpp and download default models
└── download-model.sh  # Checksum-verified model downloads
```

---

**Status: early preview.** Core flows are tested with simulated microphone/input programs;
full end-to-end checks on real Wayland, Windows, and Apple Silicon hardware are ongoing.
The GUI supports toggle and push-to-talk; native global hotkey support depends on desktop permissions.
