#!/usr/bin/env bash
set -e

PYTHON_VERSION="3.13"
VENV_DIR=".venv"

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
find_python() {
    for cmd in "python${PYTHON_VERSION}" "python3" "python"; do
        if command -v "$cmd" &>/dev/null; then
            version=$("$cmd" --version 2>&1 | grep -oP '\d+\.\d+')
            if [[ "$version" == "$PYTHON_VERSION" ]]; then
                echo "$cmd"
                return 0
            fi
        fi
    done
    # Also check pyenv shims
    if command -v pyenv &>/dev/null; then
        if pyenv versions --bare 2>/dev/null | grep -q "^${PYTHON_VERSION}"; then
            pyenv shell "$PYTHON_VERSION" 2>/dev/null
            cmd=$(pyenv which python 2>/dev/null) || true
            if [[ -n "$cmd" ]]; then
                echo "$cmd"
                return 0
            fi
        fi
    fi
    return 1
}

install_python_pyenv() {
    # Install pyenv if missing
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

        # Persist to shell config
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
# Step 3: Create venv
# -------------------------------------------------------
if [[ ! -f "$VENV_PYTHON" ]]; then
    info "  Creating virtual environment..."
    "$PYTHON_CMD" -m venv "$VENV_DIR"
fi

source "$VENV_ACTIVATE"
ok "  Venv: $VENV_DIR"

# -------------------------------------------------------
# Step 4: Install dependencies (skip if up to date)
# -------------------------------------------------------
MARKER="$VENV_DIR/.deps_installed"
if [[ ! -f "$MARKER" || "$REQUIREMENTS" -nt "$MARKER" ]]; then
    info "  Installing dependencies from $REQUIREMENTS..."
    pip install --upgrade pip -q

    # Install Qt6 system libraries on Linux (needed by PyQt6)
    if [[ "$PLATFORM" == "posix" ]] && command -v apt &>/dev/null; then
        if ! dpkg -s libgl1 &>/dev/null 2>&1 || ! dpkg -s libegl1 &>/dev/null 2>&1; then
            info "  Installing Qt6 system dependencies..."
            sudo apt install -y -qq libgl1 libegl1 libxkbcommon0 libdbus-1-3 2>/dev/null || true
        fi
    fi

    # Use --only-binary for PyQt6 to avoid building from source (needs qmake)
    pip install --only-binary=PyQt6 -r "$REQUIREMENTS" -q
    touch "$MARKER"
else
    ok "  Dependencies: up to date"
fi

# -------------------------------------------------------
# Step 5: Launch
# -------------------------------------------------------
echo ""
ok "  Starting Parrot.py GUI..."
echo ""
python -m gui
