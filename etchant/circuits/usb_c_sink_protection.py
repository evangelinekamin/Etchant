"""USB-C 5V sink input with a protected downstream power rail.

This topology covers the common power-only USB-C sink board:

* 5.1k Rd resistors on CC1 and CC2 for default USB-C attach.
* VBUS TVS near the connector.
* TPS259571 eFuse for current limiting, inrush control, and fault handling.
* Protected 5V/GND output connector for downstream boards.

It does not implement USB Power Delivery, USB data, cable current detection, or
alternate modes. It is intended for basic 5V sink designs up to the USB-C
non-PD 3A ceiling, subject to source/cable capability and thermal review.
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


class USBCSinkProtection:
    """Power-only USB-C sink with eFuse-protected 5V output."""

    @property
    def topology(self) -> str:
        return "usb_c_sink_protection"

    def validate_spec(self, spec: CircuitSpec) -> tuple[str, ...]:
        errors: list[str] = []
        if spec.input_voltage != 5.0 or spec.output_voltage != 5.0:
            errors.append(
                "USB-C sink protection topology currently supports only "
                f"5V in to 5V out, got {spec.input_voltage}V to "
                f"{spec.output_voltage}V"
            )
        if spec.output_current <= 0:
            errors.append(
                f"Output current must be positive, got {spec.output_current}A"
            )
        if spec.output_current > 3.0:
            errors.append(
                f"Requested {spec.output_current}A exceeds the basic USB-C "
                "non-PD 3A sink target; use USB-PD/current-advertisement support "
                "or an external power design."
            )
        return tuple(errors)

    def generate(self, spec: CircuitSpec) -> DesignResult:
        errors = self.validate_spec(spec)
        if errors:
            raise ValueError(f"Invalid spec: {'; '.join(errors)}")
        return self._build_design(spec)

    def _build_design(self, spec: CircuitSpec) -> DesignResult:
        components = (
            ComponentSpec(
                reference="J1",
                category=ComponentCategory.CONNECTOR,
                value="USB_C_Receptacle_PowerOnly_6P",
                footprint=(
                    "Connector_USB:"
                    "USB_C_Receptacle_GCT_USB4135-GF-A_6P_TopMnt_Horizontal"
                ),
                kicad_library="Connector",
                kicad_symbol="USB_C_Receptacle_PowerOnly_6P",
                description="USB-C power-only receptacle, 6-pin",
                properties={
                    "role": "sink",
                    "usb_pd": "not_supported",
                    "cc_policy": "5.1k Rd on CC1 and CC2",
                },
            ),
            ComponentSpec(
                reference="U1",
                category=ComponentCategory.IC,
                value="TPS259571DSGR",
                footprint=(
                    "Package_SON:"
                    "Texas_DSG0008A_WSON-8-1EP_2x2mm_P0.5mm_EP0.9x1.6mm"
                ),
                # KiCad may not ship this exact symbol. Use a generic 9-pin
                # symbol whose pins map 1:1 to DSG pads plus exposed pad.
                kicad_library="Connector_Generic",
                kicad_symbol="Conn_01x09",
                description="4A WSON eFuse with programmable current limit",
                properties={
                    "symbol_note": (
                        "generic numeric symbol; pad wiring follows "
                        "TPS259571 DSG pinout"
                    ),
                    "pinout": (
                        "1=dVdt,2=EN/UVLO,3=IN,4=IN,5=OUT,6=FLT,"
                        "7=ILM,8=GND,9=EP/GND"
                    ),
                    "current_limit_formula": "ILIMIT ~= 2000/RILM + 0.04A",
                    "rilm_ohms": "680",
                    "current_limit_nominal_a": "2.98",
                    "continuous_current_max_a": "4.0",
                    "retry_mode": "auto-retry",
                },
                jlcpcb_part_number="C471038",
            ),
            ComponentSpec(
                reference="D1",
                category=ComponentCategory.DIODE,
                value="SMF5.0CA",
                footprint="Diode_SMD:D_SOD-123FL",
                kicad_library="Device",
                kicad_symbol="D_TVS",
                description="Bidirectional 5V TVS diode on USB VBUS",
                properties={"placement": "near USB-C VBUS/GND pins"},
                jlcpcb_part_number="C4749140",
            ),
            ComponentSpec(
                reference="R1",
                category=ComponentCategory.RESISTOR,
                value="5.1k",
                footprint="Resistor_SMD:R_0603_1608Metric",
                kicad_library="Device",
                kicad_symbol="R",
                description="USB-C CC1 Rd sink resistor",
                jlcpcb_part_number="C23186",
            ),
            ComponentSpec(
                reference="R2",
                category=ComponentCategory.RESISTOR,
                value="5.1k",
                footprint="Resistor_SMD:R_0603_1608Metric",
                kicad_library="Device",
                kicad_symbol="R",
                description="USB-C CC2 Rd sink resistor",
                jlcpcb_part_number="C23186",
            ),
            ComponentSpec(
                reference="R3",
                category=ComponentCategory.RESISTOR,
                value="680R",
                footprint="Resistor_SMD:R_0603_1608Metric",
                kicad_library="Device",
                kicad_symbol="R",
                description="TPS259571 ILM resistor, about 3A current limit",
                jlcpcb_part_number="C23228",
            ),
            ComponentSpec(
                reference="R4",
                category=ComponentCategory.RESISTOR,
                value="10k",
                footprint="Resistor_SMD:R_0603_1608Metric",
                kicad_library="Device",
                kicad_symbol="R",
                description="Fault output pull-up",
                jlcpcb_part_number="C25804",
            ),
            ComponentSpec(
                reference="C1",
                category=ComponentCategory.CAPACITOR,
                value="100nF",
                footprint="Capacitor_SMD:C_0603_1608Metric",
                kicad_library="Device",
                kicad_symbol="C",
                description="eFuse input bypass capacitor",
                jlcpcb_part_number="C14663",
            ),
            ComponentSpec(
                reference="C2",
                category=ComponentCategory.CAPACITOR,
                value="22uF",
                footprint="Capacitor_SMD:C_0805_2012Metric",
                kicad_library="Device",
                kicad_symbol="C",
                description="Protected output bulk capacitor",
                jlcpcb_part_number="C45783",
            ),
            ComponentSpec(
                reference="C3",
                category=ComponentCategory.CAPACITOR,
                value="3.3nF",
                footprint="Capacitor_SMD:C_0603_1608Metric",
                kicad_library="Device",
                kicad_symbol="C",
                description="TPS259571 dVdt soft-start capacitor",
                jlcpcb_part_number="C1613",
            ),
            ComponentSpec(
                reference="J2",
                category=ComponentCategory.CONNECTOR,
                value="Conn_01x02",
                footprint=(
                    "TerminalBlock_Phoenix:"
                    "TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_"
                    "P5.08mm_Horizontal"
                ),
                kicad_library="Connector_Generic",
                kicad_symbol="Conn_01x02",
                description="Protected output terminal: 5V, GND",
            ),
            ComponentSpec(
                reference="TP1",
                category=ComponentCategory.CONNECTOR,
                value="TestPoint",
                footprint="TestPoint:TestPoint_Pad_D1.0mm",
                kicad_library="Connector",
                kicad_symbol="TestPoint",
                description="eFuse fault flag test point",
            ),
        )

        nets = (
            NetSpec(name="VBUS_RAW", connections=(
                ("J1", "A9"), ("J1", "B9"),
                ("U1", "2"), ("U1", "3"), ("U1", "4"),
                ("D1", "1"), ("C1", "1"), ("R4", "1"),
            )),
            NetSpec(name="GND", connections=(
                ("J1", "A12"), ("J1", "B12"), ("J1", "S1"),
                ("U1", "8"), ("U1", "9"),
                ("D1", "2"), ("C1", "2"), ("C2", "2"), ("C3", "2"),
                ("R1", "2"), ("R2", "2"), ("R3", "2"),
                ("J2", "2"),
            )),
            NetSpec(name="CC1", connections=(("J1", "A5"), ("R1", "1"))),
            NetSpec(name="CC2", connections=(("J1", "B5"), ("R2", "1"))),
            NetSpec(name="EFUSE_DVDT", connections=(("U1", "1"), ("C3", "1"))),
            NetSpec(name="EFUSE_ILM", connections=(("U1", "7"), ("R3", "1"))),
            NetSpec(name="EFUSE_FLT", connections=(
                ("U1", "6"), ("R4", "2"), ("TP1", "1"),
            )),
            NetSpec(name="5V_PROTECTED", connections=(
                ("U1", "5"), ("C2", "1"), ("J2", "1"),
            )),
        )

        constraints = (
            PlacementConstraint(
                component_ref="D1",
                target_ref="J1",
                max_distance_mm=3.0,
                reason="TVS diode should be adjacent to USB-C VBUS/GND entry",
            ),
            PlacementConstraint(
                component_ref="R1",
                target_ref="J1",
                max_distance_mm=5.0,
                reason="CC1 Rd resistor close to USB-C receptacle",
            ),
            PlacementConstraint(
                component_ref="R2",
                target_ref="J1",
                max_distance_mm=5.0,
                reason="CC2 Rd resistor close to USB-C receptacle",
            ),
            PlacementConstraint(
                component_ref="C1",
                target_ref="U1",
                max_distance_mm=3.0,
                reason="eFuse input bypass close to IN/GND pins",
            ),
            PlacementConstraint(
                component_ref="C2",
                target_ref="U1",
                max_distance_mm=5.0,
                reason="Output bulk capacitor close to protected rail",
            ),
            PlacementConstraint(
                component_ref="C3",
                target_ref="U1",
                max_distance_mm=3.0,
                reason="dVdt capacitor close to eFuse control pin",
            ),
            PlacementConstraint(
                component_ref="R3",
                target_ref="U1",
                max_distance_mm=3.0,
                reason="ILM resistor close to eFuse current-limit pin",
            ),
            PlacementConstraint(
                component_ref="J1",
                target_ref=None,
                max_distance_mm=15.0,
                reason="USB-C receptacle on board edge",
            ),
            PlacementConstraint(
                component_ref="J2",
                target_ref=None,
                max_distance_mm=20.0,
                reason="Protected output terminal on board edge",
            ),
        )

        notes = (
            f"USB-C power-only sink for 5V at up to {spec.output_current:.2f}A",
            "CC1 and CC2 each use 5.1k Rd to request default USB-C sink power",
            "This is not USB-PD; do not expect more than default Type-C 5V current",
            "TPS259571DSGR provides current limiting, inrush control, and auto-retry",
            "680R ILM resistor sets a nominal current limit around 2.98A",
            "SMF5.0CA TVS protects VBUS before the eFuse input",
            "Verify connector, cable, copper width, and thermal rise before fabrication",
            "KiCad eFuse symbol is generic numeric until a proper TPS259571 symbol is added",
        )

        return DesignResult(
            spec=spec,
            components=components,
            nets=nets,
            placement_constraints=constraints,
            design_notes=notes,
        )
