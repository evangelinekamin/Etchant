"""Tests for the MOSFET low-side switch generator."""

from __future__ import annotations

import pytest

from etchant.circuits.mosfet_switch import MosfetSwitchCircuit
from etchant.core.models import CircuitSpec, ComponentCategory


def _spec(vload: float = 5.0, iload: float = 0.05) -> CircuitSpec:
    return CircuitSpec(
        name="sw_test",
        topology="mosfet_switch",
        input_voltage=vload,
        output_voltage=vload,  # passthrough when on
        output_current=iload,
        description="test",
    )


class TestGeneration:
    def test_four_components(self) -> None:
        design = MosfetSwitchCircuit().generate(_spec())
        # Q1 (MOSFET), R1 (gate series), R2 (pulldown), J1 (header)
        assert len(design.components) == 4

    def test_has_2n7002(self) -> None:
        design = MosfetSwitchCircuit().generate(_spec())
        q = next(c for c in design.components if c.reference == "Q1")
        assert q.value == "2N7002"
        assert "SOT-23" in q.footprint

    def test_gate_pullup_default_off(self) -> None:
        """R2 ties gate to GND so CTRL must be actively driven high."""
        design = MosfetSwitchCircuit().generate(_spec())
        gnd = next(n for n in design.nets if n.name == "GND")
        gate = next(n for n in design.nets if n.name == "GATE")
        assert ("R2", "2") in gnd.connections
        assert ("R2", "1") in gate.connections

    def test_gate_series_resistor(self) -> None:
        design = MosfetSwitchCircuit().generate(_spec())
        ctrl = next(n for n in design.nets if n.name == "CTRL")
        gate = next(n for n in design.nets if n.name == "GATE")
        # R1 has CTRL on pin 1, GATE on pin 2
        assert ("R1", "1") in ctrl.connections
        assert ("R1", "2") in gate.connections

    def test_load_drain_wiring(self) -> None:
        design = MosfetSwitchCircuit().generate(_spec())
        load = next(n for n in design.nets if n.name == "LOAD")
        assert ("Q1", "D") in load.connections
        assert ("J1", "1") in load.connections

    def test_source_to_gnd(self) -> None:
        design = MosfetSwitchCircuit().generate(_spec())
        gnd = next(n for n in design.nets if n.name == "GND")
        assert ("Q1", "S") in gnd.connections


class TestValidation:
    def test_rejects_high_voltage(self) -> None:
        with pytest.raises(ValueError, match="Vds rating"):
            MosfetSwitchCircuit().generate(_spec(vload=72))

    def test_rejects_high_current(self) -> None:
        with pytest.raises(ValueError, match="continuous"):
            MosfetSwitchCircuit().generate(_spec(iload=0.5))

    def test_accepts_typical_3v3_mcu(self) -> None:
        MosfetSwitchCircuit().generate(_spec(vload=3.3, iload=0.05))

    def test_accepts_5v_100ma(self) -> None:
        MosfetSwitchCircuit().generate(_spec(vload=5.0, iload=0.1))


class TestRegistry:
    def test_registered(self) -> None:
        from etchant.circuits import get_generator, list_topologies
        assert "mosfet_switch" in list_topologies()
        assert isinstance(get_generator("mosfet_switch"), MosfetSwitchCircuit)
