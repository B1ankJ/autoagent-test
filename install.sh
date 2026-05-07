#!/usr/bin/env bash
set -euo pipefail

# ── colours ─────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
fail() { echo -e "${RED}✗${NC} $*" >&2; exit 1; }

check_or_install_brew() {
    if command -v brew &>/dev/null; then
        ok "Homebrew already installed"
        return
    fi
    echo "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Find brew regardless of install prefix and add to PATH
    local brew_bin
    brew_bin="$(find /opt/homebrew/bin /usr/local/bin /home/linuxbrew/.linuxbrew/bin -name brew 2>/dev/null | head -1)"
    if [[ -z "$brew_bin" ]]; then
        fail "Homebrew installed but 'brew' not found in expected locations. Add brew to your PATH manually and re-run."
    fi
    eval "$("$brew_bin" shellenv)"
    ok "Homebrew installed"
}

brew_install() {
    local pkg="$1"
    if brew list --formula "$pkg" &>/dev/null; then
        ok "$pkg already installed"
    else
        echo "Installing $pkg via Homebrew..."
        brew install "$pkg"
        ok "$pkg installed"
    fi
}

# ── macOS system deps ────────────────────────────────────────────────────────
install_macos() {
    echo -e "\n[macOS] Installing system dependencies...\n"
    check_or_install_brew
    brew_install python@3.11
    brew_install node
    brew_install android-platform-tools

    # Ensure python3.11 is on PATH (brew links may vary)
    if ! command -v python3.11 &>/dev/null; then
        export PATH="$(brew --prefix python@3.11)/bin:$PATH"
    fi
}

# ── Linux system deps ────────────────────────────────────────────────────────
install_linux() {
    echo -e "\n[Linux] Installing system dependencies...\n"

    # Check sudo
    if ! sudo -n true 2>/dev/null && ! sudo -v 2>/dev/null; then
        fail "sudo access required to install system packages. Aborting."
    fi

    if command -v apt-get &>/dev/null; then
        echo "Detected Debian/Ubuntu — using apt"
        sudo apt-get update -qq
        # Add deadsnakes PPA if python3.11 is not available in default repos
        if ! apt-cache show python3.11 &>/dev/null; then
            echo "python3.11 not in default apt repos — adding deadsnakes PPA..."
            sudo apt-get install -y software-properties-common
            sudo add-apt-repository -y ppa:deadsnakes/ppa
            sudo apt-get update -qq
        fi
        sudo apt-get install -y python3.11 python3.11-venv nodejs npm adb
        ok "apt packages installed"
    elif command -v dnf &>/dev/null; then
        echo "Detected RHEL/Fedora — using dnf"
        sudo dnf install -y python3.11 nodejs npm android-tools
        ok "dnf packages installed"
    elif command -v yum &>/dev/null; then
        echo "Detected older RHEL — using yum"
        sudo yum install -y python3.11 nodejs npm android-tools
        ok "yum packages installed"
    else
        fail "Unsupported Linux distribution. Install python3.11, nodejs, npm, and adb manually, then re-run."
    fi
}

# ── uv ───────────────────────────────────────────────────────────────────────
install_uv() {
    if command -v uv &>/dev/null; then
        ok "uv already installed ($(uv --version))"
        return
    fi
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Add uv to PATH for this session
    export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
    ok "uv installed"
}

# ── pnpm ─────────────────────────────────────────────────────────────────────
install_pnpm() {
    if command -v pnpm &>/dev/null; then
        ok "pnpm already installed ($(pnpm --version))"
        return
    fi
    echo "Installing pnpm..."
    # corepack ships with Node 16.9+; prefer it over npm -g to avoid permission issues
    if command -v corepack &>/dev/null; then
        corepack enable pnpm
    else
        npm install -g pnpm
    fi
    ok "pnpm installed"
}

# ── main ─────────────────────────────────────────────────────────────────────
main() {
    echo ""
    echo "╔══════════════════════════════════╗"
    echo "║   AutoAgent Test — Installer     ║"
    echo "╚══════════════════════════════════╝"
    echo ""

    OS="$(uname -s)"
    case "$OS" in
        Darwin) install_macos ;;
        Linux)  install_linux ;;
        *)      fail "Unsupported OS: $OS" ;;
    esac

    install_uv
    install_pnpm

    echo -e "\n[Python setup]\n"
    if ! command -v python3.11 &>/dev/null; then
        fail "python3.11 not found after install. Check your PATH or install Python 3.11 manually."
    fi
    python3.11 scripts/setup.py
}

main "$@"
