"""Tests for the low-voltage brushed motor driver generator."""

from __future__ import annotations

import pytest

from etchant.circuits import get_generator, list_topologies
from etchant.circuits.brushed_motor_driver import BrushedMotorDriver
from etchant.core.assembly_validator import validate_jlcpcb_assembly
from etchant.core.component_selector import set_parts_db
from etchant.core.models import CircuitSpec


def _spec(vin: float = 6.0, current: float = 1.0) -> CircuitSpec:
    return CircuitSpec(
        name="motor_test",
        topology="brushed_motor_driver",
        input_voltage=vin,
        output_voltage=vin,
        output_current=current,
        description="test",
    )


class TestBrushedMotorDriver:
    def test_generates_driver_caps_and_connectors(self) -> None:
        design = BrushedMotorDriver().generate(_spec())
        assert len(design.components) == 5
        assert {c.reference for c in design.components} == {"U1", "C1", "C2", "J1", "J2"}

    def test_uses_stocked_drv8837(self) -> None:
        design = BrushedMotorDriver().generate(_spec())
        driver = next(c for c in design.components if c.reference == "U1")
        assert driver.value == "DRV8837DSGR"
        assert driver.jlcpcb_part_number == "C39159"
        assert "WSON-8" in driver.footprint

    def test_motor_outputs_and_control_nets(self) -> None:
        design = BrushedMotorDriver().generate(_spec())
        names = {n.name for n in design.nets}
        assert {"VM", "GND", "IN1", "IN2", "NSLEEP", "OUT1", "OUT2"} <= names

    def test_static_assembly_validation_has_no_blocking_errors(self) -> None:
        set_parts_db(None)
        report = validate_jlcpcb_assembly(
            BrushedMotorDriver().generate(_spec()),
            prefer_basic=True,
        )
        assert report.assembly_ready is True
        assert report.error_count == 0

    def test_rejects_voltage_outside_drv8837_range(self) -> None:
        with pytest.raises(ValueError, match="DRV8837 range"):
            BrushedMotorDriver().generate(_spec(vin=12.0))

    def test_rejects_current_above_conservative_limit(self) -> None:
        with pytest.raises(ValueError, match="conservative 1A"):
            BrushedMotorDriver().generate(_spec(current=1.5))

    def test_registered(self) -> None:
        assert "brushed_motor_driver" in list_topologies()
        assert isinstance(get_generator("brushed_motor_driver"), BrushedMotorDriver)
