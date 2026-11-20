# Etchant

Etchant is an experimental PCB design agent. The current repo can generate
structured circuit designs, pick JLCPCB-oriented parts, export JSON/BOM files,
and, when KiCad is available, build KiCad board artifacts.

## Quick Start

Install Python dependencies with `uv`:

```bash
uv sync --all-extras
uv run pytest tests/ -q
uv run etchant topologies
```

This path is intentionally lightweight. It covers the agent tooling, circuit
generators, BOM/JLCPCB logic, JSON/CSV export, and most tests.

## Full KiCad Setup

KiCad's `pcbnew` Python module is a system package, not a pip package. For full
PCB artifact generation, use the distrobox bootstrap:

```bash
./setup-distrobox.sh
distrobox enter etchant-dev
cd "$ETCHANT_REPO_DIR"
uv run pytest tests/ -q
```

The bootstrap installs distrobox on apt-based hosts if it is missing, creates an
Ubuntu KiCad container, and uses `.venv-distrobox` so the container environment
does not overwrite the normal repo `.venv`.

Useful overrides:

```bash
ETCHANT_DISTROBOX_NAME=etchant-dev ./setup-distrobox.sh
ETCHANT_DISTROBOX_IMAGE=docker.io/library/ubuntu:24.04 ./setup-distrobox.sh
ETCHANT_DISTROBOX_VENV=/path/to/venv ./setup-distrobox.sh
```

## SPICE Verification

Etchant can electrically verify a generated design by simulating it with
[ngspice](https://ngspice.sourceforge.io/). Like `kicad-cli` and Freerouting,
ngspice is a system binary that Etchant shells out to, not a pip package.
Install it before running the simulation gate:

```bash
sudo apt-get install -y ngspice
ngspice --version
```

The `etchant.sim` package translates an adjustable buck converter into a
behavioural ngspice deck, runs it in batch mode, and checks the regulated
output voltage against the requested target. The runner raises a clear,
actionable error if the `ngspice` binary is not on `PATH`.

## Design Gauntlet

Run the seeded PCB idea gauntlet to see what Etchant can generate today and
what still needs topology/research work:

```bash
uv run python scripts/run_design_gauntlet.py
```

The default run writes JSON, BOM CSV, SVG previews, and a Markdown report under
`output/gauntlet`. Inside the KiCad distrobox, add `--full-pcb` to also attempt
KiCad project/board artifacts:

```bash
distrobox enter etchant-dev
cd "$ETCHANT_REPO_DIR"
uv run python scripts/run_design_gauntlet.py --full-pcb --case buck_12v_to_5v_2a
```

## Packaging Direction

Distrobox is the fast local path for Linux/WSL developers because it shares the
repo directory and behaves like a normal shell. For broad public support, the
better target is a Docker/devcontainer image that preinstalls the KiCad runtime
once and exposes the same commands to agents, CI, and MCP servers.

References:

- KiCad Ubuntu packages: https://www.kicad.org/download/details/ubuntu/
- KiCad Python bindings: https://dev-docs.kicad.org/en/apis-and-binding/pcbnew/
- Dev Containers: https://containers.dev/
- Distrobox: https://distrobox.it/

## Current Scope

The project is not yet a push-button replacement for an experienced PCB
designer. Treat generated boards as drafts that need human review, especially
for high-speed, RF, power, thermal, and safety-critical designs.
