# OpenTalk

<p align="center">
  <em>Local voice dictation for Linux, Windows, and Apple Silicon Macs.</em>
</p>

**OpenTalk** turns your voice into text **100% locally** using [whisper.cpp](https://github.com/ggml-org/whisper.cpp). No cloud APIs, no accounts, no telemetry — your voice never leaves your machine (unless *you* choose your own home server as the recognition backend).

```
Hotkey / Click → Speak → Stop → Text lands in the focused window ✨
```

## Highlights

- 🖥️ **Floating overlay bubble** — always on top (even over fullscreen), draggable, no keyboard focus stealing
- ⚡ **Live dictation** — finished speech segments are transcribed and typed out every ~4 s while you keep talking
- 🎚️ **Model switcher in the GUI** — tiny, base, small, medium, large-v3 (75 MiB – 2.9 GiB), with checksum-verified downloads
- 🎙️ **Microphone picker** — choose a PipeWire, macOS, or Windows input in the UI
- 🧠 **VAD segmentation** — optional Silero voice-activity detection splits speech cleanly
- 🔒 **Privacy first** — recognition runs locally on whisper.cpp; optional self-hosted server mode with token auth
- ⌨️ **Native text insertion** — Wayland tools, macOS Cmd+V, or Windows Ctrl+V
- 🧩 **Desktop integration** — install as an app, bind a global hotkey, drag & reposition the bubble
- 🏠 **Optional home-server mode** — offload recognition to your own server (great for laptops / ARM)

## How it works

| Part | Desktop | Home server |
| --- | --- | --- |
| Recording | Linux: PipeWire · macOS: AVFoundation · Windows: DirectShow | — |
| Recognition | `whisper-cli` (local) or your server | `whisper-cli` |
| Text insertion | Linux: `wtype`/`kwtype` · macOS: Cmd+V · Windows: Ctrl+V | — |

## Installation

Linux, macOS, and Windows receive separate packages. The macOS build is limited to
**Apple Silicon (M1, M2, M3, M4 and newer M processors)**; Intel Macs are not supported.

### Ready-to-run downloads (no Git clone)

- **[Download for macOS — Apple Silicon only](https://github.com/k1ra-dev/OpenTalk/releases/latest/download/OpenTalk-macOS-arm64.zip)**
- **[Download for Linux — x86_64](https://github.com/k1ra-dev/OpenTalk/releases/latest/download/OpenTalk-Linux-x86_64.tar.gz)**
- **[Download for Windows — x86_64](https://github.com/k1ra-dev/OpenTalk/releases/latest/download/OpenTalk-Windows-x86_64.zip)**

Extract the matching download and launch `OpenTalk.app` on macOS or `OpenTalk`/`OpenTalk.exe`
inside the Linux/Windows folder. The packages already contain Python, PyQt, `whisper-cli`,
and FFmpeg where needed. On first launch, use **double-click → ⚙ → Set up now** to download
the speech model. macOS may require right-clicking the unsigned app and choosing **Open** the
first time.

The source installation below remains available for development.

### Global hotkey

OpenTalk assigns a working default shortcut for each platform:

| System | Default hotkey |
| --- | --- |
| macOS | `Cmd+Shift+Space` |
| Windows | `Ctrl+Alt+R` |
| Linux | `Ctrl+Alt+R` |

Double-click the bubble and change the shortcut directly in **Settings → Global hotkey**.
macOS requires Accessibility permission for global shortcuts. On some Wayland compositors,
global shortcut registration is restricted by the desktop; the existing KDE/Hyprland system
shortcut remains the fallback.

### Get the project (both platforms)

```bash
git clone https://github.com/k1ra-dev/OpenTalk.git ~/Programme/opentalk
cd ~/Programme/opentalk
```

### Linux (Arch / CachyOS)

Install the Linux dependencies:

```bash
sudo pacman -S --needed python python-pyqt6 pipewire libpulse git base-devel pkgconf \
    layer-shell-qt wl-clipboard libnotify
```

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

### One-time speech-model setup

If speech recognition is missing, go to **double-click → ⚙ → Set up now**. This installs
`whisper.cpp`, a multilingual `small` model, and a small VAD model into your user directory
(~466 MiB download). No CMake on your system? Setup fetches a checksum-verified portable
copy automatically.

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

While recording, finished segments are typed into the previously focused window every ~4 s.
Pure music markers like `[MUSIC]` are discarded. Recording auto-ends after 2 minutes;
temporary audio files are deleted afterwards.

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

> **Known limitation:** `whisper-cli` currently reloads the model for every segment, so
> recognition can take a moment per segment.

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
| `OPENTALK_VAD_MODEL` | Optional path to the Silero VAD model |
| `OPENTALK_LANGUAGE` | `de` (default) or `auto` |
| `OPENTALK_INSERT` | `auto`, `wtype`, `kwtype`, `clipboard`, `stdout` |
| `OPENTALK_SOURCE` | PipeWire name, AVFoundation index, or Windows DirectShow device name |
| `OPENTALK_FFMPEG` | Optional custom FFmpeg path on macOS or Windows |
| `OPENTALK_SERVER_URL` | URL of your optional home server |
| `OPENTALK_TOKEN` | Shared token, minimum 24 characters |

Personal overrides live in `config.local.sh` (gitignored, `chmod 600`).
Template: `config.example.sh`.

## Troubleshooting

- **Linux insertion test:** Hyprland `printf 'Test äöü' | wtype -`; KDE `kwtype 'Test äöü'`.
- **Mac insertion test:** `printf 'Test äöü' | pbcopy`, then `Cmd+V`. If automatic insertion
  fails, check the Accessibility permission.
- **Service won't start:** run `python3 opentalk.py daemon` in a terminal to see the error.
- **Setup downloads:** first-time setup needs an internet connection; recognition afterwards
  runs fully offline.

## Development

```bash
python3 -m unittest discover -s . -p 'test_*.py' -v   # run tests
python3 opentalk.py daemon                             # foreground service (see errors)
```

VS Code launch configs, tasks, and a Python extension recommendation are included.
Contribution notes and known limitations: [CONTRIBUTING.md](CONTRIBUTING.md).
License: [MIT](LICENSE). Third-party tools and models carry their own licenses.

## Project layout

```
opentalk.py            # Core: recording, transcription, insertion, server mode
opentalk_gui.py        # PyQt6 floating bubble + setup dialog + model switcher
audio_sources.py       # PipeWire / macOS AVFoundation / Windows DirectShow sources
live_dictation.py      # Streaming segment recognition
model_setup.py         # Cross-platform model downloader for packaged apps
layer_shell_bridge.cpp # Layer-shell overlay for Wayland
scripts/
├── gui.sh             # Launch the floating bubble
├── start.sh           # Toggle-mode launcher (hotkey target)
├── install-desktop.sh # Install as desktop application
├── install-linux.sh   # Linux-only installer entry point
├── install-macos.sh   # Apple-Silicon-only .app installer
├── build-release.sh   # Build a downloadable package for the current platform
├── setup-model.sh     # Install whisper.cpp (+ portable CMake fallback)
└── download-model.sh  # Checksum-verified model downloads
```

---

**Status: early preview.** Core flows are tested with simulated microphone/input programs;
full end-to-end checks on real Wayland, Windows, and Apple Silicon hardware are ongoing.
The hotkey toggles recording (press-and-hold is not implemented yet).
