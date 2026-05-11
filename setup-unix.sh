#!/bin/bash
# AI Assistant - Setup Script (Linux/Mac)
# Run this once after cloning the repository

set -e

echo ""
echo "============================================================"
echo "  AI Assistant - Setup (Linux/Mac)"
echo "============================================================"
echo ""

cd "$(dirname "$0")"

# Check for Python
if command -v python3 &> /dev/null; then
    PYTHON=python3
    PIP="python3 -m pip"
elif command -v python &> /dev/null; then
    PYTHON=python
    PIP="python -m pip"
else
    echo "[ERROR] Python not found!"
    echo "        Install Python 3.10+ from https://python.org"
    exit 1
fi

# Check Python version
PY_VERSION=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$($PYTHON -c "import sys; print(sys.version_info.major)")
PY_MINOR=$($PYTHON -c "import sys; print(sys.version_info.minor)")

echo "Found Python $PY_VERSION"

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]); then
    echo "[ERROR] Python 3.10+ required, found $PY_VERSION"
    exit 1
fi

# Create virtual environment (optional but recommended)
echo ""
read -p "Create virtual environment? (recommended) [Y/n]: " CREATE_VENV
CREATE_VENV=${CREATE_VENV:-Y}

if [[ "$CREATE_VENV" =~ ^[Yy]$ ]]; then
    echo ""
    echo "[1/4] Creating virtual environment..."
    $PYTHON -m venv venv

    # Activate venv
    source venv/bin/activate
    PIP="pip"
    echo "      Virtual environment created and activated"
else
    echo ""
    echo "[1/4] Skipping virtual environment..."
fi

# Install dependencies
echo ""
echo "[2/4] Installing Python dependencies..."
echo "      (this may take a few minutes)"
echo ""
$PIP install --upgrade pip
$PIP install -r requirements.txt

# Download spaCy models
echo ""
echo "[3/4] Downloading spaCy language models..."
echo ""

echo "      German model (de_core_news_md ~50MB)..."
$PYTHON -m spacy download de_core_news_md || echo "[WARNING] German model failed"

echo "      English model (en_core_web_md ~50MB)..."
$PYTHON -m spacy download en_core_web_md || echo "[WARNING] English model failed"

# Create config from example
echo ""
echo "[4/4] Setting up configuration..."

if [ ! -f "config.json" ]; then
    if [ -f "config.json.example" ]; then
        cp config.json.example config.json
        echo "      Created config.json from example"
    else
        echo "[WARNING] config.json.example not found"
    fi
else
    echo "      config.json already exists"
fi

# Make scripts executable
chmod +x start.sh update.sh setup-unix.sh 2>/dev/null || true

echo ""
echo "============================================================"
echo "  Setup Complete!"
echo "============================================================"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Edit config.json and add your API keys:"
echo "     - anthropic (Claude API)"
echo "     - google-genai (Gemini API)"
echo "     - billomat (optional)"
echo ""
echo "  2. Run: ./start.sh"
echo ""
if [[ "$CREATE_VENV" =~ ^[Yy]$ ]]; then
    echo "  Note: Activate venv first with: source venv/bin/activate"
    echo ""
fi
echo "  Limitations on Linux/Mac:"
echo "  - No Outlook integration (Windows only)"
echo "  - Use web-based email or configure IMAP"
echo ""
