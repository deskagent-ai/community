#!/bin/bash
# AI Assistant - Update Script (Linux/Mac)

cd "$(dirname "$0")"

echo "Updating from GitHub..."
git pull

if [ $? -eq 0 ]; then
    echo ""
    echo "Update complete! Run ./start.sh to launch."
else
    echo ""
    echo "Update failed. Check your git configuration."
fi
