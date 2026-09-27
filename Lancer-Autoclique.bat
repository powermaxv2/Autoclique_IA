@echo off
rem Lance Autoclique IA sous Windows (installe les dependances au premier lancement).
setlocal
cd /d "%~dp0"

set "PY=python"
where py >nul 2>nul && set "PY=py -3"

if not exist ".venv\Scripts\pythonw.exe" (
    echo Premier lancement : installation de l'environnement Python...
    %PY% -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
)

start "" ".venv\Scripts\pythonw.exe" -m autoclique
exit /b 0

:error
echo.
echo L'installation a echoue.
echo Verifiez que Python 3.9 ou plus recent est installe : https://www.python.org/downloads/
echo (cochez "Add python.exe to PATH" pendant l'installation), puis relancez ce fichier.
pause
exit /b 1
