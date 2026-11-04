#!/bin/bash
echo "Starting AGYBridge on Termux..."
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi
pm2 start .venv/bin/python --name agybridge -- web.py
