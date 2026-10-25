#!/usr/bin/env bash
set -e

PYTHON_VERSION="3.13"
VENV_DIR=".venv"

# Prebuilt relocatable CPython (python-build-standalone, maintained by Astral).
# Deliberately PINNED rather than resolved to "latest" via the GitHub API: the
# API is rate-limited to 60 req/hr per IP (a shared NAT could fail to bootstrap
# at all), and a pin means every install gets the same interpreter. Bump these
# together with run.bat.
PBS_REPO="astral-sh/python-build-standalone"
PBS_TAG="20260718"
PBS_PY="3.13.14"

# -------------------------------------------------------
# Git Bash / MINGW detection - redirect to run.bat
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
    VENV_ACTIVATE="$VENV_DIR/Scripts/activate"
else
    PLATFORM="posix"
    REQUIREMENTS="requirements-posix.txt"
    VENV_ACTIVATE="$VENV_DIR/bin/activate"
fi

# Detect OS family within posix. macOS must never take the apt/dpkg path:
# /usr/bin/apt on macOS is Apple's stub launcher for the *Java* annotation
# tool, so `sudo apt install` fails with "Unable to locate a Java Runtime".
if [[ "$OSTYPE" == darwin* ]]; then
    OS_FAMILY="macos"
elif [[ -n "$WSL_DISTRO_NAME" ]]; then
    OS_FAMILY="wsl"
else
    OS_FAMILY="linux"
fi

# Where the self-contained interpreter is cached. User-level rather than
# project-local: it survives fresh clones, and an installed bundle is read-only
# so it cannot store a Python inside itself. Override with PARROT_PYTHON_DIR.
resolve_python_dir() {
    if [[ -n "$PARROT_PYTHON_DIR" ]]; then
        echo "$PARROT_PYTHON_DIR"
    elif [[ "$OS_FAMILY" == "macos" ]]; then
        echo "$HOME/Library/Application Support/parrot.py/python/$PYTHON_VERSION"
    else
        echo "${XDG_DATA_HOME:-$HOME/.local/share}/parrot.py/python/$PYTHON_VERSION"
    fi
}

PYTHON_DIR="$(resolve_python_dir)"

# python-build-standalone's platform triple for this machine
pbs_platform() {
    local arch
    arch=$(uname -m)
    case "$OS_FAMILY" in
        macos)
            case "$arch" in
                arm64|aarch64) echo "aarch64-apple-darwin" ;;
                x86_64)        echo "x86_64-apple-darwin" ;;
            esac
            ;;
        linux|wsl)
            case "$arch" in
                x86_64)        echo "x86_64-unknown-linux-gnu" ;;
                aarch64|arm64) echo "aarch64-unknown-linux-gnu" ;;
            esac
            ;;
    esac
}

# Only trust apt if it's a real Debian apt, not the macOS Java stub
has_apt() {
    [[ "$OS_FAMILY" != "macos" ]] && command -v apt &>/dev/null && command -v dpkg &>/dev/null
}

brew_prefix() {
    if command -v brew &>/dev/null; then
        brew --prefix
    elif [[ -x /opt/homebrew/bin/brew ]]; then
        echo "/opt/homebrew"
    elif [[ -x /usr/local/bin/brew ]]; then
        echo "/usr/local"
    fi
}

load_brew() {
    if ! command -v brew &>/dev/null; then
        local prefix
        prefix=$(brew_prefix)
        if [[ -n "$prefix" && -x "$prefix/bin/brew" ]]; then
            eval "$("$prefix/bin/brew" shellenv)"
        fi
    fi
    # Must return 0: a bare `[[ ]] && cmd` tail would return 1 when brew is
    # absent, and `set -e` would kill the script with no output at all.
    return 0
}

# -------------------------------------------------------
# Step 1: Check network connectivity (needed for installs)
# -------------------------------------------------------
check_network() {
    if ! curl -s --max-time 5 https://pypi.org > /dev/null 2>&1; then
        # macOS ping takes -W in milliseconds; use -t (deadline in seconds) there
        if [[ "$OS_FAMILY" == "macos" ]]; then
            PING_TIMEOUT=(-t 3)
        else
            PING_TIMEOUT=(-W 3)
        fi
        if ! ping -c 1 "${PING_TIMEOUT[@]}" 8.8.8.8 > /dev/null 2>&1; then
            err "No network connectivity detected."
            echo ""
            if [[ "$OS_FAMILY" == "macos" ]]; then
                echo "  Check your Wi-Fi / Ethernet connection, then rerun: ./run.sh"
            else
                echo "  If you're on WSL, this is often a DNS issue. Try:"
                echo ""
                echo "    echo \"nameserver 8.8.8.8\" | sudo tee /etc/resolv.conf"
                echo ""
                echo "  Then rerun: ./run.sh"
            fi
            exit 1
        else
            err "Network is reachable but DNS resolution is failing."
            echo ""
            if [[ "$OS_FAMILY" == "macos" ]]; then
                echo "  Check your DNS settings in System Settings > Network,"
                echo "  then rerun: ./run.sh"
            else
                echo "  Fix DNS by running:"
                echo ""
                echo "    echo \"nameserver 8.8.8.8\" | sudo tee /etc/resolv.conf"
                echo ""
                echo "  Then rerun: ./run.sh"
            fi
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
    # Our own cached self-contained interpreter wins - it's the one we manage
    if [[ -x "$PYTHON_DIR/bin/python${PYTHON_VERSION}" ]]; then
        echo "$PYTHON_DIR/bin/python${PYTHON_VERSION}"
        return 0
    fi

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

    # Check Homebrew prefixes directly - brew may not be on PATH yet in this shell
    if [[ "$OS_FAMILY" == "macos" ]]; then
        for prefix in "$(brew_prefix)" /opt/homebrew /usr/local; do
            [[ -z "$prefix" ]] && continue
            local brew_bin="$prefix/bin/python${PYTHON_VERSION}"
            if [[ -x "$brew_bin" ]]; then
                echo "$brew_bin"
                return 0
            fi
        done
    fi

    # Check standard system commands (avoid pyenv shims - they can error)
    for cmd in "python${PYTHON_VERSION}" "python3" "python"; do
        local cmd_path
        cmd_path=$(command -v "$cmd" 2>/dev/null) || continue
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

    if ! command -v pyenv &>/dev/null; then
        info "Installing pyenv..."
        echo ""

        if [[ "$OS_FAMILY" == "macos" ]]; then
            load_brew
            if ! command -v brew &>/dev/null; then
                err "  Homebrew is required to build Python with pyenv on macOS."
                echo ""
                echo "  Install Homebrew first:"
                echo ""
                echo "    /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
                echo ""
                echo "  Then rerun: ./run.sh"
                exit 1
            fi
            local missing_deps=()
            for pkg in openssl readline sqlite3 xz zlib; do
                if ! brew list --formula "$pkg" &>/dev/null; then
                    missing_deps+=("$pkg")
                fi
            done
            if [[ ${#missing_deps[@]} -gt 0 ]]; then
                info "Installing build dependencies: ${missing_deps[*]}"
                brew install "${missing_deps[@]}"
            fi
        elif has_apt; then
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

    if ! pyenv versions --bare 2>/dev/null | grep -q "^${PYTHON_VERSION}"; then
        info "Installing Python $PYTHON_VERSION via pyenv (this may take a few minutes)..."
        pyenv install "$PYTHON_VERSION"
    fi

    pyenv shell "$PYTHON_VERSION"
}

# Download URL for the pinned prebuilt Python. PARROT_PYTHON_URL overrides it
# (useful for testing a different build or an internal mirror).
pbs_url() {
    local plat="$1"
    if [[ -n "$PARROT_PYTHON_URL" ]]; then
        echo "$PARROT_PYTHON_URL"
    else
        echo "https://github.com/$PBS_REPO/releases/download/${PBS_TAG}/cpython-${PBS_PY}+${PBS_TAG}-${plat}-install_only.tar.gz"
    fi
}

# Download a self-contained, relocatable CPython into PYTHON_DIR. No sudo and
# nothing outside PYTHON_DIR: a GUI progress window cannot answer a sudo
# password prompt.
install_python_standalone() {
    local plat url tmp
    plat=$(pbs_platform)

    if [[ -z "$plat" ]]; then
        err "  No prebuilt Python is available for $(uname -s) $(uname -m)."
        echo "  Choose the pyenv or manual option instead."
        return 1
    fi

    url=$(pbs_url "$plat")
    tmp="${TMPDIR:-/tmp}/parrot-python-$$"
    rm -rf "$tmp"
    mkdir -p "$tmp"

    echo ""
    info "  Downloading a self-contained Python $PYTHON_VERSION (~25 MB, no admin password needed)..."
    if ! curl -fL --progress-bar --max-time 300 "$url" -o "$tmp/python.tar.gz"; then
        err "  Download failed."
        echo "  URL: $url"
        rm -rf "$tmp"
        return 1
    fi

    info "  Extracting..."
    if ! tar -xzf "$tmp/python.tar.gz" -C "$tmp"; then
        err "  Could not extract the archive."
        rm -rf "$tmp"
        return 1
    fi

    # Archive contains a single top-level python/ directory
    if [[ ! -x "$tmp/python/bin/python${PYTHON_VERSION}" ]]; then
        err "  Unexpected archive layout — no bin/python${PYTHON_VERSION} inside."
        rm -rf "$tmp"
        return 1
    fi

    rm -rf "$PYTHON_DIR"
    mkdir -p "$(dirname "$PYTHON_DIR")"
    mv "$tmp/python" "$PYTHON_DIR"
    rm -rf "$tmp"

    ok "  Installed to $PYTHON_DIR"
    return 0
}

PYTHON_CMD=$(find_python) || true

if [[ -z "$PYTHON_CMD" ]]; then
    echo ""
    warn "  Python $PYTHON_VERSION is required but was not found."
    echo ""

    check_network

    echo "  How would you like to install Python $PYTHON_VERSION?"
    echo ""
    echo "    [1] Download a self-contained Python (recommended)"
    echo "        ~25 MB, no admin password, nothing installed system-wide"
    echo "    [2] Build from source with pyenv (slower, needs a compiler)"
    echo "    [3] I'll install it myself"
    if [[ -n "$WSL_DISTRO_NAME" ]]; then
        echo "    [4] Exit — I'll run from Windows instead (run.bat)"
    fi
    echo ""

    if [[ -n "$WSL_DISTRO_NAME" ]]; then
        read -rp "  Choose [1/2/3/4] (default 1): " choice
    else
        read -rp "  Choose [1/2/3] (default 1): " choice
    fi
    echo ""

    installed=false
    case "${choice:-1}" in
        1)
            if install_python_standalone; then
                installed=true
            else
                exit 1
            fi
            ;;
        2)
            install_python_pyenv
            installed=true
            ;;
        4)
            if [[ -n "$WSL_DISTRO_NAME" ]]; then
                info "  Run from Windows with: run.bat"
                exit 0
            fi
            ;;
    esac

    if [[ "$installed" == true ]]; then
        PYTHON_CMD=$(find_python) || true
        if [[ -z "$PYTHON_CMD" ]]; then
            err "  Python $PYTHON_VERSION still not found after install."
            echo "  Try opening a new terminal and rerunning: ./run.sh"
            exit 1
        fi
    else
        echo "  Install Python $PYTHON_VERSION using one of these methods:"
        echo ""
        echo "    pyenv:              pyenv install $PYTHON_VERSION && pyenv global $PYTHON_VERSION"
        echo "    Official installer: https://www.python.org/downloads/"
        if [[ "$OS_FAMILY" == "macos" ]]; then
            echo "    Homebrew:           brew install python@$PYTHON_VERSION"
        fi
        if [[ -n "$WSL_DISTRO_NAME" ]]; then
            echo "    Windows native:     run.bat (from PowerShell or cmd)"
        fi
        echo ""
        echo "  Then rerun: ./run.sh"
        exit 1
    fi
fi

ok "  Python: $PYTHON_CMD ($("$PYTHON_CMD" --version))"

# -------------------------------------------------------
# Step 3: Discard a venv built for a different platform
# -------------------------------------------------------
MARKER="$VENV_DIR/.deps_installed"

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

# -------------------------------------------------------
# Step 4: Hand venv creation + dependency install to bootstrap.py
#
# bootstrap.py owns this so the logic lives once instead of here and in
# run.bat. Its progress window is stdlib tkinter (works before PyQt6 exists);
# it falls back to plain text when there's no display, or with --console.
# -------------------------------------------------------
if ! "$PYTHON_CMD" bootstrap.py --check; then
    # No prompt: they launched the app, and setup is what launching costs the
    # first time. The setup window lists what it is doing and has Cancel.
    echo ""
    info "  Launching setup..."
    echo ""

    # Linux system libraries Qt and PortAudio link against. Must happen before
    # pip runs. macOS needs none of these: the sounddevice wheel bundles
    # PortAudio and PyQt6 ships its own Qt frameworks.
    if [[ "$PLATFORM" == "posix" ]] && has_apt; then
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

    set +e
    "$PYTHON_CMD" bootstrap.py "$@"
    bootstrap_code=$?
    set -e
    if [[ $bootstrap_code -ne 0 ]]; then
        echo ""
        if [[ $bootstrap_code -eq 2 ]]; then
            warn "  Setup cancelled."
        else
            err "  Setup failed."
        fi
        exit $bootstrap_code
    fi
else
    ok "  Dependencies: up to date"
fi

source "$VENV_ACTIVATE"
ok "  Venv: $VENV_DIR"

# -------------------------------------------------------
# Step 5: Launch
# -------------------------------------------------------

# Check display server on Linux. macOS has no DISPLAY/WAYLAND_DISPLAY - Qt uses
# the native Cocoa backend, so this check must not run there.
if [[ "$PLATFORM" == "posix" && "$OS_FAMILY" != "macos" ]]; then
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
            set +e
            "$PYTHON_CMD" bootstrap.py "$@"
            retry_code=$?
            set -e
            if [[ $retry_code -eq 0 ]]; then
                source "$VENV_ACTIVATE"
                echo ""
                info "  Retrying launch..."
                echo ""
                python -m gui
            fi
            ;;
        2)
            info "  Recreating venv from scratch..."
            rm -rf "$VENV_DIR"
            set +e
            "$PYTHON_CMD" bootstrap.py "$@"
            retry_code=$?
            set -e
            if [[ $retry_code -eq 0 ]]; then
                source "$VENV_ACTIVATE"
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
