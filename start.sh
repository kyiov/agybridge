#!/bin/bash
echo "Memulai AGYBridge..."
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi
python web.py
