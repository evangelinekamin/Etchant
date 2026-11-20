"""Tests for the op-amp unity-gain buffer generator."""

from __future__ import annotations

import pytest

from etchant.circuits.op_amp_buffer import OpAmpBufferCircuit
from etchant.core.models import CircuitSpec, ComponentCategory


def _spec(vin: float = 5.0) -> CircuitSpec:
    return CircuitSpec(
        name="opamp_test",
        topology="op_amp_buffer",
        input_voltage=vin,
        output_voltage=vin,
        output_current=0.02,
        description="test",
    )


class TestBasicGeneration:
    def test_component_count(self) -> None:
        design = OpAmpBufferCircuit().generate(_spec())
        # U1 (op-amp), C1 (bypass), J1 (4-pin header)
        assert len(design.components) == 3

    def test_has_op_amp(self) -> None:
        design = OpAmpBufferCircuit().generate(_spec())
        ics = [c for c in design.components if c.category == ComponentCategory.IC]
        assert len(ics) == 1
        assert "MCP6001" in ics[0].value

    def test_has_bypass_cap(self) -> None:
        design = OpAmpBufferCircuit().generate(_spec())
        caps = [c for c in design.components if c.category == ComponentCategory.CAPACITOR]
        assert len(caps) == 1
        assert caps[0].value == "100nF"

    def test_has_4pin_header(self) -> None:
        design = OpAmpBufferCircuit().generate(_spec())
        conns = [c for c in design.components if c.category == ComponentCategory.CONNECTOR]
        assert len(conns) == 1
        assert "1x04" in conns[0].footprint


class TestUnityGainWiring:
    def test_buffer_short_tied(self) -> None:
        """OUT (pin 1) must be tied to IN- (pin 4) — that's what makes it a buffer."""
        design = OpAmpBufferCircuit().generate(_spec())
        vout = next(n for n in design.nets if n.name == "VOUT")
        u1_pins_on_vout = {pin for ref, pin in vout.connections if ref == "U1"}
        # Both the OUT pin (~) and IN- pin (-) must be on VOUT
        assert "~" in u1_pins_on_vout, "OUT pin (~) must be on VOUT"
        assert "-" in u1_pins_on_vout, "IN- pin (-) must be on VOUT (feedback)"

    def test_vin_drives_inplus(self) -> None:
        design = OpAmpBufferCircuit().generate(_spec())
        vin = next(n for n in design.nets if n.name == "VIN")
        u1_pins_on_vin = {pin for ref, pin in vin.connections if ref == "U1"}
        assert "+" in u1_pins_on_vin, "IN+ pin (+) must be on VIN"

    def test_bypass_cap_on_supply(self) -> None:
        design = OpAmpBufferCircuit().generate(_spec())
        vcc = next(n for n in design.nets if n.name == "VCC")
        gnd = next(n for n in design.nets if n.name == "GND")
        assert ("C1", "1") in vcc.connections
        assert ("C1", "2") in gnd.connections

    def test_all_four_nets_present(self) -> None:
        design = OpAmpBufferCircuit().generate(_spec())
        names = {n.name for n in design.nets}
        assert names == {"VCC", "GND", "VIN", "VOUT"}


class TestSpecValidation:
    def test_rejects_below_supply_range(self) -> None:
        gen = OpAmpBufferCircuit()
        with pytest.raises(ValueError, match="MCP6001 range"):
            gen.generate(_spec(vin=1.5))

    def test_rejects_above_supply_range(self) -> None:
        gen = OpAmpBufferCircuit()
        with pytest.raises(ValueError, match="MCP6001 range"):
            gen.generate(_spec(vin=9.0))

    def test_accepts_3v3(self) -> None:
        OpAmpBufferCircuit().generate(_spec(vin=3.3))  # should not raise

    def test_accepts_5v(self) -> None:
        OpAmpBufferCircuit().generate(_spec(vin=5.0))

    def test_accepts_6v_boundary(self) -> None:
        OpAmpBufferCircuit().generate(_spec(vin=6.0))


class TestPlacementConstraints:
    def test_bypass_cap_near_opamp(self) -> None:
        design = OpAmpBufferCircuit().generate(_spec())
        cap_constraint = next(
            pc for pc in design.placement_constraints if pc.component_ref == "C1"
        )
        assert cap_constraint.target_ref == "U1"
        assert cap_constraint.max_distance_mm <= 5.0

    def test_header_is_unanchored(self) -> None:
        design = OpAmpBufferCircuit().generate(_spec())
        j1 = next(pc for pc in design.placement_constraints if pc.component_ref == "J1")
        # target_ref=None → edge placement in constraint_placer step 4
        assert j1.target_ref is None


class TestRegistryIntegration:
    def test_registered_under_op_amp_buffer(self) -> None:
        from etchant.circuits import get_generator, list_topologies
        assert "op_amp_buffer" in list_topologies()
        gen = get_generator("op_amp_buffer")
        assert isinstance(gen, OpAmpBufferCircuit)
