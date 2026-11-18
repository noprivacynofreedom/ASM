#!/usr/bin/env bash
set -euo pipefail

# Bootstrap a Linux machine (Debian/Ubuntu, Fedora, or Arch) for Atlas Chat
# development and Tauri builds. Skips any tool/library already installed.
# Pass --check to report status without installing anything.

CHECK_ONLY=0
if [[ "${1:-}" == "--check" ]]; then
    CHECK_ONLY=1
    echo "Running in --check mode (no packages will be installed)."
fi

detect_distro() {
    if command -v apt-get >/dev/null 2>&1; then
        echo "apt"
    elif command -v dnf >/dev/null 2>&1; then
        echo "dnf"
    elif command -v pacman >/dev/null 2>&1; then
        echo "pacman"
    else
        echo "unknown"
    fi
}

DISTRO="$(detect_distro)"
SUDO=""
if [[ "${EUID:-$(id -u)}" -ne 0 ]] && command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
fi

APT_UPDATED=0
install_pkg() {
    local label="$1"
    local apt_pkgs="$2"
    local dnf_pkgs="$3"
    local pacman_pkgs="$4"

    if [[ "$CHECK_ONLY" -eq 1 ]]; then
        echo "[MISSING] $label"
        return 0
    fi

    echo "[INSTALL] $label ($DISTRO)..."
    case "$DISTRO" in
        apt)
            if [[ "$APT_UPDATED" -eq 0 ]]; then
                $SUDO apt-get update
                APT_UPDATED=1
            fi
            # shellcheck disable=SC2086
            $SUDO apt-get install -y $apt_pkgs
            ;;
        dnf)
            # shellcheck disable=SC2086
            $SUDO dnf install -y $dnf_pkgs
            ;;
        pacman)
            # shellcheck disable=SC2086
            $SUDO pacman -S --needed --noconfirm $pacman_pkgs
            ;;
        *)
            echo "[WARN]    Unsupported package manager; install $label manually." >&2
            return 1
            ;;
    esac
}

# 1. git
if command -v git >/dev/null 2>&1; then
    echo "[SKIP]    git ($(command -v git))"
else
    install_pkg "git" "git" "git" "git"
fi

# 2. python3 + pip
if command -v python3 >/dev/null 2>&1; then
    echo "[SKIP]    python3 ($(command -v python3))"
else
    install_pkg "python3" "python3 python3-pip python3-venv" "python3 python3-pip" "python python-pip"
fi

if command -v python3 >/dev/null 2>&1 && python3 -m pip --version >/dev/null 2>&1; then
    echo "[SKIP]    pip (python3 -m pip)"
else
    install_pkg "pip" "python3-pip" "python3-pip" "python-pip"
fi

# 3. node / npm
if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    echo "[SKIP]    node ($(node -v))"
else
    install_pkg "node" "nodejs npm" "nodejs npm" "nodejs npm"
fi

# 4. rustc / cargo
if [[ -f "$HOME/.cargo/env" ]]; then
    # shellcheck disable=SC1091
    source "$HOME/.cargo/env"
fi
if command -v rustc >/dev/null 2>&1 && command -v cargo >/dev/null 2>&1; then
    echo "[SKIP]    rustc / cargo ($(rustc --version))"
else
    if [[ "$CHECK_ONLY" -eq 1 ]]; then
        echo "[MISSING] rustc / cargo"
    else
        echo "[INSTALL] rustc / cargo via rustup..."
        if ! command -v curl >/dev/null 2>&1; then
            install_pkg "curl" "curl" "curl" "curl"
        fi
        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
        # shellcheck disable=SC1091
        source "$HOME/.cargo/env"
    fi
fi

# 5. pkg-config & C build toolchain
if command -v pkg-config >/dev/null 2>&1 && command -v cc >/dev/null 2>&1; then
    echo "[SKIP]    pkg-config & C toolchain"
else
    install_pkg "pkg-config & build tools" \
        "pkg-config build-essential curl wget file libssl-dev" \
        "pkgconf-pkg-config gcc gcc-c++ make curl wget file openssl-devel" \
        "pkgconf base-devel curl wget file openssl"
fi

# 6. WebKitGTK (webkit2gtk-4.1 or 4.0) + Tauri GTK/AppIndicator deps
if command -v pkg-config >/dev/null 2>&1 && (pkg-config --exists webkit2gtk-4.1 || pkg-config --exists webkit2gtk-4.0); then
    echo "[SKIP]    WebKitGTK ($(pkg-config --exists webkit2gtk-4.1 && echo webkit2gtk-4.1 || echo webkit2gtk-4.0))"
else
    install_pkg "WebKitGTK & Tauri GTK deps" \
        "libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev libxdo-dev" \
        "webkit2gtk4.1-devel gtk3-devel libappindicator-gtk3-devel librsvg2-devel libxdo-devel" \
        "webkit2gtk-4.1 gtk3 libayatana-appindicator librsvg xdotool"
fi

# 7. Playwright + Chromium
if command -v python3 >/dev/null 2>&1; then
    if python3 -c "import playwright" >/dev/null 2>&1; then
        echo "[SKIP]    playwright (python3)"
    elif [[ "$CHECK_ONLY" -eq 1 ]]; then
        echo "[MISSING] playwright (python3 -m pip install playwright)"
    else
        echo "[INSTALL] playwright via pip..."
        python3 -m pip install --user playwright
    fi

    PW_CACHE="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}"
    if compgen -G "$PW_CACHE/chromium*" >/dev/null 2>&1; then
        echo "[SKIP]    playwright chromium ($PW_CACHE)"
    elif [[ "$CHECK_ONLY" -eq 1 ]]; then
        echo "[MISSING] playwright chromium"
    elif python3 -c "import playwright" >/dev/null 2>&1; then
        echo "[INSTALL] playwright chromium..."
        python3 -m playwright install chromium
    else
        echo "[WARN]    Skipping Chromium install because playwright is not importable."
    fi
fi

echo "Done."
