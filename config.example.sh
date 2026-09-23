# Kopieren nach config.local.sh; persönliche Werte werden von Git ignoriert.
export SPRECHSCHRIFT_MODEL="$HOME/whisper.cpp/models/ggml-small.bin"
export SPRECHSCHRIFT_WHISPER_CLI="$HOME/whisper.cpp/build/bin/whisper-cli"
export SPRECHSCHRIFT_LANGUAGE="de"
export SPRECHSCHRIFT_INSERT="auto"
# Optionaler eigener Server im privaten Netz:
# export SPRECHSCHRIFT_SERVER_URL="http://TAILSCALE-IP:8765"
# export SPRECHSCHRIFT_TOKEN="LANGES-ZUFAELLIGES-TOKEN"
