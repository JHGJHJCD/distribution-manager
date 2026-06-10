@echo off
chcp 65001 >nul
echo ===================================================
echo  בונה קובץ הפצה — מנהל חלוקה
echo ===================================================

cd /d "%~dp0"

echo [1/3] מוודא PyInstaller מותקן תחת Python הנכון...
python -m pip install pyinstaller -q
if errorlevel 1 (
    echo שגיאה: pip נכשל
    pause & exit /b 1
)

echo [2/3] בונה EXE לפי קובץ ה-spec (Python 3.12)...
python -m PyInstaller "מנהל_חלוקה.spec" --noconfirm --clean
if errorlevel 1 (
    echo.
    echo *** הבנייה נכשלה! ***
    pause & exit /b 1
)

echo [3/3] מסיים...
echo.
echo הקובץ נמצא ב: dist\מנהל_חלוקה.exe
echo.
echo חשוב: אל תעתיק רק את ה-EXE — העבר את תיקיית dist\ כולה.
pause
