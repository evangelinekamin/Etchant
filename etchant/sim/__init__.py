"""SPICE-based electrical verification for Etchant designs.

Slice 1 provides an output-voltage regulation gate for adjustable buck
converters. The public surface is intentionally small so later slices (other
topologies, switching-stage checks) can extend it without churn.
"""

from etchant.sim.buck_verifier import (
    DEFAULT_TOLERANCE_PCT,
    VerifyResult,
    verify_buck,
)
from etchant.sim.ngspice_runner import (
    NgspiceError,
    SimulationResult,
    check_ngspice_available,
    run_deck,
)
from etchant.sim.spice_netlist import (
    DEFAULT_GAIN,
    DEFAULT_VREF,
    build_buck_deck,
    has_feedback_divider,
    parse_component_value,
)

__all__ = [
    "DEFAULT_GAIN",
    "DEFAULT_TOLERANCE_PCT",
    "DEFAULT_VREF",
    "NgspiceError",
    "SimulationResult",
    "VerifyResult",
    "build_buck_deck",
    "check_ngspice_available",
    "has_feedback_divider",
    "parse_component_value",
    "run_deck",
    "verify_buck",
]
