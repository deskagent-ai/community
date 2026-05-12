#!/bin/bash
# DeskAgent - Setup Script (macOS / Linux)
# Run this once after cloning the repository.
#
# Usage:
#   ./setup-unix.sh
#
# Tested on:
#   - macOS 14+ (Apple Silicon and Intel)
#   - Ubuntu 22.04 / 24.04
#   - Fedora 40
#
# If you get "bad interpreter: /bin/bash^M" - your checkout has CRLF
# line endings (Git was configured to convert on checkout). Fix once:
#   sed -i '' 's/\r//' setup-unix.sh start.sh    # macOS
#   sed -i    's/\r//' setup-unix.sh start.sh    # Linux
# The repo now ships a .gitattributes that forces LF for .sh files,
# so a fresh clone should not have this problem any more.

set -e

echo ""
echo "============================================================"
echo "  DeskAgent - Setup (macOS / Linux)"
echo "============================================================"
echo ""

cd "$(dirname "$0")"

# ----------------------------------------------------------------------
# 1) Find a usable Python 3.12.x
# ----------------------------------------------------------------------
# DeskAgent requires Python 3.12 (NOT 3.13 - spaCy/thinc are not yet
# compatible). We probe several names so a fresh Homebrew install of
# python@3.12 works even if 'python3' still points at the system default.

PYTHON=""
for CANDIDATE in python3.12 python3.11 python3.10 python3 python; do
    if command -v "$CANDIDATE" &> /dev/null; then
        VER=$("$CANDIDATE" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "")
        if [ "$VER" = "3.12" ] || [ "$VER" = "3.11" ] || [ "$VER" = "3.10" ]; then
            PYTHON="$CANDIDATE"
            echo "Found $CANDIDATE -> Python $VER"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "[ERROR] No compatible Python found (need 3.10, 3.11, or 3.12)."
    echo ""
    echo "Install Python 3.12 first:"
    echo "  macOS:        brew install python@3.12"
    echo "  Ubuntu/Debian: sudo apt install python3.12 python3.12-venv"
    echo "  Fedora:        sudo dnf install python3.12"
    echo ""
    echo "Then re-run ./setup-unix.sh"
    exit 1
fi

PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")

# Hard reject 3.13+ even if we somehow picked it up
PY_MAJOR=$("$PYTHON" -c "import sys; print(sys.version_info.major)")
PY_MINOR=$("$PYTHON" -c "import sys; print(sys.version_info.minor)")
if [ "$PY_MAJOR" -gt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -gt 12 ]); then
    echo "[ERROR] Python $PY_VERSION is too new."
    echo "        DeskAgent requires Python 3.12 (spaCy/thinc are not"
    echo "        yet compatible with 3.13). Install 3.12 alongside:"
    echo "  macOS:  brew install python@3.12"
    echo "  Linux:  use pyenv or your distro's python3.12 package"
    exit 1
fi

# ----------------------------------------------------------------------
# 2) Create virtual environment (always - no prompt; non-interactive
#    safe; people who want a system-wide install can pip-install
#    deskagent themselves)
# ----------------------------------------------------------------------
echo ""
echo "[1/4] Creating virtual environment in ./venv ..."
if [ -d venv ]; then
    echo "      venv already exists - reusing"
else
    "$PYTHON" -m venv venv
fi

# Activate venv for the rest of this script
# shellcheck disable=SC1091
source venv/bin/activate
PYTHON_VENV="$(pwd)/venv/bin/python"

# ----------------------------------------------------------------------
# 3) Install dependencies
# ----------------------------------------------------------------------
echo ""
echo "[2/4] Installing Python dependencies (this can take a few minutes)..."
"$PYTHON_VENV" -m pip install --upgrade pip
"$PYTHON_VENV" -m pip install -r requirements.txt

# ----------------------------------------------------------------------
# 4) Optional spaCy models for the anonymizer extra
# ----------------------------------------------------------------------
echo ""
echo "[3/4] Optional: spaCy language models for PII anonymization."
echo "      Skip with Ctrl+C if you don't need them."
echo ""

if "$PYTHON_VENV" -c "import spacy" 2>/dev/null; then
    "$PYTHON_VENV" -m spacy download de_core_news_md \
        || echo "      [WARNING] German model failed - skipping"
    "$PYTHON_VENV" -m spacy download en_core_web_md \
        || echo "      [WARNING] English model failed - skipping"
else
    echo "      spaCy not installed (would be pulled in by [anonymizer] extra)."
    echo "      To enable PII anonymization:  pip install -e .[anonymizer]"
fi

# ----------------------------------------------------------------------
# 5) Make scripts executable
# ----------------------------------------------------------------------
echo ""
echo "[4/4] Marking scripts executable..."
chmod +x start.sh update.sh setup-unix.sh 2>/dev/null || true

# ----------------------------------------------------------------------
# Done
# ----------------------------------------------------------------------
echo ""
echo "============================================================"
echo "  Setup Complete!"
echo "============================================================"
echo ""
echo "  Start DeskAgent:"
echo "      ./start.sh"
echo ""
echo "  (start.sh activates the venv automatically - you do NOT"
echo "  need to 'source venv/bin/activate' yourself.)"
echo ""
echo "  Configuration: edit config/backends.json and config/apis.json"
echo "  (templates with placeholder values are already present)."
echo ""
echo "  macOS / Linux limitations vs Windows:"
echo "    - outlook MCP    (Windows COM only)  -> use gmail/imap/msgraph"
echo "    - clipboard MCP  (Windows pywin32)   -> not loaded"
echo ""
