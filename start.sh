#!/bin/bash
# AI Assistant - Start Script (Linux/Mac)

cd "$(dirname "$0")"

# Check for Python
if command -v python3 &> /dev/null; then
    PYTHON=python3
elif command -v python &> /dev/null; then
    PYTHON=python
else
    echo "[ERROR] Python not found. Install Python 3.10+"
    exit 1
fi

# Check Python version
PY_VERSION=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Using Python $PY_VERSION"

# Run assistant
export PYTHONUNBUFFERED=1
$PYTHON -u scripts/assistant.py
