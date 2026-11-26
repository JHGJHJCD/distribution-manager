@echo off
rem Compares the lists of the website with the lists of the desktop program, on a COPY of the data.
rem The data file is only READ: it is copied to a temporary folder and everything runs on the copies.
rem Double-click = compare on the desktop program's own data file.
rem Or drag a copy of data.db onto this file (or: compare_with_old.bat "C:\path\to\data.db").
rem At the end the report opens in the browser. It holds numbers only - no names.
cd /d "%~dp0.."
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"
set "SRC=%~1"
if "%SRC%"=="" set "SRC=%APPDATA%\ManhalHaluka\data.db"
if not exist "%SRC%" (
  echo The data file was not found: "%SRC%"
  echo Drag a copy of data.db onto this file and try again.
  pause
  exit /b 2
)
"%PY%" -c "import fastapi, openpyxl" 2>nul
if errorlevel 1 (
  echo Python 3.12 with fastapi and openpyxl was not found. The comparison cannot run.
  pause
  exit /b 2
)
set PYTHONUTF8=1
set "SENT="
if exist "web\data\sent_history.json" set SENT=--sent-history "web\data\sent_history.json"
echo Comparing... this takes a few minutes. Nothing is changed in the data.
"%PY%" web\tests\local_check_real.py --from "%SRC%" %SENT% --report --open
echo.
pause
