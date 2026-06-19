#!/usr/bin/env bash
set -e

PYTHON_VERSION="3.13"
VENV_DIR=".venv"

# -------------------------------------------------------
# Git Bash / MINGW detection — redirect to run.bat
# -------------------------------------------------------
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
    echo ""
    echo "  Detected Git Bash (MINGW). This script is for Linux/WSL/macOS."
    echo ""
    echo "  To run on Windows, use one of these instead:"
    echo ""
    echo "    From PowerShell or cmd:   run.bat"
    echo "    From Git Bash:            cmd //c run.bat"
    echo ""

    # Check if run.bat exists and offer to launch it
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [[ -f "$SCRIPT_DIR/run.bat" ]]; then
        read -rp "  Launch run.bat now? [Y/n]: " choice
        case "$choice" in
            [nN]*)
                exit 0
                ;;
            *)
                cmd //c "$(cygpath -w "$SCRIPT_DIR/run.bat")"
                exit $?
                ;;
        esac
    fi
    exit 1
fi

# Colors (if terminal supports them)
if [[ -t 1 ]]; then
    BOLD="\033[1m"
    DIM="\033[2m"
    GREEN="\033[32m"
    YELLOW="\033[33m"
    RED="\033[31m"
    CYAN="\033[36m"
    RESET="\033[0m"
else
    BOLD="" DIM="" GREEN="" YELLOW="" RED="" CYAN="" RESET=""
fi

info()  { echo -e "${CYAN}$1${RESET}"; }
ok()    { echo -e "${GREEN}$1${RESET}"; }
warn()  { echo -e "${YELLOW}$1${RESET}"; }
err()   { echo -e "${RED}$1${RESET}"; }

# Detect platform
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
    PLATFORM="windows"
    REQUIREMENTS="requirements-windows.txt"
    VENV_PYTHON="$VENV_DIR/Scripts/python"
    VENV_ACTIVATE="$VENV_DIR/Scripts/activate"
else
    PLATFORM="posix"
    REQUIREMENTS="requirements-posix.txt"
    VENV_PYTHON="$VENV_DIR/bin/python"
    VENV_ACTIVATE="$VENV_DIR/bin/activate"
fi

# -------------------------------------------------------
# Step 1: Check network connectivity (needed for installs)
# -------------------------------------------------------
check_network() {
    if ! curl -s --max-time 5 https://pypi.org > /dev/null 2>&1; then
        if ! ping -c 1 -W 3 8.8.8.8 > /dev/null 2>&1; then
            err "No network connectivity detected."
            echo ""
            echo "  If you're on WSL, this is often a DNS issue. Try:"
            echo ""
            echo "    echo \"nameserver 8.8.8.8\" | sudo tee /etc/resolv.conf"
            echo ""
            echo "  Then rerun: ./run.sh"
            exit 1
        else
            err "Network is reachable but DNS resolution is failing."
            echo ""
            echo "  Fix DNS by running:"
            echo ""
            echo "    echo \"nameserver 8.8.8.8\" | sudo tee /etc/resolv.conf"
            echo ""
            echo "  Then rerun: ./run.sh"
            exit 1
        fi
    fi
}

# -------------------------------------------------------
# Step 2: Find or install Python 3.13
# -------------------------------------------------------
load_pyenv() {
    if ! command -v pyenv &>/dev/null && [[ -d "$HOME/.pyenv" ]]; then
        export PYENV_ROOT="$HOME/.pyenv"
        export PATH="$PYENV_ROOT/bin:$PATH"
        eval "$(pyenv init -)" 2>/dev/null || true
    fi
}

find_python() {
    load_pyenv

    # Check pyenv versions directly by path first (most reliable)
    if [[ -d "$HOME/.pyenv/versions" ]]; then
        for dir in "$HOME/.pyenv/versions"/*/; do
            for bin in "$dir/bin/python3" "$dir/bin/python"; do
                if [[ -x "$bin" ]]; then
                    local version
                    version=$("$bin" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
                    if [[ "$version" == "$PYTHON_VERSION" ]]; then
                        echo "$bin"
                        return 0
                    fi
                fi
            done
        done
    fi

    # Check standard system commands (avoid pyenv shims — they can error)
    for cmd in "python${PYTHON_VERSION}" "python3" "python"; do
        local cmd_path
        cmd_path=$(command -v "$cmd" 2>/dev/null) || continue
        # Skip pyenv shims
        [[ "$cmd_path" == *".pyenv/shims"* ]] && continue
        local version
        version=$("$cmd_path" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
        if [[ "$version" == "$PYTHON_VERSION" ]]; then
            echo "$cmd_path"
            return 0
        fi
    done

    return 1
}

install_python_pyenv() {
    load_pyenv

    # Install pyenv if still not available
    if ! command -v pyenv &>/dev/null; then
        info "Installing pyenv..."
        echo ""

        # Check for build dependencies
        local missing_deps=()
        for pkg in build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev libffi-dev liblzma-dev; do
            if ! dpkg -s "$pkg" &>/dev/null; then
                missing_deps+=("$pkg")
            fi
        done

        if [[ ${#missing_deps[@]} -gt 0 ]]; then
            info "Installing build dependencies: ${missing_deps[*]}"
            sudo apt update -qq
            sudo apt install -y -qq "${missing_deps[@]}"
        fi

        curl -fsSL https://pyenv.run | bash

        # Add pyenv to current session
        export PYENV_ROOT="$HOME/.pyenv"
        export PATH="$PYENV_ROOT/bin:$PATH"
        eval "$(pyenv init -)"
    fi

    # Persist to shell config if not already there
    local shell_rc=""
    if [[ -f "$HOME/.zshrc" ]]; then
        shell_rc="$HOME/.zshrc"
    elif [[ -f "$HOME/.bashrc" ]]; then
        shell_rc="$HOME/.bashrc"
    fi

    if [[ -n "$shell_rc" ]] && ! grep -q 'PYENV_ROOT' "$shell_rc"; then
        echo '' >> "$shell_rc"
        echo '# pyenv' >> "$shell_rc"
        echo 'export PYENV_ROOT="$HOME/.pyenv"' >> "$shell_rc"
        echo 'export PATH="$PYENV_ROOT/bin:$PATH"' >> "$shell_rc"
        echo 'eval "$(pyenv init -)"' >> "$shell_rc"
        ok "  Added pyenv to $shell_rc"
    fi

    # Install Python version
    if ! pyenv versions --bare 2>/dev/null | grep -q "^${PYTHON_VERSION}"; then
        info "Installing Python $PYTHON_VERSION via pyenv (this may take a few minutes)..."
        pyenv install "$PYTHON_VERSION"
    fi

    pyenv shell "$PYTHON_VERSION"
}

PYTHON_CMD=$(find_python) || true

if [[ -z "$PYTHON_CMD" ]]; then
    echo ""
    warn "  Python $PYTHON_VERSION is required but was not found."
    echo ""

    # Check network before offering install
    check_network

    echo "  How would you like to install Python $PYTHON_VERSION?"
    echo ""
    echo "    [1] Install automatically with pyenv (recommended)"
    echo "    [2] I'll install it myself"
    echo ""

    if [[ -n "$WSL_DISTRO_NAME" ]]; then
        echo "    [3] Exit — I'll run from Windows instead (run.bat)"
        echo ""
    fi

    read -rp "  Choose [1/2$([ -n "$WSL_DISTRO_NAME" ] && echo '/3')]: " choice
    echo ""

    case "$choice" in
        1)
            install_python_pyenv
            PYTHON_CMD=$(find_python) || true
            if [[ -z "$PYTHON_CMD" ]]; then
                err "  Python $PYTHON_VERSION still not found after install."
                echo "  Try opening a new terminal and rerunning: ./run.sh"
                exit 1
            fi
            ;;
        3)
            info "  Run from Windows with: run.bat"
            exit 0
            ;;
        *)
            echo "  Install Python $PYTHON_VERSION using one of these methods:"
            echo ""
            echo "    pyenv:              pyenv install $PYTHON_VERSION && pyenv global $PYTHON_VERSION"
            echo "    Official installer: https://www.python.org/downloads/"
            if [[ -n "$WSL_DISTRO_NAME" ]]; then
                echo "    Windows native:     run.bat (from PowerShell or cmd)"
            fi
            echo ""
            echo "  Then rerun: ./run.sh"
            exit 1
            ;;
    esac
fi

ok "  Python: $PYTHON_CMD ($($PYTHON_CMD --version))"

# -------------------------------------------------------
# Step 3: Create venv (or recreate if from a different platform)
# -------------------------------------------------------
if [[ -d "$VENV_DIR/Scripts" && ! -d "$VENV_DIR/bin" ]]; then
    echo ""
    warn "  Existing virtual environment was created on Windows and is"
    warn "  incompatible with $(uname -s). It needs to be recreated."
    echo ""
    read -rp "  Recreate venv? [Y/n]: " venv_choice
    if [[ "$venv_choice" =~ ^[nN] ]]; then
        echo "  Aborted. Remove .venv manually or run from Windows instead."
        exit 1
    fi
    info "  Recreating venv for $(uname -s)..."
    rm -rf "$VENV_DIR"
fi
if [[ ! -f "$VENV_PYTHON" ]]; then
    info "  Creating virtual environment..."
    "$PYTHON_CMD" -m venv "$VENV_DIR"
    rm -f "$MARKER"
fi

source "$VENV_ACTIVATE"
ok "  Venv: $VENV_DIR"

# -------------------------------------------------------
# Step 4: Install dependencies (skip if up to date)
# -------------------------------------------------------
MARKER="$VENV_DIR/.deps_installed"
if [[ ! -f "$MARKER" || "$REQUIREMENTS" -nt "$MARKER" ]]; then
    echo ""
    info "  Dependencies need to be installed from $REQUIREMENTS."
    echo ""
    read -rp "  Install now? [Y/n]: " deps_choice
    if [[ "$deps_choice" =~ ^[nN] ]]; then
        echo "  Skipped. Run again when ready."
        exit 1
    fi
    info "  Installing dependencies..."

    # Install system libraries on Linux
    if [[ "$PLATFORM" == "posix" ]] && command -v apt &>/dev/null; then
        # Core dependencies (all Linux with apt)
        sys_deps=()
        for pkg in libgl1 libegl1 libxkbcommon0 libdbus-1-3 libportaudio2; do
            if ! dpkg -s "$pkg" &>/dev/null 2>&1; then
                sys_deps+=("$pkg")
            fi
        done

        # Additional X11/Wayland deps needed for Qt on WSL
        if [[ -n "$WSL_DISTRO_NAME" ]]; then
            for pkg in libxcb-cursor0 libxcb-xinerama0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxkbcommon-x11-0; do
                if ! dpkg -s "$pkg" &>/dev/null 2>&1; then
                    sys_deps+=("$pkg")
                fi
            done
        fi

        if [[ ${#sys_deps[@]} -gt 0 ]]; then
            info "  Installing system dependencies: ${sys_deps[*]}"
            sudo apt update -qq
            sudo apt install -y -qq "${sys_deps[@]}"
        fi
    fi

    # Use --only-binary for PyQt6 to avoid building from source (needs qmake)
    # Show progress (no -q) so the user can see what's happening
    pip install --only-binary=PyQt6 --progress-bar on -r "$REQUIREMENTS" --disable-pip-version-check
    touch "$MARKER"
else
    ok "  Dependencies: up to date"
fi

# -------------------------------------------------------
# Step 5: Launch
# -------------------------------------------------------

# Check display server on Linux
if [[ "$PLATFORM" == "posix" ]]; then
    if [[ -z "$DISPLAY" && -z "$WAYLAND_DISPLAY" ]]; then
        err "  No display server detected."
        echo ""
        if [[ -n "$WSL_DISTRO_NAME" ]]; then
            echo "  WSL requires Windows 11 with WSLg for GUI apps."
            echo "  Alternatives:"
            echo ""
            echo "    1. Run natively on Windows: run.bat (recommended)"
            echo "    2. Update WSL:  wsl --update  (from PowerShell)"
            echo "    3. Install VcXsrv on Windows and set:"
            echo "       export DISPLAY=\$(cat /etc/resolv.conf | grep nameserver | awk '{print \$2}'):0"
        else
            echo "  A display server (X11 or Wayland) is required for the GUI."
        fi
        echo ""
        exit 1
    fi
fi

# Auto-select Qt platform on WSL (xcb is more reliable than wayland under WSLg)
if [[ -n "$WSL_DISTRO_NAME" && -z "$QT_QPA_PLATFORM" ]]; then
    if [[ -n "$DISPLAY" ]]; then
        export QT_QPA_PLATFORM=xcb
    elif [[ -n "$WAYLAND_DISPLAY" ]]; then
        export QT_QPA_PLATFORM=wayland
    fi
fi

echo ""
ok "  Starting Parrot.py GUI..."
echo ""
python -m gui
EXIT_CODE=$?

if [[ $EXIT_CODE -ne 0 ]]; then
    echo ""
    err "  The application failed to start."
    echo ""
    echo "    [1] Reinstall dependencies and retry"
    echo "    [2] Recreate venv from scratch and retry"
    echo "    [3] Exit"
    echo ""
    read -rp "  Choose [1/2/3]: " err_choice

    case "$err_choice" in
        1)
            info "  Reinstalling dependencies..."
            echo ""
            rm -f "$MARKER"
            pip install --only-binary=PyQt6 --progress-bar on -r "$REQUIREMENTS" --disable-pip-version-check
            if [[ $? -eq 0 ]]; then
                touch "$MARKER"
                echo ""
                info "  Retrying launch..."
                echo ""
                python -m gui
            fi
            ;;
        2)
            info "  Recreating venv from scratch..."
            rm -rf "$VENV_DIR"
            "$PYTHON_CMD" -m venv "$VENV_DIR"
            source "$VENV_ACTIVATE"
            info "  Installing dependencies..."
            echo ""
            pip install --only-binary=PyQt6 --progress-bar on -r "$REQUIREMENTS" --disable-pip-version-check
            if [[ $? -eq 0 ]]; then
                touch "$MARKER"
                echo ""
                info "  Retrying launch..."
                echo ""
                python -m gui
            fi
            ;;
        *)
            exit $EXIT_CODE
            ;;
    esac
fi
