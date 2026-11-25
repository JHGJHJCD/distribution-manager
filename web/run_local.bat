@echo off
rem Starts the website on THIS computer only: http://127.0.0.1:8787
rem Double-click = start the server and open the browser.  "run_local.bat noopen" = server only.
rem Close this window (or press Ctrl+C) to stop the site.
cd /d "%~dp0.."
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -c "import fastapi, uvicorn" 2>nul
if errorlevel 1 (
  echo Python 3.12 with fastapi and uvicorn was not found. The site cannot start.
  if /i not "%~1"=="noopen" pause
  exit /b 1
)
if /i not "%~1"=="noopen" start "" /min cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:8787"
"%PY%" -m uvicorn web.app:app --host 127.0.0.1 --port 8787
