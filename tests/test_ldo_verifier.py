"""Tests for the LDO output-voltage verification gate (slice 2).

Mirrors the buck gate but for the LM317-style adjustable LDO (AMS1117-ADJ): the
regulator holds Vref across VOUT->ADJ, so Vout = Vref * (1 + R2/R1) with
Vref = 1.25 V. Note the differences from the buck: the feedback node is ADJ
(not FB), Vref is 1.25 (not 0.8), and the divider sense is inverted -- R1 spans
VOUT->ADJ and R2 spans ADJ->GND.
"""

import dataclasses
import shutil

import pytest

from etchant.circuits.generative_ldo import GenerativeLDORegulator
from etchant.core.models import CircuitSpec
from etchant.sim import VerifyResult

try:  # verify_ldo is what this slice adds; import defensively so RED is a clean fail.
    from etchant.sim import verify_ldo
except ImportError:  # pragma: no cover
    verify_ldo = None

pytestmark = pytest.mark.skipif(
    shutil.which("ngspice") is None, reason="ngspice binary required for SPICE gate"
)


def _ldo(vout: float, vin: float = 12.0, iout: float = 0.5):
    return GenerativeLDORegulator().generate(
        CircuitSpec(
            name="ldo",
            topology="ldo_regulator",
            input_voltage=vin,
            output_voltage=vout,
            output_current=iout,
            description="adjustable ldo",
        )
    )


def test_verify_ldo_passes_for_correct_adjustable_ldo():
    """A correctly-generated adjustable LDO regulates to its target voltage."""
    assert verify_ldo is not None, "verify_ldo is not implemented in etchant.sim yet"
    result = verify_ldo(_ldo(4.1))
    assert isinstance(result, VerifyResult)
    assert result.applicable is True
    assert result.passed is True
    # E24 divider quantization allows a few percent of honest drift.
    assert abs(result.vout_sim - 4.1) / 4.1 * 100.0 <= 6.0


def test_verify_ldo_catches_wrong_ratio_resistor():
    """Sabotaging the ADJ->GND ratio resistor must fail the gate.

    This is the electrically-wrong board that the graph/DRC/part checks pass clean.
    """
    assert verify_ldo is not None, "verify_ldo is not implemented in etchant.sim yet"
    design = _ldo(4.1)
    comps = tuple(
        dataclasses.replace(c, value="22k") if c.reference == "R2" else c
        for c in design.components
    )
    bad = dataclasses.replace(design, components=comps)
    result = verify_ldo(bad)
    assert result.applicable is True
    assert result.passed is False
    assert result.vout_sim > 4.1 * 1.3  # way above target


def test_verify_ldo_not_applicable_for_fixed_output():
    """A fixed-output LDO (no divider) is not applicable and raises no objection."""
    assert verify_ldo is not None, "verify_ldo is not implemented in etchant.sim yet"
    result = verify_ldo(_ldo(5.0))  # 5.0V is a fixed AMS1117 part -> no ADJ divider
    assert result.applicable is False
    assert result.passed is True
