#!/bin/bash
# DeskAgent - Start Script (macOS / Linux)
#
# Auto-activates ./venv if it exists. You do NOT need to
# 'source venv/bin/activate' yourself.
#
# Usage:
#   ./start.sh                      # default port 8765, foreground
#   ./start.sh --port 9000          # custom port
#   ./start.sh --no-tray            # no tray icon
#
# If you get "bad interpreter: /bin/bash^M", fix line endings once:
#   sed -i '' 's/\r//' setup-unix.sh start.sh    # macOS
#   sed -i    's/\r//' setup-unix.sh start.sh    # Linux

cd "$(dirname "$0")"

# ----------------------------------------------------------------------
# Pick Python: venv if present, otherwise a usable Python 3.12.x
# ----------------------------------------------------------------------
if [ -x "venv/bin/python" ]; then
    PYTHON="$(pwd)/venv/bin/python"
    USING_VENV=1
else
    USING_VENV=0
    PYTHON=""
    for CANDIDATE in python3.12 python3.11 python3.10 python3 python; do
        if command -v "$CANDIDATE" &> /dev/null; then
            PYTHON="$CANDIDATE"
            break
        fi
    done

    if [ -z "$PYTHON" ]; then
        echo "[ERROR] Python not found and no ./venv directory."
        echo "        Run ./setup-unix.sh first."
        exit 1
    fi
fi

PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if [ "$USING_VENV" = "1" ]; then
    echo "[INFO] Using venv Python $PY_VERSION"
else
    echo "[INFO] Using system Python $PY_VERSION (no ./venv found)"
fi

# ----------------------------------------------------------------------
# Set PYTHONPATH and start
# ----------------------------------------------------------------------
export PYTHONUNBUFFERED=1
export PYTHONPATH="$(pwd)/scripts"

# Mirror what start.bat does on Windows: load the assistant module's
# main() rather than executing a script file. This works because
# scripts/assistant/__init__.py exposes main.
exec "$PYTHON" -c "import sys; sys.path.insert(0, '$(pwd)/scripts'); from assistant import main; main()" "$@"
