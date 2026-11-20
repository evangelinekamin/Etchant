"""Tests for voltage divider / reference generator."""

from __future__ import annotations

import pytest

from etchant.circuits.voltage_divider import (
    VoltageDividerCircuit,
    _format_resistor,
    _pick_divider_pair,
)
from etchant.core.models import CircuitSpec, ComponentCategory


def _spec(vin: float = 5.0, vout: float = 2.5) -> CircuitSpec:
    return CircuitSpec(
        name="div_test",
        topology="voltage_divider",
        input_voltage=vin,
        output_voltage=vout,
        output_current=0.001,
        description="test",
    )


class TestDividerMath:
    def test_5v_to_2v5_equal_resistors(self) -> None:
        r1, r2 = _pick_divider_pair(5.0, 2.5)
        # V_out / V_in = 0.5 → R2 / (R1+R2) = 0.5 → R1 == R2
        assert abs(r1 - r2) / max(r1, r2) < 0.01

    def test_5v_to_3v3(self) -> None:
        r1, r2 = _pick_divider_pair(5.0, 3.3)
        ratio = r2 / (r1 + r2)
        assert abs(ratio - 3.3 / 5.0) < 0.02  # within 2% of target

    def test_12v_to_3v3(self) -> None:
        r1, r2 = _pick_divider_pair(12.0, 3.3)
        actual_vout = 12.0 * r2 / (r1 + r2)
        assert abs(actual_vout - 3.3) < 0.15  # within 150mV of target

    def test_rejects_vout_greater_than_vin(self) -> None:
        with pytest.raises(ValueError):
            _pick_divider_pair(3.3, 5.0)


class TestResistorFormat:
    def test_sub_ohm(self) -> None:
        assert _format_resistor(0.1) == "100R"

    def test_kohm(self) -> None:
        assert _format_resistor(10) == "10k"

    def test_fractional_kohm(self) -> None:
        assert _format_resistor(4.7) == "4.7k"

    def test_megohm(self) -> None:
        assert _format_resistor(1000) == "1M"


class TestGeneration:
    def test_four_components(self) -> None:
        design = VoltageDividerCircuit().generate(_spec())
        # R1 + R2 + C1 + J1
        assert len(design.components) == 4

    def test_three_nets(self) -> None:
        design = VoltageDividerCircuit().generate(_spec())
        names = {n.name for n in design.nets}
        assert names == {"VIN", "GND", "VOUT"}

    def test_divider_topology(self) -> None:
        """R1 top → VOUT tap → R2 bottom → GND. Bypass C1 on VOUT."""
        design = VoltageDividerCircuit().generate(_spec())
        vin = next(n for n in design.nets if n.name == "VIN")
        vout = next(n for n in design.nets if n.name == "VOUT")
        gnd = next(n for n in design.nets if n.name == "GND")
        assert ("R1", "1") in vin.connections
        assert ("R1", "2") in vout.connections
        assert ("R2", "1") in vout.connections
        assert ("R2", "2") in gnd.connections
        assert ("C1", "1") in vout.connections
        assert ("C1", "2") in gnd.connections

    def test_3pin_header(self) -> None:
        design = VoltageDividerCircuit().generate(_spec())
        conns = [c for c in design.components if c.category == ComponentCategory.CONNECTOR]
        assert len(conns) == 1
        assert "1x03" in conns[0].footprint


class TestValidation:
    def test_rejects_vout_ge_vin(self) -> None:
        with pytest.raises(ValueError, match="less than"):
            VoltageDividerCircuit().generate(_spec(vin=3.3, vout=5.0))

    def test_rejects_zero_voltage(self) -> None:
        with pytest.raises(ValueError):
            VoltageDividerCircuit().generate(_spec(vin=0, vout=0))

    def test_rejects_high_voltage(self) -> None:
        with pytest.raises(ValueError, match="exceeds"):
            VoltageDividerCircuit().generate(_spec(vin=48, vout=5.0))


class TestRegistry:
    def test_registered(self) -> None:
        from etchant.circuits import get_generator, list_topologies
        assert "voltage_divider" in list_topologies()
        assert isinstance(get_generator("voltage_divider"), VoltageDividerCircuit)
