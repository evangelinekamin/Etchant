"""Tests for the experimental USB-C to M.2 NVMe bridge topology."""

from __future__ import annotations

import pytest

from etchant.circuits.usb_nvme_bridge import USBNVMeBridge
from etchant.core.models import CircuitSpec


@pytest.fixture
def spec() -> CircuitSpec:
    return CircuitSpec(
        name="usb_nvme_2230",
        topology="usb_nvme_bridge",
        input_voltage=5.0,
        output_voltage=3.3,
        output_current=2.0,
        description="USB-C to M.2 2230 NVMe bridge",
    )


class TestUSBNVMeBridge:
    def test_validates_usb_power_shape(self, spec: CircuitSpec) -> None:
        assert USBNVMeBridge().validate_spec(spec) == ()

    def test_rejects_non_usb_input_voltage(self) -> None:
        spec = CircuitSpec(
            name="bad",
            topology="usb_nvme_bridge",
            input_voltage=12.0,
            output_voltage=3.3,
            output_current=2.0,
            description="bad",
        )

        errors = USBNVMeBridge().validate_spec(spec)

        assert errors
        assert "5V" in errors[0]

    def test_generates_expected_blocks(self, spec: CircuitSpec) -> None:
        design = USBNVMeBridge().generate(spec)

        refs = {component.reference for component in design.components}
        assert {"J1", "U1", "J2", "U2", "U3", "Y1", "U4"} <= refs
        assert any(component.value == "M.2_M-Key_2230_NVMe" for component in design.components)
        assert any(component.value == "JMS583" for component in design.components)

    def test_declares_high_speed_nets(self, spec: CircuitSpec) -> None:
        design = USBNVMeBridge().generate(spec)

        net_names = {net.name for net in design.nets}
        assert {"USB_RX_P", "USB_RX_N", "USB_TX_P", "USB_TX_N"} <= net_names
        assert {"PCIE_TX_P", "PCIE_TX_N", "PCIE_RX_P", "PCIE_RX_N"} <= net_names

    def test_notes_are_explicitly_experimental(self, spec: CircuitSpec) -> None:
        design = USBNVMeBridge().generate(spec)
        notes = " ".join(design.design_notes).lower()

        assert "experimental" in notes
        assert "not fabrication-ready" in notes
        assert "raid1" in notes
