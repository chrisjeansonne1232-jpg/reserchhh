@echo off
REM Edge Lab one-time setup for Windows. Double-click this file, or run it from a Command Prompt.
cd /d "%~dp0"
echo ============================================================
echo  Edge Lab setup  (paper money only - no real orders, ever)
echo ============================================================
where py >nul 2>nul
if errorlevel 1 (
  echo.
  echo Python was not found. Install Python 3.12 from https://www.python.org/downloads/
  echo and TICK the box "Add python.exe to PATH" during install. Then run this file again.
  pause
  exit /b 1
)
if not exist .venv (
  echo Creating a private Python environment in .venv ...
  py -3.12 -m venv .venv
  if errorlevel 1 py -3 -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -e .
if errorlevel 1 (
  echo Install failed - copy the red text above and send it to Claude.
  pause
  exit /b 1
)
echo.
echo --- Checking that your API keys are visible (names only, values are never shown) ---
python -m edgelab.data keys
echo.
echo --- Running the self-tests (takes about a minute) ---
python -m pytest -q
echo.
echo Setup finished. Next step is in README.md ("First steps").
pause
