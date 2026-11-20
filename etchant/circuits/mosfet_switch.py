"""Low-side N-channel MOSFET load switch.

Small control board for switching a load on/off from a microcontroller
pin: MCU drives the CTRL net high, the 2N7002 conducts, the load's
return path completes through the MOSFET to GND. 100Ω gate series
resistor slows the edge to reduce EMI; 10kΩ pulldown keeps the switch
off when CTRL floats.

Wiring (user-facing):
    J1.1  LOAD — connect to the low side of the load (drain)
    J1.2  GND  — shared ground with the MCU
    J1.3  CTRL — digital high from MCU turns the switch ON

Adds a control-circuit topology to the pipeline, complementing the
signal-path (op-amp) and reference (divider) boards.
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


class MosfetSwitchCircuit:
    """Low-side N-channel MOSFET switch generator (2N7002)."""

    @property
    def topology(self) -> str:
        return "mosfet_switch"

    def validate_spec(self, spec: CircuitSpec) -> tuple[str, ...]:
        errors: list[str] = []
        # 2N7002 Vds max is 60V; Id continuous is ~115mA.
        if spec.input_voltage > 60:
            errors.append(
                f"Load voltage {spec.input_voltage}V exceeds 2N7002 Vds rating (60V)"
            )
        if spec.output_current > 0.2:
            errors.append(
                f"Load current {spec.output_current}A exceeds 2N7002 continuous "
                f"rating (~0.115A). Use a higher-power MOSFET."
            )
        if spec.input_voltage <= 0:
            errors.append(
                f"Load voltage must be positive, got {spec.input_voltage}V"
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
                reference="Q1",
                category=ComponentCategory.IC,
                value="2N7002",
                footprint="Package_TO_SOT_SMD:SOT-23",
                kicad_library="Transistor_FET",
                kicad_symbol="2N7002",
                description="N-channel MOSFET, 60V Vds, 115mA Id",
                properties={
                    "vds_max": "60V",
                    "id_continuous_a": "0.115",
                    "rds_on_mohm": "1.5",  # at Vgs=10V
                    "vgs_th_max_v": "2.5",
                },
            ),
            # Gate series resistor — slows switching edge (EMI reduction).
            ComponentSpec(
                reference="R1",
                category=ComponentCategory.RESISTOR,
                value="100R",
                footprint="Resistor_SMD:R_0603_1608Metric",
                kicad_library="Device",
                kicad_symbol="R",
                description="Gate series resistor (slows edge)",
            ),
            # Gate pulldown — keeps the switch OFF when CTRL floats.
            ComponentSpec(
                reference="R2",
                category=ComponentCategory.RESISTOR,
                value="10k",
                footprint="Resistor_SMD:R_0603_1608Metric",
                kicad_library="Device",
                kicad_symbol="R",
                description="Gate pulldown (default OFF)",
            ),
            ComponentSpec(
                reference="J1",
                category=ComponentCategory.CONNECTOR,
                value="Conn_01x03",
                footprint=(
                    "Connector_PinHeader_2.54mm:"
                    "PinHeader_1x03_P2.54mm_Vertical"
                ),
                kicad_library="Connector_Generic",
                kicad_symbol="Conn_01x03",
                description="Header: LOAD, GND, CTRL",
            ),
        )

        # 2N7002 SOT-23 pinout: 1=G, 2=S, 3=D
        nets = (
            NetSpec(name="LOAD", connections=(
                ("J1", "1"), ("Q1", "D"),
            )),
            NetSpec(name="GND", connections=(
                ("J1", "2"), ("Q1", "S"), ("R2", "2"),
            )),
            NetSpec(name="CTRL", connections=(
                ("J1", "3"), ("R1", "1"),
            )),
            NetSpec(name="GATE", connections=(
                ("R1", "2"), ("R2", "1"), ("Q1", "G"),
            )),
        )

        constraints = (
            PlacementConstraint(
                component_ref="R1",
                target_ref="Q1",
                max_distance_mm=5.0,
                reason="Gate series resistor close to MOSFET gate",
            ),
            PlacementConstraint(
                component_ref="R2",
                target_ref="Q1",
                max_distance_mm=5.0,
                reason="Gate pulldown adjacent to gate net",
            ),
            PlacementConstraint(
                component_ref="J1",
                target_ref=None,
                max_distance_mm=20.0,
                reason="User header at board edge",
            ),
        )

        p_dissipated_mw = (
            spec.output_current * spec.output_current * 1.5  # I² * Rds_on (1.5Ω)
            * 1000
        )

        notes = (
            f"Low-side N-MOSFET switch: {spec.input_voltage}V, "
            f"{spec.output_current * 1000:.0f}mA load",
            "2N7002 SOT-23, Vgs,th = 2.5V max (works with 3.3V + 5V MCU logic)",
            "100Ω gate series + 10kΩ pulldown (default OFF)",
            f"Dissipation in MOSFET: ~{p_dissipated_mw:.1f}mW at rated current",
            "Wiring: J1 = LOAD, GND, CTRL (user's MCU pin)",
            "Add a flyback diode across the load if switching inductive loads",
            "All SMD — JLCPCB basic parts",
        )

        return DesignResult(
            spec=spec,
            components=components,
            nets=nets,
            placement_constraints=constraints,
            design_notes=notes,
        )
