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

from dataclasses import dataclass

from etchant.core.models import (
    CircuitSpec,
    ComponentCategory,
    ComponentSpec,
    DesignResult,
    NetSpec,
    PlacementConstraint,
)


@dataclass(frozen=True)
class _MosfetOption:
    value: str
    footprint: str
    kicad_library: str
    kicad_symbol: str
    description: str
    max_voltage: float
    max_current: float
    practical_current: float
    rds_on_ohm: float
    gate_drive: str
    properties: dict[str, str]
    jlcpcb_part_number: str | None = None


_SIGNAL_MOSFET = _MosfetOption(
    value="2N7002",
    footprint="Package_TO_SOT_SMD:SOT-23",
    kicad_library="Transistor_FET",
    kicad_symbol="2N7002",
    description="Small-signal N-channel MOSFET, 60V Vds, 115mA continuous",
    max_voltage=60.0,
    max_current=0.2,
    practical_current=0.115,
    rds_on_ohm=1.5,
    gate_drive="3.3V/5V logic",
    properties={
        "vds_max": "60V",
        "id_continuous_a": "0.115",
        "rds_on_ohm": "1.5",
        "vgs_th_max_v": "2.5",
        "current_class": "signal",
    },
)

_SOT23_POWER_MOSFET = _MosfetOption(
    value="AO3400A-class",
    footprint="Package_TO_SOT_SMD:SOT-23",
    kicad_library="Device",
    kicad_symbol="Q_NMOS",
    description="Logic-level N-channel power MOSFET class, 30V, SOT-23",
    max_voltage=30.0,
    max_current=5.0,
    practical_current=2.0,
    rds_on_ohm=0.055,
    gate_drive="logic-level; verify Rds(on) at your MCU voltage",
    properties={
        "vds_max": "30V",
        "id_design_limit_a": "3.0",
        "rds_on_ohm_typ": "0.055",
        "current_class": "power_sot23",
        "selection_status": "generic_class_requires_part_verification",
    },
)

_POWERPAK_MOSFET = _MosfetOption(
    value="SQJA36EP-T1_GE3",
    footprint="Package_SO:PowerPAK_SO-8L_Single",
    kicad_library="Device",
    kicad_symbol="Q_NMOS",
    description="Low-Rds(on) N-channel MOSFET, 40V, PowerPAK SO-8L",
    max_voltage=40.0,
    max_current=20.0,
    practical_current=10.0,
    rds_on_ohm=0.00124,
    gate_drive="5V-10V gate drive recommended for low Rds(on)",
    jlcpcb_part_number="C2761031",
    properties={
        "vds_max": "40V",
        "id_design_limit_a": "10.0",
        "rds_on_ohm_typ": "0.00124",
        "current_class": "power_pak",
        "jlcpcb_classification": "extended",
        "gate_drive_note": "verify 3.3V gate drive or add a MOSFET driver",
    },
)


class MosfetSwitchCircuit:
    """Low-side N-channel MOSFET switch generator."""

    @property
    def topology(self) -> str:
        return "mosfet_switch"

    def validate_spec(self, spec: CircuitSpec) -> tuple[str, ...]:
        errors: list[str] = []
        if spec.input_voltage <= 0:
            errors.append(
                f"Load voltage must be positive, got {spec.input_voltage}V"
            )
        if spec.output_current <= 0:
            errors.append(
                f"Load current must be positive, got {spec.output_current}A"
            )
        if errors:
            return tuple(errors)

        option = _select_mosfet(spec)
        if option is None:
            errors.append(
                f"No low-side MOSFET option covers {spec.input_voltage}V at "
                f"{spec.output_current}A. Add a dedicated load-switch or "
                "gate-driver topology."
            )
        return tuple(errors)

    def generate(self, spec: CircuitSpec) -> DesignResult:
        errors = self.validate_spec(spec)
        if errors:
            raise ValueError(f"Invalid spec: {'; '.join(errors)}")
        return self._build_design(spec)

    def _build_design(self, spec: CircuitSpec) -> DesignResult:
        option = _select_mosfet(spec)
        if option is None:
            raise ValueError("No MOSFET option selected")

        components = (
            ComponentSpec(
                reference="Q1",
                category=ComponentCategory.IC,
                value=option.value,
                footprint=option.footprint,
                kicad_library=option.kicad_library,
                kicad_symbol=option.kicad_symbol,
                description=option.description,
                properties=option.properties,
                jlcpcb_part_number=option.jlcpcb_part_number,
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
                footprint=_connector_footprint(spec.output_current),
                kicad_library="Connector_Generic",
                kicad_symbol="Conn_01x03",
                description="Header: LOAD, GND, CTRL",
            ),
        )

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

        p_dissipated_mw = spec.output_current * spec.output_current * option.rds_on_ohm * 1000

        notes = (
            f"Low-side N-MOSFET switch: {spec.input_voltage}V, "
            f"{spec.output_current:.2f}A load",
            f"Selected MOSFET: {option.value} ({option.properties['current_class']})",
            f"Gate drive: {option.gate_drive}",
            "100Ω gate series + 10kΩ pulldown (default OFF)",
            f"Estimated MOSFET dissipation: ~{p_dissipated_mw:.1f}mW at requested current",
            "Wiring: J1 = LOAD, GND, CTRL (user's MCU pin)",
            "Add a flyback diode across the load if switching inductive loads",
            "For high-side power-path switching, use a dedicated load-switch topology.",
        )

        return DesignResult(
            spec=spec,
            components=components,
            nets=nets,
            placement_constraints=constraints,
            design_notes=notes,
        )


def _select_mosfet(spec: CircuitSpec) -> _MosfetOption | None:
    """Select a MOSFET class by voltage/current with conservative derating."""
    options = (_SIGNAL_MOSFET, _SOT23_POWER_MOSFET, _POWERPAK_MOSFET)
    for option in options:
        if (
            spec.input_voltage <= option.max_voltage
            and spec.output_current <= option.practical_current
        ):
            return option
    return None


def _connector_footprint(current_a: float) -> str:
    if current_a <= 0.5:
        return "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical"
    if current_a <= 2.0:
        return "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical_SMD_Pin1Right"
    return "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-3-5.08_1x03_P5.08mm_Horizontal"
