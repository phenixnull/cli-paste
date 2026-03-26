@echo off
chcp 65001 >nul 2>&1

cd /d "%~dp0"

if exist "dist\cli_paste.exe" (
    echo [cli_paste] Start local dist\cli_paste.exe
    start "" "dist\cli_paste.exe"
    exit /b 0
)

if defined CLI_PASTE_PYTHON (
    if not exist "%CLI_PASTE_PYTHON%" (
        echo [cli_paste] CLI_PASTE_PYTHON does not exist: %CLI_PASTE_PYTHON%
        pause
        exit /b 1
    )
    echo [cli_paste] Bootstrap with %CLI_PASTE_PYTHON%
    "%CLI_PASTE_PYTHON%" "bootstrap.py"
    goto :done
)

where py >nul 2>&1
if not errorlevel 1 (
    echo [cli_paste] Bootstrap with py -3
    py -3 "bootstrap.py"
    goto :done
)

where python >nul 2>&1
if not errorlevel 1 (
    echo [cli_paste] Bootstrap with python
    python "bootstrap.py"
    goto :done
)

echo [cli_paste] Python not found. Install Python 3.8+ or set CLI_PASTE_PYTHON.
pause
exit /b 1

:done
if errorlevel 1 (
    pause
    exit /b %errorlevel%
)
