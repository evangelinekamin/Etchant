"""Op-amp unity-gain buffer (voltage follower).

A classic analog building block: input signal passed to a high-impedance
op-amp input, output shorted back to inverting input. Result is Zout << Zin,
used to drive loads that would sag a signal source.

Differentiates the generator from the power-supply topologies already
in the pipeline — signal-path circuit, not DC-DC, shows the generator
handles analog blocks too.

Uses MCP6001UT-I/OT in SOT-23-5. It is a rail-to-rail single op-amp
with 1MHz GBW — plenty for audio/sensor buffering.
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


class OpAmpBufferCircuit:
    """Unity-gain op-amp buffer generator."""

    @property
    def topology(self) -> str:
        return "op_amp_buffer"

    def validate_spec(self, spec: CircuitSpec) -> tuple[str, ...]:
        errors: list[str] = []
        # MCP6001 supply range is 1.8..6.0V. Accept any sensible single supply.
        if spec.input_voltage < 1.8 or spec.input_voltage > 6.0:
            errors.append(
                f"Supply voltage must be in 1.8..6.0V (MCP6001 range), "
                f"got {spec.input_voltage}V"
            )
        # output_current isn't really meaningful for a buffer — op-amp can
        # source/sink ~22mA — but we accept any value and the user's spec
        # stays honest to the fact that this isn't a power stage.
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
                value="MCP6001UT-I/OT",
                footprint="Package_TO_SOT_SMD:SOT-23-5",
                kicad_library="Amplifier_Operational",
                kicad_symbol="MCP6001-OT",
                description="1MHz rail-to-rail op-amp, SOT-23-5",
                properties={
                    "gbw_mhz": "1",
                    "input_type": "rail-to-rail",
                    "output_type": "rail-to-rail",
                    "supply_range_v": "1.8..6.0",
                },
                jlcpcb_part_number="C21403",
            ),
            ComponentSpec(
                reference="C1",
                category=ComponentCategory.CAPACITOR,
                value="100nF",
                footprint="Capacitor_SMD:C_0402_1005Metric",
                kicad_library="Device",
                kicad_symbol="C",
                description="Supply bypass (close to V+ pin)",
                properties={"type": "ceramic", "dielectric": "X7R"},
            ),
            # 4-pin header: VCC, GND, VIN (signal in), VOUT (buffered out).
            ComponentSpec(
                reference="J1",
                category=ComponentCategory.CONNECTOR,
                value="Conn_01x04",
                footprint=(
                    "Connector_PinHeader_2.54mm:"
                    "PinHeader_1x04_P2.54mm_Vertical"
                ),
                kicad_library="Connector_Generic",
                kicad_symbol="Conn_01x04",
                description="Power + signal header (VCC, GND, VIN, VOUT)",
            ),
        )

        # MCP6001-OT pinout (SOT-23-5):
        #   1 = OUT,  2 = V-,  3 = IN+,  4 = IN-,  5 = V+
        # Unity-gain buffer ties OUT back to IN- — so pins 1 and 4 share
        # the VOUT net, pin 3 takes VIN, pin 5 is VCC, pin 2 is GND.
        nets = (
            NetSpec(name="VCC", connections=(
                ("J1", "1"), ("U1", "V+"), ("C1", "1"),
            )),
            NetSpec(name="GND", connections=(
                ("J1", "2"), ("U1", "V-"), ("C1", "2"),
            )),
            NetSpec(name="VIN", connections=(
                ("J1", "3"), ("U1", "+"),
            )),
            NetSpec(name="VOUT", connections=(
                ("J1", "4"), ("U1", "~"), ("U1", "-"),
            )),
        )

        constraints = (
            PlacementConstraint(
                component_ref="C1",
                target_ref="U1",
                max_distance_mm=3.0,
                reason="Supply bypass must be adjacent to V+ pin",
            ),
            PlacementConstraint(
                component_ref="J1",
                target_ref=None,
                max_distance_mm=25.0,
                reason="Signal/power header at board edge",
            ),
        )

        notes = (
            f"Op-amp unity-gain buffer on {spec.input_voltage}V supply",
            "MCP6001 rail-to-rail, 1MHz GBW — OK for audio/sensor buffering",
            "Pin 1 (OUT) tied to Pin 4 (IN-) for Av = +1",
            "100nF supply bypass close to V+ pin",
            "4-pin header: VCC / GND / V_IN / V_OUT",
            "All SMD — JLCPCB assembly compatible",
        )

        return DesignResult(
            spec=spec,
            components=components,
            nets=nets,
            placement_constraints=constraints,
            design_notes=notes,
        )
