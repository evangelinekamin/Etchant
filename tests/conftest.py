"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from etchant.core.models import (
    CircuitSpec,
    ComponentCategory,
    ComponentSpec,
    DesignResult,
    NetSpec,
)


@pytest.fixture
def fixed_output_buck() -> DesignResult:
    """A buck-style design with NO feedback divider (fixed-output IC).

    Used to exercise the "not applicable" path of the SPICE output-voltage
    gate, which only verifies adjustable bucks (those with R1/R2/FB).
    """
    spec = CircuitSpec(
        name="fixed_output_buck",
        topology="buck_converter",
        input_voltage=12.0,
        output_voltage=5.0,
        output_current=1.0,
        description="fixed-output buck (no feedback divider)",
    )
    components = (
        ComponentSpec(
            reference="U1",
            category=ComponentCategory.IC,
            value="TPS563200",
            footprint="Package_TO_SOT_SMD:SOT-563",
            kicad_library="Regulator_Switching",
            kicad_symbol="TPS563200",
            description="fixed-output buck IC",
        ),
        ComponentSpec(
            reference="L1",
            category=ComponentCategory.INDUCTOR,
            value="4.7uH",
            footprint="Inductor_SMD:L_Vishay_IHLP-2525",
            kicad_library="Device",
            kicad_symbol="L",
            description="power inductor",
        ),
    )
    nets = (
        NetSpec(name="VIN", connections=(("U1", "VIN"),)),
        NetSpec(name="SW", connections=(("U1", "SW"), ("L1", "1"))),
        NetSpec(name="VOUT", connections=(("L1", "2"),)),
        NetSpec(name="GND", connections=(("U1", "GND"),)),
    )
    return DesignResult(
        spec=spec,
        components=components,
        nets=nets,
        placement_constraints=(),
        design_notes=(),
    )


@pytest.fixture
def lm2596_spec() -> CircuitSpec:
    return CircuitSpec(
        name="lm2596_buck_12v_5v",
        topology="buck_converter",
        input_voltage=12.0,
        output_voltage=5.0,
        output_current=2.0,
        description="LM2596 12V to 5V 2A buck converter",
    )


@pytest.fixture
def golden_dir() -> Path:
    return Path(__file__).parent / "golden"


@pytest.fixture
def constraints_dir() -> Path:
    return Path(__file__).parent.parent / "constraints"
