"""Programmable voltage divider / reference generator.

Two-resistor divider with output buffering cap — classic ADC reference
or bias-voltage generator. Takes a spec's input_voltage and
output_voltage and picks the nearest E24 resistor pair to hit the
ratio, then emits the board.

Great complement to the op-amp buffer: divider + buffer = complete
low-impedance voltage reference. Also useful on its own for biasing
single-supply op-amp inputs or setting a threshold for a comparator.

Circuit:
    VIN ---R1--- VOUT ---R2--- GND
                   |
                  C1 (buffer)
                   |
                  GND
"""

from __future__ import annotations

import math

from etchant.core.models import (
    CircuitSpec,
    ComponentCategory,
    ComponentSpec,
    DesignResult,
    NetSpec,
    PlacementConstraint,
)

# E24 standard resistor values (1kΩ decade — multiply for other decades).
_E24 = (
    1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0,
    3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1,
)


def _pick_divider_pair(
    vin: float, vout: float, target_total_kohm: float = 20.0,
) -> tuple[float, float]:
    """Pick R1 (top, kΩ) and R2 (bottom) to best match vout/vin ratio.

    Keeps the total roughly at target_total_kohm so the divider doesn't
    load the source heavily or draw excessive quiescent current.

    vout = vin * R2 / (R1 + R2), so ratio = R2 / (R1+R2).
    """
    if vout >= vin:
        raise ValueError(
            f"Divider output {vout}V must be less than input {vin}V",
        )
    ratio = vout / vin

    # Enumerate candidate R1 across a few decades of E24 and derive R2;
    # pick the pair closest to the target ratio.
    best: tuple[float, float] | None = None
    best_err = float("inf")
    for decade in (1, 10, 100):
        for r1_base in _E24:
            r1 = r1_base * decade
            # Target R2 from ratio algebra: R2 = R1 * ratio / (1 - ratio)
            r2_ideal = r1 * ratio / (1 - ratio)
            # Snap R2 to nearest E24 value (same decade or neighbors)
            candidates = []
            for r2_decade in (decade / 10, decade, decade * 10):
                if r2_decade < 0.1:
                    continue
                candidates.extend(v * r2_decade for v in _E24)
            r2 = min(candidates, key=lambda v: abs(v - r2_ideal))
            actual_ratio = r2 / (r1 + r2)
            err = abs(actual_ratio - ratio)
            total = r1 + r2
            # Prefer pairs near the target total
            err_weighted = err + abs(total - target_total_kohm) * 1e-6
            if err_weighted < best_err:
                best_err = err_weighted
                best = (r1, r2)

    assert best is not None
    return best


def _format_resistor(value_kohm: float) -> str:
    """Human-readable resistor value (e.g. '10k', '100R', '4.7k', '1M')."""
    if value_kohm >= 1000:
        return f"{value_kohm / 1000:g}M"
    if value_kohm >= 1:
        return f"{value_kohm:g}k"
    return f"{value_kohm * 1000:g}R"


class VoltageDividerCircuit:
    """Two-resistor voltage divider with output bypass cap."""

    @property
    def topology(self) -> str:
        return "voltage_divider"

    def validate_spec(self, spec: CircuitSpec) -> tuple[str, ...]:
        errors: list[str] = []
        if spec.input_voltage <= 0:
            errors.append(f"Input voltage must be positive, got {spec.input_voltage}V")
        if spec.output_voltage <= 0:
            errors.append(f"Output voltage must be positive, got {spec.output_voltage}V")
        if spec.output_voltage >= spec.input_voltage:
            errors.append(
                f"Output voltage ({spec.output_voltage}V) must be less than "
                f"input ({spec.input_voltage}V) for a passive divider"
            )
        if spec.input_voltage > 30:
            errors.append(
                f"Input voltage {spec.input_voltage}V exceeds sane divider range. "
                f"Use an LDO/buck first."
            )
        return tuple(errors)

    def generate(self, spec: CircuitSpec) -> DesignResult:
        errors = self.validate_spec(spec)
        if errors:
            raise ValueError(f"Invalid spec: {'; '.join(errors)}")
        return self._build_design(spec)

    def _build_design(self, spec: CircuitSpec) -> DesignResult:
        r1_k, r2_k = _pick_divider_pair(spec.input_voltage, spec.output_voltage)
        actual_vout = spec.input_voltage * r2_k / (r1_k + r2_k)
        error_pct = abs(actual_vout - spec.output_voltage) / spec.output_voltage * 100

        quiescent_ua = spec.input_voltage / (r1_k + r2_k) * 1000  # I = V/R, μA

        components = (
            ComponentSpec(
                reference="R1",
                category=ComponentCategory.RESISTOR,
                value=_format_resistor(r1_k),
                footprint="Resistor_SMD:R_0603_1608Metric",
                kicad_library="Device",
                kicad_symbol="R",
                description=f"Top resistor ({_format_resistor(r1_k)})",
            ),
            ComponentSpec(
                reference="R2",
                category=ComponentCategory.RESISTOR,
                value=_format_resistor(r2_k),
                footprint="Resistor_SMD:R_0603_1608Metric",
                kicad_library="Device",
                kicad_symbol="R",
                description=f"Bottom resistor ({_format_resistor(r2_k)})",
            ),
            ComponentSpec(
                reference="C1",
                category=ComponentCategory.CAPACITOR,
                value="100nF",
                footprint="Capacitor_SMD:C_0603_1608Metric",
                kicad_library="Device",
                kicad_symbol="C",
                description="Output bypass (reduces noise on VREF)",
                properties={"type": "ceramic", "dielectric": "X7R"},
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
                description="3-pin header: VIN, GND, VOUT",
            ),
        )

        nets = (
            NetSpec(name="VIN", connections=(("J1", "1"), ("R1", "1"))),
            NetSpec(name="GND", connections=(
                ("J1", "2"), ("R2", "2"), ("C1", "2"),
            )),
            NetSpec(name="VOUT", connections=(
                ("R1", "2"), ("R2", "1"), ("C1", "1"), ("J1", "3"),
            )),
        )

        constraints = (
            PlacementConstraint(
                component_ref="R1",
                target_ref=None,
                max_distance_mm=15.0,
                reason="Top resistor in the divider chain",
            ),
            PlacementConstraint(
                component_ref="R2",
                target_ref="R1",
                max_distance_mm=5.0,
                reason="Bottom resistor adjacent to top for short VOUT trace",
            ),
            PlacementConstraint(
                component_ref="C1",
                target_ref="R2",
                max_distance_mm=5.0,
                reason="Bypass cap on output node, close to divider tap",
            ),
            PlacementConstraint(
                component_ref="J1",
                target_ref=None,
                max_distance_mm=20.0,
                reason="Signal header at board edge",
            ),
        )

        notes = (
            f"Voltage divider: {spec.input_voltage}V -> {actual_vout:.3f}V "
            f"(target {spec.output_voltage}V, error {error_pct:.2f}%)",
            f"R1={_format_resistor(r1_k)} top, R2={_format_resistor(r2_k)} bottom",
            f"Quiescent current: {quiescent_ua:.1f} μA at V_IN",
            "100nF output bypass filters resistor Johnson noise",
            "3-pin header: VIN / GND / V_REF",
            "Add an op-amp buffer downstream for low-impedance loads",
            "All SMD 0603 passives — JLCPCB basic parts",
        )

        return DesignResult(
            spec=spec,
            components=components,
            nets=nets,
            placement_constraints=constraints,
            design_notes=notes,
        )
