@echo off
rem Launcher for people who downloaded only the sources: offers an update, creates .venv,
rem installs requirements, starts Spectra. The whole body is one block (cmd parses it up front),
rem so an update may overwrite this very file while it runs.
cd /d "%~dp0"
(
    powershell -NoProfile -ExecutionPolicy Bypass -File packaging\check_update.ps1

    if not exist .venv\Scripts\python.exe py -3.14 -m venv .venv || (
        echo.
        echo Setup failed. Python 3.14 for Windows is required: https://www.python.org/downloads/
        pause
        exit /b 1
    )
    .venv\Scripts\python.exe -m pip install -q -r requirements.txt || (
        echo.
        echo Installing requirements failed.
        pause
        exit /b 1
    )

    rem Desktop shortcut with the app icon (a .bat cannot carry one); it starts the app directly, no console flash.
    powershell -NoProfile -Command "$d=[Environment]::GetFolderPath('Desktop'); $p=Join-Path $d 'Spectra.lnk'; if(-not(Test-Path $p)){$s=(New-Object -ComObject WScript.Shell).CreateShortcut($p); $s.TargetPath='%~dp0.venv\Scripts\pythonw.exe'; $s.Arguments='main.py'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0resources\icons\app_icon.ico'; $s.Save()}"
    start "" .venv\Scripts\pythonw.exe main.py
    exit /b 0
)
