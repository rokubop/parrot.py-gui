@echo off
setlocal

set PYTHON_VERSION=3.13
set VENV_DIR=.venv
set REQUIREMENTS=requirements-windows.txt
set VENV_PYTHON=%VENV_DIR%\Scripts\python.exe
set VENV_ACTIVATE=%VENV_DIR%\Scripts\activate.bat
set MARKER=%VENV_DIR%\.deps_installed

:: --- Find Python 3.13 ---
set PYTHON_CMD=
for %%C in (python3.13 python3 python) do (
    where %%C >nul 2>&1 && (
        for /f "tokens=2 delims= " %%V in ('%%C --version 2^>^&1') do (
            echo %%V | findstr /b "%PYTHON_VERSION%" >nul && (
                set PYTHON_CMD=%%C
                goto :found
            )
        )
    )
)

echo.
echo   Python %PYTHON_VERSION% is required but was not found.
echo.
echo   Install it using one of these methods:
echo.
echo     Option 1 -- Official installer:
echo       https://www.python.org/downloads/
echo       Make sure to check "Add Python to PATH" during install.
echo.
echo     Option 2 -- winget:
echo       winget install Python.Python.3.13
echo.
echo   After installing, rerun: run.bat
echo.
exit /b 1

:found
echo Using: %PYTHON_CMD%

:: --- Create venv if missing ---
if not exist "%VENV_PYTHON%" (
    echo Creating virtual environment...
    %PYTHON_CMD% -m venv %VENV_DIR%
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
echo Installing dependencies from %REQUIREMENTS%...
pip install --upgrade pip -q
pip install -r %REQUIREMENTS% -q
echo. > %MARKER%

:skip_deps

:: --- Launch GUI ---
echo.
echo Starting Parrot.py GUI...
python -m gui
