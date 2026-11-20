"""Output-voltage verification gate for adjustable buck converters.

This is slice 1 of Etchant's SPICE verification: it answers one electrical
question the graph/DRC/part checks cannot -- does the regulated output voltage
actually match the requested target? A design whose feedback divider resolves
to the wrong voltage (wrong part, wrong value) fails here even though it is
graph-complete, in stock, and passes DRC.
"""

from __future__ import annotations

from dataclasses import dataclass

from etchant.core.models import DesignResult
from etchant.sim.ngspice_runner import run_deck
from etchant.sim.spice_netlist import (
    DEFAULT_VREF,
    build_buck_deck,
    has_feedback_divider,
)

DEFAULT_TOLERANCE_PCT = 5.0
"""Allowed VOUT error before the gate fails a design.

Adjustable bucks set VOUT with a resistor divider drawn from the E24 series, so
the achievable voltage is quantized: a 12V->3.3V design rounds its ideal 31.25k
top resistor to 30k and lands at 3.20V, ~3% low. The tolerance sits above that
quantization floor so honest designs pass, while gross errors (wrong resistor,
wrong part) -- which miss by tens of percent -- fail.
"""


@dataclass(frozen=True)
class VerifyResult:
    """Immutable verdict from the buck output-voltage gate."""

    applicable: bool
    passed: bool
    vout_sim: float
    vout_target: float
    error_pct: float
    tolerance_pct: float
    detail: str


def verify_buck(
    design: DesignResult,
    *,
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
    vref: float = DEFAULT_VREF,
    timeout: float = 30.0,
) -> VerifyResult:
    """Verify that an adjustable buck's simulated VOUT matches its target.

    For designs without a feedback divider (fixed-output ICs) the check does not
    apply: ``applicable`` is False and ``passed`` is True (the gate raises no
    objection) rather than raising.

    Raises NgspiceError if the simulation cannot be run or fails to converge.
    """
    target = design.spec.output_voltage

    if not has_feedback_divider(design):
        return VerifyResult(
            applicable=False,
            passed=True,
            vout_sim=0.0,
            vout_target=target,
            error_pct=0.0,
            tolerance_pct=tolerance_pct,
            detail=(
                "no feedback divider (fixed-output design); output-voltage "
                "regulation check not applicable"
            ),
        )

    deck = build_buck_deck(design, vref=vref)
    result = run_deck(deck, nodes=("vout",), timeout=timeout)
    vout_sim = result.voltage("vout")

    error_pct = abs(vout_sim - target) / target * 100.0 if target else float("inf")
    passed = error_pct <= tolerance_pct
    verdict = "within" if passed else "outside"
    detail = (
        f"simulated VOUT {vout_sim:.4g}V vs target {target:.4g}V "
        f"({error_pct:.2f}% error, {verdict} {tolerance_pct:g}% tolerance)"
    )
    return VerifyResult(
        applicable=True,
        passed=passed,
        vout_sim=vout_sim,
        vout_target=target,
        error_pct=error_pct,
        tolerance_pct=tolerance_pct,
        detail=detail,
    )
