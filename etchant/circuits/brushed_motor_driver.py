"""Low-voltage reversible brushed DC motor driver.

Uses TI's DRV8837 single H-bridge for small motors from 1.8V to 7V. This is
intended for the common "small 6V motor around 1A" use case: forward/reverse,
brake/coast via IN1/IN2 PWM, and a dedicated nSLEEP control input.
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


class BrushedMotorDriver:
    """DRV8837 single-H-bridge brushed motor driver generator."""

    @property
    def topology(self) -> str:
        return "brushed_motor_driver"

    def validate_spec(self, spec: CircuitSpec) -> tuple[str, ...]:
        errors: list[str] = []
        if spec.input_voltage < 1.8 or spec.input_voltage > 7.0:
            errors.append(
                f"Motor supply must be in DRV8837 range 1.8..7.0V, "
                f"got {spec.input_voltage}V"
            )
        if spec.output_current <= 0:
            errors.append(f"Motor current must be positive, got {spec.output_current}A")
        if spec.output_current > 1.0:
            errors.append(
                f"Requested {spec.output_current}A exceeds the conservative 1A "
                "continuous design target; check stall current and thermals."
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
                reference="U1",
                category=ComponentCategory.IC,
                value="DRV8837DSGR",
                footprint=(
                    "Package_SON:"
                    "Texas_DSG0008A_WSON-8-1EP_2x2mm_P0.5mm_EP0.9x1.6mm"
                ),
                # KiCad 9 lacks this symbol in the tested environment. Use a
                # generic 9-pin symbol whose pins map 1:1 to the WSON pads.
                kicad_library="Connector_Generic",
                kicad_symbol="Conn_01x09",
                description="DRV8837 1.8A low-voltage H-bridge motor driver",
                properties={
                    "symbol_note": "generic numeric symbol; pad wiring follows DRV8837 DSG pinout",
                    "driver_interface": "IN1/IN2 PWM",
                    "vm_range": "1.8..7.0V",
                    "continuous_current_design_a": "1.0",
                },
                jlcpcb_part_number="C39159",
            ),
            ComponentSpec(
                reference="C1",
                category=ComponentCategory.CAPACITOR,
                value="10uF",
                footprint="Capacitor_SMD:C_0805_2012Metric",
                kicad_library="Device",
                kicad_symbol="C",
                description="Motor supply bulk capacitor",
                jlcpcb_part_number="C15850",
            ),
            ComponentSpec(
                reference="C2",
                category=ComponentCategory.CAPACITOR,
                value="100nF",
                footprint="Capacitor_SMD:C_0603_1608Metric",
                kicad_library="Device",
                kicad_symbol="C",
                description="Local VM bypass capacitor",
                jlcpcb_part_number="C14663",
            ),
            ComponentSpec(
                reference="J1",
                category=ComponentCategory.CONNECTOR,
                value="Conn_01x02",
                footprint="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal",
                kicad_library="Connector_Generic",
                kicad_symbol="Conn_01x02",
                description="Motor output terminal: OUT1, OUT2",
            ),
            ComponentSpec(
                reference="J2",
                category=ComponentCategory.CONNECTOR,
                value="Conn_01x05",
                footprint=(
                    "Connector_PinHeader_2.54mm:"
                    "PinHeader_1x05_P2.54mm_Vertical"
                ),
                kicad_library="Connector_Generic",
                kicad_symbol="Conn_01x05",
                description="Control/power header: VM, GND, IN1, IN2, nSLEEP",
            ),
        )

        # DRV8837 DSG pinout: 1=VM, 2=OUT1, 3=OUT2, 4=GND,
        # 5=IN2, 6=IN1, 7=nSLEEP, 8=VCC, 9=exposed pad/GND.
        nets = (
            NetSpec(name="VM", connections=(
                ("J2", "1"), ("U1", "1"), ("C1", "1"), ("C2", "1"),
            )),
            NetSpec(name="GND", connections=(
                ("J2", "2"), ("U1", "4"), ("U1", "9"), ("C1", "2"), ("C2", "2"),
            )),
            NetSpec(name="IN1", connections=(("J2", "3"), ("U1", "6"))),
            NetSpec(name="IN2", connections=(("J2", "4"), ("U1", "5"))),
            NetSpec(name="NSLEEP", connections=(("J2", "5"), ("U1", "7"), ("U1", "8"))),
            NetSpec(name="OUT1", connections=(("U1", "2"), ("J1", "1"))),
            NetSpec(name="OUT2", connections=(("U1", "3"), ("J1", "2"))),
        )

        constraints = (
            PlacementConstraint(
                component_ref="C1",
                target_ref="U1",
                max_distance_mm=8.0,
                reason="Bulk capacitor close to motor supply pin",
            ),
            PlacementConstraint(
                component_ref="C2",
                target_ref="U1",
                max_distance_mm=3.0,
                reason="HF bypass adjacent to VM/GND",
            ),
            PlacementConstraint(
                component_ref="J1",
                target_ref=None,
                max_distance_mm=20.0,
                reason="Motor terminal at board edge",
            ),
            PlacementConstraint(
                component_ref="J2",
                target_ref=None,
                max_distance_mm=20.0,
                reason="Control/power header at board edge",
            ),
        )

        notes = (
            f"DRV8837 brushed DC motor driver for {spec.input_voltage}V, "
            f"{spec.output_current:.2f}A design load",
            "Use IN1/IN2 for PWM direction/brake/coast control",
            "nSLEEP and VCC are tied to J2 pin 5 in this first-pass control header",
            "Verify motor stall current; design target is 1A continuous, not stall",
            "Add bulk capacitance near J2 if motor leads are long or supply is weak",
            "KiCad symbol is generic numeric until a proper DRV8837 symbol is added",
        )

        return DesignResult(
            spec=spec,
            components=components,
            nets=nets,
            placement_constraints=constraints,
            design_notes=notes,
        )
