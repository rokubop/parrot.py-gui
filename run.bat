@echo off
setlocal EnableDelayedExpansion

set PYTHON_VERSION=3.13
set VENV_DIR=.venv
set REQUIREMENTS=requirements-windows.txt
set VENV_PYTHON=%VENV_DIR%\Scripts\python.exe
set VENV_ACTIVATE=%VENV_DIR%\Scripts\activate.bat
set MARKER=%VENV_DIR%\.deps_installed

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

:: Check if winget is available
where winget >nul 2>&1
if errorlevel 1 goto :no_winget

echo   How would you like to install Python %PYTHON_VERSION%?
echo.
echo     [1] Install automatically with winget (recommended)
echo     [2] I'll install it myself
echo.
set /p "CHOICE=  Choose [1/2]: "
echo.

if "%CHOICE%"=="1" goto :install_winget
if "%CHOICE%"=="2" goto :manual_install
goto :manual_install

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
echo   After installing, rerun: run.bat
echo.
exit /b 1

:found
echo   Using: %PYTHON_CMD% (%PYTHON_VERSION%)

:: --- Create venv (or recreate if from a different platform) ---
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
if not exist "%VENV_PYTHON%" (
    echo   Creating virtual environment...
    %PYTHON_CMD% -m venv %VENV_DIR%
    if exist "%MARKER%" del "%MARKER%"
)

:: --- Activate and install deps ---
call %VENV_ACTIVATE%

:: Install deps only if marker is missing or requirements changed
if not exist "%MARKER%" goto :install_deps
for %%R in (%REQUIREMENTS%) do for %%M in (%MARKER%) do (
    if "%%~tR" gtr "%%~tM" goto :install_deps
)
goto :skip_deps

:install_deps
echo.
echo   Dependencies need to be installed from %REQUIREMENTS%.
echo.
set /p "DEPS_CHOICE=  Install now? [Y/n]: "
if /i "!DEPS_CHOICE!"=="n" (
    echo   Skipped. Run again when ready.
    exit /b 1
)
call :check_network
echo   Installing dependencies (this may take a few minutes)...
echo.
python -m pip install --only-binary=PyQt6 --progress-bar on -r %REQUIREMENTS% --disable-pip-version-check
echo. > %MARKER%

:skip_deps

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
        python -m pip install --only-binary=PyQt6 --progress-bar on -r %REQUIREMENTS% --disable-pip-version-check
        if not errorlevel 1 (
            echo. > %MARKER%
            echo.
            echo   Retrying launch...
            echo.
            python -m gui
        )
    )
    if "!ERR_CHOICE!"=="2" (
        echo   Recreating venv from scratch...
        rmdir /s /q "%VENV_DIR%"
        %PYTHON_CMD% -m venv %VENV_DIR%
        call %VENV_ACTIVATE%
        echo   Installing dependencies...
        echo.
        python -m pip install --only-binary=PyQt6 --progress-bar on -r %REQUIREMENTS% --disable-pip-version-check
        if not errorlevel 1 (
            echo. > %MARKER%
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
:: Search PATH for python commands matching the target version
set PYTHON_CMD=
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
