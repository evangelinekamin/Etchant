"""Tests for the USB-C sink protection generator."""

from __future__ import annotations

import pytest

from etchant.circuits import get_generator, list_topologies
from etchant.circuits.usb_c_sink_protection import USBCSinkProtection
from etchant.core.assembly_validator import validate_jlcpcb_assembly
from etchant.core.component_selector import set_parts_db
from etchant.core.models import CircuitSpec


def _spec(vin: float = 5.0, vout: float = 5.0, current: float = 3.0) -> CircuitSpec:
    return CircuitSpec(
        name="usb_c_sink_test",
        topology="usb_c_sink_protection",
        input_voltage=vin,
        output_voltage=vout,
        output_current=current,
        description="test",
    )


class TestUSBCSinkProtection:
    def test_generates_connector_protection_efuse_and_output(self) -> None:
        design = USBCSinkProtection().generate(_spec())

        refs = {component.reference for component in design.components}
        assert {
            "J1", "U1", "D1", "R1", "R2", "R3", "R4", "C1", "C2",
            "C3", "J2", "TP1",
        } == refs

    def test_uses_real_usb_c_and_efuse_parts(self) -> None:
        design = USBCSinkProtection().generate(_spec())
        by_ref = {component.reference: component for component in design.components}

        assert by_ref["J1"].value == "USB_C_Receptacle_PowerOnly_6P"
        assert by_ref["U1"].value == "TPS259571DSGR"
        assert by_ref["U1"].jlcpcb_part_number == "C471038"
        assert by_ref["D1"].value == "SMF5.0CA"
        assert by_ref["D1"].jlcpcb_part_number == "C4749140"
        assert by_ref["R1"].jlcpcb_part_number == "C23186"
        assert by_ref["R3"].jlcpcb_part_number == "C23228"
        assert by_ref["C3"].jlcpcb_part_number == "C1613"

    def test_type_c_rd_and_power_path_nets(self) -> None:
        design = USBCSinkProtection().generate(_spec())
        nets = {net.name: set(net.connections) for net in design.nets}

        assert ("J1", "A5") in nets["CC1"]
        assert ("R1", "1") in nets["CC1"]
        assert ("J1", "B5") in nets["CC2"]
        assert ("R2", "1") in nets["CC2"]
        assert ("R1", "2") in nets["GND"]
        assert ("R2", "2") in nets["GND"]
        assert {("J1", "A9"), ("J1", "B9"), ("U1", "3"), ("U1", "4")} <= nets[
            "VBUS_RAW"
        ]
        assert {("U1", "5"), ("C2", "1"), ("J2", "1")} <= nets["5V_PROTECTED"]

    def test_static_assembly_validation_flags_only_unsourced_usb_c_receptacle(
        self,
    ) -> None:
        # The eFuse protection circuit (U1, D1, R1-R4, C1-C3) is fully sourced
        # from the static JLCPCB table. J2 (output terminal block) and TP1
        # (test point) are legitimately do-not-populate. J1, the USB-C
        # receptacle, is not yet in the static parts table -- honestly
        # blocking assembly until it is sourced, rather than a silent
        # connector-category pass.
        set_parts_db(None)
        report = validate_jlcpcb_assembly(
            USBCSinkProtection().generate(_spec()),
            prefer_basic=True,
        )

        blocking = {check.reference for check in report.checks if check.has_error}
        assert blocking == {"J1"}
        assert report.assembly_ready is False
        assert report.error_count == 1

    def test_rejects_non_5v_power_path(self) -> None:
        with pytest.raises(ValueError, match="5V in to 5V out"):
            USBCSinkProtection().generate(_spec(vin=9.0, vout=5.0))

    def test_rejects_current_above_basic_type_c_limit(self) -> None:
        with pytest.raises(ValueError, match="non-PD 3A"):
            USBCSinkProtection().generate(_spec(current=4.0))

    def test_registered(self) -> None:
        assert "usb_c_sink_protection" in list_topologies()
        assert isinstance(get_generator("usb_c_sink_protection"), USBCSinkProtection)
