@echo off
setlocal EnableDelayedExpansion

set PYTHON_VERSION=3.13
set VENV_DIR=.venv
set REQUIREMENTS=requirements-windows.txt
set VENV_ACTIVATE=%VENV_DIR%\Scripts\activate.bat
set MARKER=%VENV_DIR%\.deps_installed

:: Prebuilt relocatable CPython (python-build-standalone, maintained by Astral).
:: Deliberately PINNED, not resolved to "latest" via the GitHub API — the API is
:: rate-limited per IP, and two users installing a week apart should not get
:: different interpreters. Keep these in sync with run.sh.
set PBS_REPO=astral-sh/python-build-standalone
set PBS_TAG=20260718
set PBS_PY=3.13.14

:: Where the self-contained interpreter is cached. User-level rather than
:: project-local so it survives fresh clones, and because an installed bundle is
:: read-only and cannot store a Python inside itself.
if defined PARROT_PYTHON_DIR (
    set "PYTHON_DIR=%PARROT_PYTHON_DIR%"
) else (
    set "PYTHON_DIR=%LOCALAPPDATA%\parrot.py\python\%PYTHON_VERSION%"
)

:: Suppress Qt DPI awareness warning on Windows
set QT_LOGGING_RULES=qt.qpa.window=false

:: --- Find Python 3.13 ---
call :find_python
if defined PYTHON_CMD goto :found

echo.
echo   Python %PYTHON_VERSION% is required but was not found.
echo.

:: Check network before offering install
call :check_network

echo   How would you like to install Python %PYTHON_VERSION%?
echo.
echo     [1] Download a self-contained Python (recommended)
echo         ~25 MB, no admin rights, nothing installed system-wide
echo     [2] Install system-wide with winget
echo     [3] I'll install it myself
echo.
set /p "CHOICE=  Choose [1/2/3] (default 1): "
echo.

if not defined CHOICE set CHOICE=1
if "%CHOICE%"=="1" goto :install_standalone
if "%CHOICE%"=="2" goto :want_winget
if "%CHOICE%"=="3" goto :manual_install
goto :manual_install

:want_winget
where winget >nul 2>&1
if errorlevel 1 goto :no_winget
goto :install_winget

:install_standalone
:: curl ships with Windows 10 1803+, tar with Windows 10 17063+
where curl >nul 2>&1
if errorlevel 1 (
    echo   curl was not found ^(it ships with Windows 10 1803 and later^).
    echo   Choose option [2] or [3] instead.
    echo.
    exit /b 1
)
where tar >nul 2>&1
if errorlevel 1 (
    echo   tar was not found ^(it ships with Windows 10 17063 and later^).
    echo   Choose option [2] or [3] instead.
    echo.
    exit /b 1
)

set "PBS_PLAT="
if /i "%PROCESSOR_ARCHITECTURE%"=="AMD64" set "PBS_PLAT=x86_64-pc-windows-msvc"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "PBS_PLAT=aarch64-pc-windows-msvc"
if /i "%PROCESSOR_ARCHITECTURE%"=="x86"   set "PBS_PLAT=i686-pc-windows-msvc"
if not defined PBS_PLAT (
    echo   No prebuilt Python is available for architecture %PROCESSOR_ARCHITECTURE%.
    echo   Choose option [2] or [3] instead.
    echo.
    exit /b 1
)

if defined PARROT_PYTHON_URL (
    set "PBS_URL=%PARROT_PYTHON_URL%"
) else (
    set "PBS_URL=https://github.com/%PBS_REPO%/releases/download/%PBS_TAG%/cpython-%PBS_PY%+%PBS_TAG%-!PBS_PLAT!-install_only.tar.gz"
)

set "PBS_TMP=%TEMP%\parrot-python-%RANDOM%"
if exist "%PBS_TMP%" rmdir /s /q "%PBS_TMP%"
mkdir "%PBS_TMP%"

echo   Downloading a self-contained Python %PYTHON_VERSION% (~25 MB, no admin rights needed)...
echo.
curl -fL --progress-bar --max-time 300 "!PBS_URL!" -o "%PBS_TMP%\python.tar.gz"
if errorlevel 1 (
    echo.
    echo   Download failed.
    echo   URL: !PBS_URL!
    rmdir /s /q "%PBS_TMP%"
    echo.
    exit /b 1
)

echo   Extracting...
tar -xzf "%PBS_TMP%\python.tar.gz" -C "%PBS_TMP%"
if errorlevel 1 (
    echo   Could not extract the archive.
    rmdir /s /q "%PBS_TMP%"
    echo.
    exit /b 1
)

:: Archive contains a single top-level python\ directory
if not exist "%PBS_TMP%\python\python.exe" (
    echo   Unexpected archive layout - no python\python.exe inside.
    rmdir /s /q "%PBS_TMP%"
    echo.
    exit /b 1
)

if exist "%PYTHON_DIR%" rmdir /s /q "%PYTHON_DIR%"
for %%P in ("%PYTHON_DIR%") do mkdir "%%~dpP" 2>nul
move "%PBS_TMP%\python" "%PYTHON_DIR%" >nul
if errorlevel 1 (
    echo   Could not move the interpreter into place.
    echo   Target: %PYTHON_DIR%
    rmdir /s /q "%PBS_TMP%"
    echo.
    exit /b 1
)
rmdir /s /q "%PBS_TMP%" 2>nul

echo   Installed to %PYTHON_DIR%
echo.

call :find_python
if defined PYTHON_CMD goto :found

echo   Python was downloaded but could not be found at:
echo     %PYTHON_DIR%\python.exe
echo.
exit /b 1

:install_winget
echo   Installing Python %PYTHON_VERSION% via winget...
echo.
winget install Python.Python.3.13 --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo.
    echo   winget install failed. Try installing manually:
    echo     https://www.python.org/downloads/
    echo.
    exit /b 1
)
echo.
echo   Python installed. Refreshing PATH...
echo.

:: Refresh PATH from registry so we pick up the new install without restarting the terminal
call :refresh_path

:: Try finding Python again
call :find_python
if defined PYTHON_CMD (
    echo   Found: !PYTHON_CMD!
    goto :found
)

:: Still not found via PATH — check common install locations directly
call :find_python_direct
if defined PYTHON_CMD (
    echo   Found: !PYTHON_CMD!
    goto :found
)

echo   Python was installed but could not be found in PATH.
echo   Please restart your terminal and rerun: run.bat
echo.
exit /b 1

:no_winget
echo   winget is not available on this system.
echo.

:manual_install
echo   Install Python %PYTHON_VERSION% using one of these methods:
echo.
echo     Official installer:
echo       https://www.python.org/downloads/
echo       Make sure to check "Add Python to PATH" during install.
echo.
echo     winget (if available):
echo       winget install Python.Python.3.13
echo.
echo   Or rerun run.bat and choose [1] to download a self-contained Python
echo   that needs no admin rights and changes nothing system-wide.
echo.
echo   After installing, rerun: run.bat
echo.
exit /b 1

:found
echo   Using: %PYTHON_CMD% (%PYTHON_VERSION%)

:: --- Discard a venv built for a different platform ---
if exist "%VENV_DIR%\bin" (
    echo.
    echo   Existing virtual environment was created on Linux/WSL and is
    echo   incompatible with Windows. It needs to be recreated.
    echo.
    set /p "VENV_CHOICE=  Recreate venv? [Y/n]: "
    if /i "!VENV_CHOICE!"=="n" (
        echo   Aborted. Remove .venv manually or run from WSL instead.
        exit /b 1
    )
    echo   Recreating venv for Windows...
    rmdir /s /q "%VENV_DIR%"
)

:: --- Hand venv creation + dependency install to bootstrap.py ---
:: bootstrap.py owns this step so the logic lives in one place instead of being
:: duplicated here and in run.sh. It shows a progress window (stdlib tkinter, so
:: it works before PyQt6 exists) and falls back to text when there's no display.
"%PYTHON_CMD%" bootstrap.py --check
if not errorlevel 1 (
    echo   Dependencies: up to date
    goto :skip_deps
)

:: No prompt: they launched the app, and setup is what launching costs the
:: first time. The setup window lists what it is doing and has Cancel.
echo.
echo   Launching setup...
echo.
call :check_network

"%PYTHON_CMD%" bootstrap.py %*
set BOOTSTRAP_CODE=!errorlevel!
if not "!BOOTSTRAP_CODE!"=="0" (
    echo.
    if "!BOOTSTRAP_CODE!"=="2" (
        echo   Setup cancelled.
    ) else (
        echo   Setup failed.
    )
    exit /b !BOOTSTRAP_CODE!
)

:skip_deps

:: --- Activate the venv for launch ---
call %VENV_ACTIVATE%

:: --- Launch GUI ---
echo.
echo   Starting Parrot.py GUI...
echo.
python -m gui
if errorlevel 1 (
    echo.
    echo   The application failed to start.
    echo.
    echo     [1] Reinstall dependencies and retry
    echo     [2] Recreate venv from scratch and retry
    echo     [3] Exit
    echo.
    set /p "ERR_CHOICE=  Choose [1/2/3]: "
    if "!ERR_CHOICE!"=="1" (
        echo   Reinstalling dependencies...
        echo.
        if exist "%MARKER%" del "%MARKER%"
        "%PYTHON_CMD%" bootstrap.py %*
        if not errorlevel 1 (
            call %VENV_ACTIVATE%
            echo.
            echo   Retrying launch...
            echo.
            python -m gui
        )
    )
    if "!ERR_CHOICE!"=="2" (
        echo   Recreating venv from scratch...
        rmdir /s /q "%VENV_DIR%"
        "%PYTHON_CMD%" bootstrap.py %*
        if not errorlevel 1 (
            call %VENV_ACTIVATE%
            echo.
            echo   Retrying launch...
            echo.
            python -m gui
        )
    )
)
exit /b 0

:: ============================================================
:: Subroutines
:: ============================================================

:find_python
set PYTHON_CMD=

:: Our own cached self-contained interpreter wins — it's the one we manage
if exist "%PYTHON_DIR%\python.exe" (
    set "PYTHON_CMD=%PYTHON_DIR%\python.exe"
    exit /b 0
)

:: Search PATH for python commands matching the target version
for %%C in (python3.13 python3 python) do (
    where %%C >nul 2>&1 && (
        for /f "tokens=2 delims= " %%V in ('%%C --version 2^>^&1') do (
            echo %%V | findstr /b "%PYTHON_VERSION%" >nul && (
                set PYTHON_CMD=%%C
                exit /b 0
            )
        )
    )
)
exit /b 1

:find_python_direct
:: Check common Windows install locations for Python 3.13
set PYTHON_CMD=
:: winget / official installer default locations
for %%D in (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%PROGRAMFILES%\Python313\python.exe"
    "%PROGRAMFILES(x86)%\Python313\python.exe"
    "%APPDATA%\..\Local\Programs\Python\Python313\python.exe"
) do (
    if exist %%D (
        for /f "tokens=2 delims= " %%V in ('%%D --version 2^>^&1') do (
            echo %%V | findstr /b "%PYTHON_VERSION%" >nul && (
                set PYTHON_CMD=%%~D
                exit /b 0
            )
        )
    )
)
exit /b 1

:check_network
:: Verify network connectivity before attempting downloads
curl -s --max-time 5 https://pypi.org >nul 2>&1
if errorlevel 1 (
    ping -n 1 -w 3000 8.8.8.8 >nul 2>&1
    if errorlevel 1 (
        echo   No network connectivity detected.
        echo   Please check your internet connection and rerun: run.bat
        echo.
        exit /b 1
    )
)
exit /b 0

:refresh_path
:: Read the current user and system PATH from the registry and apply it
for /f "tokens=2*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "USER_PATH=%%B"
for /f "tokens=2*" %%A in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "SYS_PATH=%%B"
if defined SYS_PATH if defined USER_PATH set "PATH=%SYS_PATH%;%USER_PATH%"
if defined SYS_PATH if not defined USER_PATH set "PATH=%SYS_PATH%"
exit /b 0
