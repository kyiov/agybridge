@echo off
echo Starting AGYBridge...
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)
python web.py
pause
