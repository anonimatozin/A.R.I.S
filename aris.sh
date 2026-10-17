#!/usr/bin/env bash
# A.R.I.S. CLI — Linux (equivalente ao aris.bat)
# Uso: ./aris.sh [opções do aris_local.py]
#   ./aris.sh                 # voz completa (TTS + microfone)
#   ./aris.sh --mic-off       # sem microfone
#   ./aris.sh --text-only     # só texto
set -e

ARIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$ARIS_DIR/venv-linux/bin/python"

# PortAudio extraído localmente (sem sudo) para PyAudio/sounddevice
PA_DIR="$HOME/.local/opt/portaudio/usr"
if [ -d "$PA_DIR/lib/x86_64-linux-gnu" ]; then
    export LD_LIBRARY_PATH="$PA_DIR/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

# X11 (pyautogui/OCR): o GNOME exporta XAUTHORITY apontando para o cookie
# cru do Xwayland, gravado com o nome canônico "host/unix:" — o Xlib do
# Python não conecta com esse arquivo. Normaliza sempre para o display atual.
if [ -n "$DISPLAY" ]; then
    dispnum="${DISPLAY##*:}"
    source_auth="${XAUTHORITY:-}"
    if [ -z "$source_auth" ] || [ ! -f "$source_auth" ]; then
        for candidate in "$HOME/.Xauthority" /run/user/$(id -u)/.mutter-Xwaylandauth.* /run/user/$(id -u)/gdm/Xauthority; do
            if [ -f "$candidate" ]; then
                source_auth="$candidate"
                break
            fi
        done
    fi
    if [ -n "$source_auth" ] && command -v xauth >/dev/null 2>&1; then
        # Pega o primeiro MIT-MAGIC-COOKIE-1 e o regrava com o nome do
        # display atual, que é o formato que o Xlib espera.
        cookie="$(xauth -f "$source_auth" list 2>/dev/null | grep "MIT-MAGIC-COOKIE-1" | head -1 | awk '{print $NF}')"
        if [ -n "$cookie" ]; then
            AUTHTMP="/tmp/aris_xauth_$(id -u)"
            : > "$AUTHTMP"
            xauth -f "$AUTHTMP" add ":${dispnum}" . "$cookie" 2>/dev/null
            export XAUTHORITY="$AUTHTMP"
        fi
    fi
fi

export PYTHONPATH="$ARIS_DIR${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUNBUFFERED=1

cd "$ARIS_DIR"
exec "$PYTHON" "$ARIS_DIR/aris_local.py" "$@"
