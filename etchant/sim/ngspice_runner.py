"""Run an ngspice deck as a subprocess and parse node voltages.

Etchant shells out to the ``ngspice`` binary the same way it invokes
``kicad-cli`` (``etchant.kicad.pipeline``) and Freerouting
(``etchant.kicad.router``): no Python-level SPICE bindings are imported.

ngspice returns exit code 0 even when an operating point fails to converge and
reports the failure only on stdout, so results are validated by parsing the
output rather than by trusting the return code.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

_NGSPICE_BINARY = "ngspice"
_INSTALL_HINT = "sudo apt-get install -y ngspice"


class NgspiceError(RuntimeError):
    """Raised when ngspice is unavailable, times out, or fails to converge."""


@dataclass(frozen=True)
class SimulationResult:
    """Immutable result of an ngspice run: solved node voltages plus raw log."""

    node_voltages: Mapping[str, float]
    raw_output: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "node_voltages", MappingProxyType(dict(self.node_voltages))
        )

    def voltage(self, node: str) -> float:
        """Return the solved voltage at ``node`` (case-insensitive)."""
        return self.node_voltages[node.lower()]


def check_ngspice_available() -> bool:
    """True when the ngspice binary is discoverable on PATH."""
    return shutil.which(_NGSPICE_BINARY) is not None


def _require_ngspice() -> None:
    """Preflight: raise an actionable error if ngspice is not installed."""
    if not check_ngspice_available():
        raise NgspiceError(
            f"the '{_NGSPICE_BINARY}' binary is not on PATH. "
            f"Install it with: {_INSTALL_HINT}"
        )


def run_deck(
    deck: str,
    *,
    nodes: tuple[str, ...] = ("vout",),
    timeout: float = 30.0,
) -> SimulationResult:
    """Write ``deck`` to a temp file, run ngspice in batch mode, parse ``nodes``.

    Raises NgspiceError if ngspice is missing, exceeds ``timeout``, or does not
    emit a parseable voltage for every requested node (the tell-tale of a
    non-converging operating point).
    """
    _require_ngspice()

    with tempfile.TemporaryDirectory(prefix="etchant-spice-") as tmp:
        deck_path = Path(tmp) / "deck.cir"
        deck_path.write_text(deck)
        try:
            proc = subprocess.run(
                [_NGSPICE_BINARY, "-b", str(deck_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise NgspiceError(f"ngspice timed out after {timeout:g}s") from exc
        except FileNotFoundError as exc:  # binary vanished after preflight
            raise NgspiceError(
                f"failed to execute '{_NGSPICE_BINARY}': {exc}"
            ) from exc

    output = proc.stdout + proc.stderr
    voltages = _parse_node_voltages(output, nodes)
    return SimulationResult(node_voltages=voltages, raw_output=output)


def _parse_node_voltages(output: str, nodes: tuple[str, ...]) -> dict[str, float]:
    """Extract each requested node's ``v(node) = <float>`` from ngspice output."""
    voltages: dict[str, float] = {}
    for node in nodes:
        key = node.lower()
        match = re.search(
            rf"v\({re.escape(key)}\)\s*=\s*([-+0-9.eE]+)", output, re.IGNORECASE
        )
        if match is None:
            raise NgspiceError(
                f"could not read v({key}) from ngspice output; the operating "
                f"point may have failed to converge.\n"
                f"--- ngspice output (tail) ---\n{_tail(output)}"
            )
        voltages[key] = float(match.group(1))
    return voltages


def _tail(text: str, lines: int = 15) -> str:
    """Return the last ``lines`` non-empty-trimmed lines of ``text``."""
    return "\n".join(text.strip().splitlines()[-lines:])
