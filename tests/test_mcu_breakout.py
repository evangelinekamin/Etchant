"""Tests for the ESP32-C3 minimum-system breakout generator."""

from __future__ import annotations

import pytest

from etchant.circuits.mcu_breakout import ESP32C3Breakout
from etchant.core.assembly_validator import validate_jlcpcb_assembly
from etchant.core.component_selector import set_parts_db
from etchant.core.models import CircuitSpec, ComponentCategory


def _spec(vin: float = 5.0) -> CircuitSpec:
    return CircuitSpec(
        name="esp32_test",
        topology="mcu_breakout",
        input_voltage=vin,
        output_voltage=3.3,
        output_current=0.5,
        description="test",
    )


class TestESP32C3Breakout:
    def test_component_count(self) -> None:
        design = ESP32C3Breakout().generate(_spec())
        assert len(design.components) == 10

    def test_uses_curated_assembly_parts(self) -> None:
        design = ESP32C3Breakout().generate(_spec())
        mcu = next(c for c in design.components if c.reference == "U1")
        led = next(c for c in design.components if c.reference == "D1")
        decoupling = next(c for c in design.components if c.reference == "C2")
        en_pullup = next(c for c in design.components if c.reference == "R1")
        led_resistor = next(c for c in design.components if c.reference == "R2")

        assert mcu.value == "ESP32-C3-WROOM-02-N4"
        assert mcu.jlcpcb_part_number == "C2934560"
        assert led.value == "KT-0805G"
        assert led.jlcpcb_part_number == "C2297"
        assert decoupling.jlcpcb_part_number == "C14663"
        assert en_pullup.jlcpcb_part_number == "C25804"
        assert led_resistor.jlcpcb_part_number == "C21190"

    def test_has_programming_and_gpio_headers(self) -> None:
        design = ESP32C3Breakout().generate(_spec())
        conns = [c for c in design.components if c.category == ComponentCategory.CONNECTOR]
        assert {c.reference for c in conns} == {"J1", "J2"}
        assert any("1x06" in c.footprint for c in conns)
        assert any("1x08" in c.footprint for c in conns)

    def test_static_assembly_validation_has_no_blocking_errors(self) -> None:
        set_parts_db(None)
        design = ESP32C3Breakout().generate(_spec())
        report = validate_jlcpcb_assembly(design, prefer_basic=True)

        assert report.assembly_ready is True
        assert report.error_count == 0

    def test_rejects_non_usb_input_voltage(self) -> None:
        with pytest.raises(ValueError, match="USB input voltage"):
            ESP32C3Breakout().generate(_spec(vin=12.0))
