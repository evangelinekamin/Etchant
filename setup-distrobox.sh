#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${ETCHANT_REPO_DIR:-$SCRIPT_DIR}"

CONTAINER_NAME="${ETCHANT_DISTROBOX_NAME:-etchant-dev}"
IMAGE="${ETCHANT_DISTROBOX_IMAGE:-docker.io/library/ubuntu:24.04}"
CONTAINER_HOME="${ETCHANT_DISTROBOX_HOME:-$HOME/.local/share/etchant/distrobox-home}"
VENV_DIR="${ETCHANT_DISTROBOX_VENV:-$REPO_DIR/.venv-distrobox}"

install_distrobox_if_needed() {
    if command -v distrobox >/dev/null 2>&1; then
        return
    fi

    if command -v apt-get >/dev/null 2>&1 && command -v sudo >/dev/null 2>&1; then
        echo "distrobox not found. Installing distrobox with apt..."
        sudo apt-get update
        sudo apt-get install -y distrobox
        return
    fi

    echo "distrobox is required for full KiCad/pcbnew output." >&2
    echo "Install distrobox and either podman or docker, then rerun this script." >&2
    exit 1
}

install_distrobox_if_needed

if ! command -v podman >/dev/null 2>&1 && ! command -v docker >/dev/null 2>&1; then
    echo "Neither podman nor docker is available. Install one before creating the distrobox." >&2
    exit 1
fi

mkdir -p "$CONTAINER_HOME"

echo "=== Etchant Development Environment Setup ==="
echo "Container: $CONTAINER_NAME"
echo "Base image: $IMAGE"
echo "Repo: $REPO_DIR"
echo "Container home: $CONTAINER_HOME"
echo "Python env: $VENV_DIR"
echo ""

container_exists() {
    distrobox list 2>/dev/null \
        | awk -F'|' 'NR > 1 {gsub(/^[ \t]+|[ \t]+$/, "", $2); print $2}' \
        | grep -Fxq "$CONTAINER_NAME"
}

# Create the distrobox container
if container_exists; then
    echo "Container '$CONTAINER_NAME' already exists. Entering to update..."
else
    echo "Creating container '$CONTAINER_NAME'..."
    distrobox create \
        --name "$CONTAINER_NAME" \
        --image "$IMAGE" \
        --yes \
        --home "$CONTAINER_HOME" \
        --volume "$REPO_DIR:$REPO_DIR:rw" \
        --additional-packages "software-properties-common ca-certificates curl git sudo"
fi

# Install all dependencies inside the container
distrobox enter "$CONTAINER_NAME" -- bash -s -- "$REPO_DIR" "$VENV_DIR" <<'IN_CONTAINER'
    set -euo pipefail

    REPO_DIR="$1"
    VENV_DIR="$2"

    echo "--- Installing system packages ---"

    # Add KiCad PPA for KiCad 9
    if ! grep -Rqs "kicad-9.0-releases" /etc/apt/sources.list /etc/apt/sources.list.d; then
        sudo add-apt-repository -y ppa:kicad/kicad-9.0-releases
    fi
    sudo apt-get update

    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        kicad \
        kicad-symbols \
        kicad-footprints \
        kicad-templates \
        python3-pip \
        python3-venv \
        python3-dev \
        ngspice \
        libngspice0-dev \
        build-essential

    echo "--- Installing uv ---"
    if ! command -v uv &>/dev/null; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.local/bin:$PATH"
    fi

    echo "--- Setting up KiCad environment variables ---"
    KICAD_SYMBOL_DIR="/usr/share/kicad/symbols"
    KICAD_FOOTPRINT_DIR="/usr/share/kicad/footprints"

    quote_for_shell() {
        printf "%q" "$1"
    }

    sudo tee /etc/profile.d/etchant.sh >/dev/null << ENVEOF
# Etchant KiCad/SKiDL environment
export ETCHANT_REPO_DIR=$(quote_for_shell "$REPO_DIR")
export UV_PROJECT_ENVIRONMENT=$(quote_for_shell "$VENV_DIR")
export UV_PYTHON=/usr/bin/python3
export UV_PYTHON_DOWNLOADS=never
export UV_LINK_MODE=copy
export KICAD_SYMBOL_DIR=$(quote_for_shell "$KICAD_SYMBOL_DIR")
export KICAD8_FOOTPRINT_DIR=$(quote_for_shell "$KICAD_FOOTPRINT_DIR")
export KICAD9_FOOTPRINT_DIR=$(quote_for_shell "$KICAD_FOOTPRINT_DIR")
export KICAD_FOOTPRINT_DIR=$(quote_for_shell "$KICAD_FOOTPRINT_DIR")
ENVEOF

    export ETCHANT_REPO_DIR="$REPO_DIR"
    export UV_PROJECT_ENVIRONMENT="$VENV_DIR"
    export UV_PYTHON=/usr/bin/python3
    export UV_PYTHON_DOWNLOADS=never
    export UV_LINK_MODE=copy
    export KICAD_SYMBOL_DIR
    export KICAD8_FOOTPRINT_DIR="$KICAD_FOOTPRINT_DIR"
    export KICAD9_FOOTPRINT_DIR="$KICAD_FOOTPRINT_DIR"
    export KICAD_FOOTPRINT_DIR="$KICAD_FOOTPRINT_DIR"

    echo "--- Installing project dependencies ---"
    cd "$REPO_DIR"
    if [ ! -d "$VENV_DIR" ] || ! grep -q "include-system-site-packages = true" "$VENV_DIR/pyvenv.cfg" 2>/dev/null; then
        rm -rf "$VENV_DIR"
        uv venv --python /usr/bin/python3 --system-site-packages "$VENV_DIR"
    fi
    VIRTUAL_ENV="$VENV_DIR" PATH="$VENV_DIR/bin:$PATH" uv sync --active --all-extras

    echo "--- Patching SKiDL circular import bug ---"
    uv run python scripts/patch_skidl.py

    echo "--- Verifying KiCad Python bindings ---"
    uv run python - <<'PY'
import pcbnew

version = getattr(pcbnew, "GetBuildVersion", pcbnew.Version)()
print(f"pcbnew: {version}")
PY

    echo ""
    echo "=== Setup complete ==="
    echo "KiCad symbols: $KICAD_SYMBOL_DIR"
    echo "KiCad footprints: $KICAD_FOOTPRINT_DIR"
    echo "Project env: $UV_PROJECT_ENVIRONMENT"
    echo ""
    echo "Verify with:"
    echo "  uv run pytest tests/ -q"
    echo "  uv run etchant --help"
IN_CONTAINER

echo ""
echo "Container '$CONTAINER_NAME' is ready."
echo "Enter with: distrobox enter $CONTAINER_NAME"
echo "Then: cd $REPO_DIR && uv run pytest tests/ -q"
