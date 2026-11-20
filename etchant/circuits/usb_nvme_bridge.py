"""Experimental USB-C to M.2 2230 NVMe bridge topology.

This is an architecture-level generator for portable SSD/flash-drive concepts.
It intentionally does not claim fabrication readiness: USB 3.x and PCIe/NVMe
need controlled impedance, bridge-vendor reference layouts, and custom KiCad
symbols/footprints before ordering hardware.
"""

from __future__ import annotations

from etchant.core.models import (
    CircuitSpec,
    ComponentCategory,
    ComponentSpec,
    DesignResult,
    NetSpec,
    PlacementConstraint,
)


class USBNVMeBridge:
    """Single M.2 2230 NVMe SSD to USB-C bridge concept."""

    @property
    def topology(self) -> str:
        return "usb_nvme_bridge"

    def validate_spec(self, spec: CircuitSpec) -> tuple[str, ...]:
        errors: list[str] = []
        if spec.input_voltage != 5.0:
            errors.append(
                f"USB-C bus-powered NVMe bridge expects 5V input, got {spec.input_voltage}V"
            )
        if spec.output_voltage != 3.3:
            errors.append(
                f"M.2 NVMe SSD rail expects 3.3V output, got {spec.output_voltage}V"
            )
        if spec.output_current <= 0:
            errors.append(f"SSD current budget must be positive, got {spec.output_current}A")
        if spec.output_current > 3.0:
            errors.append(
                f"SSD current budget {spec.output_current}A is high for a compact "
                "bus-powered USB-C board; use external power or a larger thermal design."
            )
        return tuple(errors)

    def generate(self, spec: CircuitSpec) -> DesignResult:
        errors = self.validate_spec(spec)
        if errors:
            raise ValueError(f"Invalid spec: {'; '.join(errors)}")
        return self._build_design(spec)

    def _build_design(self, spec: CircuitSpec) -> DesignResult:
        return DesignResult(
            spec=spec,
            components=self._components(spec),
            nets=self._nets(),
            placement_constraints=self._placement_constraints(),
            design_notes=self._design_notes(spec),
        )

    def _components(self, spec: CircuitSpec) -> tuple[ComponentSpec, ...]:
        return (
            ComponentSpec(
                reference="J1",
                category=ComponentCategory.CONNECTOR,
                value="USB_C_Receptacle_USB3",
                footprint="Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal",
                kicad_library="Connector",
                kicad_symbol="USB_C_Receptacle_USB2.0",
                description=(
                    "USB-C receptacle; use a USB 3.x-capable symbol/footprint "
                    "in production"
                ),
                properties={"role": "upstream_usb_c", "speed": "USB 3.2 Gen 2 target"},
            ),
            ComponentSpec(
                reference="U1",
                category=ComponentCategory.IC,
                value="JMS583",
                footprint="Package_QFN:QFN-48-1EP_6x6mm_P0.4mm_EP4.2x4.2mm",
                kicad_library="Interface_USB",
                kicad_symbol="JMS583_PLACEHOLDER",
                description="USB 3.1 Gen 2 to PCIe/NVMe bridge controller placeholder",
                properties={
                    "bridge_family": "USB-to-NVMe",
                    "layout_status": "requires vendor reference design",
                    "pcie_lanes": "2",
                },
            ),
            ComponentSpec(
                reference="J2",
                category=ComponentCategory.CONNECTOR,
                value="M.2_M-Key_2230_NVMe",
                footprint="Connector_M.2:M.2_M-Key_2230_Socket_PLACEHOLDER",
                kicad_library="Connector_Generic",
                kicad_symbol="Conn_01x75",
                description="M.2 M-key socket for 2230 NVMe SSD",
                properties={
                    "m2_key": "M",
                    "ssd_lengths": "2230",
                    "interface": "PCIe/NVMe",
                    "layout_status": "custom footprint required",
                },
            ),
            ComponentSpec(
                reference="U2",
                category=ComponentCategory.IC,
                value="3.3V_2A_Buck",
                footprint="Package_TO_SOT_SMD:SOT-23-6",
                kicad_library="Regulator_Switching",
                kicad_symbol="Buck_Regulator_PLACEHOLDER",
                description="5V to 3.3V SSD power rail regulator placeholder",
                properties={
                    "input": "USB_VBUS",
                    "output": "3.3V",
                    "current_budget": f"{spec.output_current}A",
                },
            ),
            ComponentSpec(
                reference="U3",
                category=ComponentCategory.IC,
                value="USB3_ESD_Array",
                footprint="Package_TO_SOT_SMD:SOT-23-6",
                kicad_library="Device",
                kicad_symbol="D_TVS",
                description="Low-capacitance ESD protection for USB high-speed pairs",
                properties={"capacitance": "low", "placement": "next to USB-C connector"},
            ),
            ComponentSpec(
                reference="Y1",
                category=ComponentCategory.IC,
                value="25MHz",
                footprint="Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
                kicad_library="Device",
                kicad_symbol="Crystal",
                description="Bridge controller reference crystal placeholder",
                properties={"frequency": "25MHz"},
            ),
            ComponentSpec(
                reference="U4",
                category=ComponentCategory.IC,
                value="SPI_Flash_4Mbit",
                footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
                kicad_library="Memory_Flash",
                kicad_symbol="W25Q32JVSS",
                description="Firmware/configuration flash placeholder",
                properties={"interface": "SPI"},
            ),
            ComponentSpec(
                reference="C1",
                category=ComponentCategory.CAPACITOR,
                value="22uF",
                footprint="Capacitor_SMD:C_0805_2012Metric",
                kicad_library="Device",
                kicad_symbol="C",
                description="USB VBUS bulk capacitor",
            ),
            ComponentSpec(
                reference="C2",
                category=ComponentCategory.CAPACITOR,
                value="22uF",
                footprint="Capacitor_SMD:C_0805_2012Metric",
                kicad_library="Device",
                kicad_symbol="C",
                description="3.3V SSD rail bulk capacitor",
            ),
            ComponentSpec(
                reference="R1",
                category=ComponentCategory.RESISTOR,
                value="5.1k",
                footprint="Resistor_SMD:R_0603_1608Metric",
                kicad_library="Device",
                kicad_symbol="R",
                description="USB-C CC1 Rd pull-down",
            ),
            ComponentSpec(
                reference="R2",
                category=ComponentCategory.RESISTOR,
                value="5.1k",
                footprint="Resistor_SMD:R_0603_1608Metric",
                kicad_library="Device",
                kicad_symbol="R",
                description="USB-C CC2 Rd pull-down",
            ),
        )

    def _nets(self) -> tuple[NetSpec, ...]:
        return (
            NetSpec(
                name="VBUS",
                connections=(("J1", "VBUS"), ("U2", "VIN"), ("C1", "1")),
            ),
            NetSpec(
                name="3V3",
                connections=(
                    ("U2", "VOUT"), ("J2", "3V3"), ("C2", "1"), ("U1", "VDD"),
                ),
            ),
            NetSpec(name="GND", connections=(
                ("J1", "GND"), ("U1", "GND"), ("U2", "GND"), ("J2", "GND"),
                ("U3", "GND"), ("C1", "2"), ("C2", "2"), ("R1", "2"), ("R2", "2"),
            )),
            NetSpec(name="CC1", connections=(("J1", "CC1"), ("R1", "1"))),
            NetSpec(name="CC2", connections=(("J1", "CC2"), ("R2", "1"))),
            NetSpec(name="USB_D_P", connections=(("J1", "D+"), ("U1", "USB_DP"), ("U3", "D+"))),
            NetSpec(name="USB_D_N", connections=(("J1", "D-"), ("U1", "USB_DM"), ("U3", "D-"))),
            NetSpec(
                name="USB_RX_P",
                connections=(("J1", "SSRX+"), ("U1", "USB_TX_P"), ("U3", "SSRX+")),
            ),
            NetSpec(
                name="USB_RX_N",
                connections=(("J1", "SSRX-"), ("U1", "USB_TX_N"), ("U3", "SSRX-")),
            ),
            NetSpec(
                name="USB_TX_P",
                connections=(("J1", "SSTX+"), ("U1", "USB_RX_P"), ("U3", "SSTX+")),
            ),
            NetSpec(
                name="USB_TX_N",
                connections=(("J1", "SSTX-"), ("U1", "USB_RX_N"), ("U3", "SSTX-")),
            ),
            NetSpec(name="PCIE_TX_P", connections=(("U1", "PCIE_TX_P"), ("J2", "PERP0"))),
            NetSpec(name="PCIE_TX_N", connections=(("U1", "PCIE_TX_N"), ("J2", "PERN0"))),
            NetSpec(name="PCIE_RX_P", connections=(("U1", "PCIE_RX_P"), ("J2", "PETP0"))),
            NetSpec(name="PCIE_RX_N", connections=(("U1", "PCIE_RX_N"), ("J2", "PETN0"))),
            NetSpec(name="PCIE_REFCLK_P", connections=(("U1", "REFCLK_P"), ("J2", "REFCLK_P"))),
            NetSpec(name="PCIE_REFCLK_N", connections=(("U1", "REFCLK_N"), ("J2", "REFCLK_N"))),
            NetSpec(name="PERST", connections=(("U1", "PERST"), ("J2", "PERST"))),
            NetSpec(name="CLKREQ", connections=(("U1", "CLKREQ"), ("J2", "CLKREQ"))),
            NetSpec(name="XTAL_IN", connections=(("U1", "XI"), ("Y1", "1"))),
            NetSpec(name="XTAL_OUT", connections=(("U1", "XO"), ("Y1", "3"))),
            NetSpec(name="SPI", connections=(("U1", "SPI"), ("U4", "SPI"))),
        )

    def _placement_constraints(self) -> tuple[PlacementConstraint, ...]:
        return (
            PlacementConstraint("U1", "J1", 12.0, "USB bridge close to USB-C connector"),
            PlacementConstraint("J2", "U1", 25.0, "M.2 socket close to bridge PCIe pins"),
            PlacementConstraint("U3", "J1", 5.0, "USB ESD array adjacent to connector"),
            PlacementConstraint("U2", "J2", 15.0, "3.3V regulator close to SSD socket"),
            PlacementConstraint("Y1", "U1", 8.0, "Crystal close to bridge controller"),
            PlacementConstraint("U4", "U1", 12.0, "Firmware flash close to bridge controller"),
        )

    def _design_notes(self, spec: CircuitSpec) -> tuple[str, ...]:
        return (
            "Experimental USB-C to M.2 2230 NVMe bridge concept, not fabrication-ready.",
            "Target use: compact reliable flash-drive-style enclosure for one 2230 NVMe SSD.",
            "Bridge placeholder: JMS583-class USB 3.1 Gen 2 to PCIe/NVMe controller.",
            "High-speed constraints required: USB SuperSpeed and PCIe differential "
            "pairs at controlled impedance.",
            "Requires vendor bridge reference schematic/layout, firmware config, "
            "and custom M.2 footprint before ordering.",
            f"Power budget: USB 5V input, 3.3V SSD rail sized around {spec.output_current}A.",
            "RAID1 dual-M.2 variant is a separate topology; use a dual-NVMe RAID "
            "bridge such as JMS586R-class hardware.",
        )
