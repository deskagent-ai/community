#!/bin/bash
# DeskAgent - Update Script (macOS / Linux)
#
# Pulls the latest commits and re-installs Python dependencies into
# ./venv so any new packages in requirements.txt are picked up.
#
# Usage:
#   ./update.sh

set -e

cd "$(dirname "$0")"

echo ""
echo "============================================================"
echo "  DeskAgent - Update"
echo "============================================================"
echo ""

# ----------------------------------------------------------------------
# Sanity check: we must be in a git checkout
# ----------------------------------------------------------------------
if [ ! -d ".git" ] && [ ! -f ".git" ]; then
    echo "[ERROR] This directory is not a git checkout."
    echo "        update.sh only works for source installs from"
    echo "        https://github.com/deskagent-ai/community"
    exit 1
fi

# ----------------------------------------------------------------------
# Refuse to pull if the working tree has uncommitted changes
# (avoids surprising merge conflicts / clobbered local edits)
# ----------------------------------------------------------------------
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "[ERROR] You have uncommitted local changes:"
    git status --short
    echo ""
    echo "Commit, stash, or revert them first, then re-run ./update.sh"
    exit 1
fi

# ----------------------------------------------------------------------
# 1) Pull
# ----------------------------------------------------------------------
echo "[1/2] Pulling latest changes from origin..."
git pull --ff-only

# ----------------------------------------------------------------------
# 2) Reinstall requirements into the venv (only if venv exists)
# ----------------------------------------------------------------------
if [ -x "venv/bin/python" ]; then
    echo ""
    echo "[2/2] Updating Python dependencies in ./venv ..."
    venv/bin/python -m pip install --upgrade pip
    venv/bin/python -m pip install -r requirements.txt
else
    echo ""
    echo "[2/2] No ./venv found - skipping dependency update."
    echo "      Run ./setup-unix.sh first if you have not yet."
fi

echo ""
echo "============================================================"
echo "  Update complete!"
echo "============================================================"
echo ""
echo "  Start DeskAgent:    ./start.sh"
echo ""
