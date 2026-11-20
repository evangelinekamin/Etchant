"""Tests for the ngspice subprocess runner.

Preflight and parsing behaviour is tested without ngspice (via mocking); the
actual-simulation tests are skipped when the ngspice binary is not on PATH.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from etchant.sim.ngspice_runner import (
    NgspiceError,
    SimulationResult,
    check_ngspice_available,
    run_deck,
)

requires_ngspice = pytest.mark.skipif(
    not check_ngspice_available(), reason="ngspice binary not on PATH"
)

_OP_DECK = (
    "* op test\n"
    "Bout vout 0 V = max(0, min(12, 1e5*(0.8 - V(fb))))\n"
    "R1 vout fb 30000\n"
    "R2 fb 0 10000\n"
    "Rload vout 0 3.3\n"
    ".control\n"
    "op\n"
    "print v(vout)\n"
    ".endc\n"
    ".end\n"
)


class TestPreflight:
    def test_missing_binary_raises_with_install_hint(self) -> None:
        with (
            patch("etchant.sim.ngspice_runner.shutil.which", return_value=None),
            pytest.raises(NgspiceError) as exc,
        ):
            run_deck(_OP_DECK)
        message = str(exc.value).lower()
        assert "ngspice" in message
        assert "apt-get install" in message  # must be actionable

    def test_check_available_reflects_path(self) -> None:
        with patch(
            "etchant.sim.ngspice_runner.shutil.which", return_value=None
        ):
            assert check_ngspice_available() is False
        with patch(
            "etchant.sim.ngspice_runner.shutil.which",
            return_value="/usr/bin/ngspice",
        ):
            assert check_ngspice_available() is True

    def test_timeout_becomes_ngspice_error(self) -> None:
        timeout_exc = subprocess.TimeoutExpired(cmd="ngspice", timeout=0.01)
        with (
            patch(
                "etchant.sim.ngspice_runner.shutil.which",
                return_value="/usr/bin/ngspice",
            ),
            patch(
                "etchant.sim.ngspice_runner.subprocess.run",
                side_effect=timeout_exc,
            ),
            pytest.raises(NgspiceError, match="timed out"),
        ):
            run_deck(_OP_DECK, timeout=0.01)


@requires_ngspice
class TestRunDeck:
    def test_reads_output_voltage(self) -> None:
        result = run_deck(_OP_DECK)
        assert isinstance(result, SimulationResult)
        assert result.voltage("vout") == pytest.approx(3.2, abs=0.05)
        assert result.raw_output  # raw ngspice output is retained

    def test_result_node_voltages_are_immutable(self) -> None:
        result = run_deck(_OP_DECK)
        with pytest.raises(TypeError):
            result.node_voltages["vout"] = 0.0  # type: ignore[index]

    def test_non_convergence_raises(self) -> None:
        # R1=1k pushes the high-gain feedback loop to a non-converging
        # operating point; ngspice aborts and prints no v(vout) line while
        # still exiting 0, so the runner must detect it by parsing.
        deck = _OP_DECK.replace("R1 vout fb 30000", "R1 vout fb 1000")
        with pytest.raises(NgspiceError):
            run_deck(deck)

    def test_missing_node_raises(self) -> None:
        with pytest.raises(NgspiceError):
            run_deck(_OP_DECK, nodes=("does_not_exist",))
