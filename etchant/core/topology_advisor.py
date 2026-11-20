"""Topology advisor for recommending circuit types from requirements.

Maps power supply requirements to the best circuit topology based on
voltage, current, efficiency needs, noise requirements, and cost.
This is the rule-based fallback — the LLM agent uses this when it needs
a structured recommendation rather than relying on training data alone.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TopologyRecommendation:
    """A recommended circuit topology with reasoning."""

    topology: str
    confidence: float  # 0.0 to 1.0
    reason: str
    tradeoffs: tuple[str, ...]
    alternatives: tuple[str, ...]


def recommend_topology(
    input_voltage: float,
    output_voltage: float,
    output_current: float,
    priority: str = "balanced",
) -> TopologyRecommendation:
    """Recommend a circuit topology based on electrical requirements.

    Args:
        input_voltage: Input voltage in volts
        output_voltage: Output voltage in volts
        output_current: Output current in amps
        priority: One of "efficiency", "noise", "cost", "size",
            "usb_power", "protection", or "balanced"
    """
    is_step_down = output_voltage < input_voltage
    is_same_voltage = output_voltage == input_voltage
    normalized_priority = priority.lower().replace("-", "_")
    voltage_diff = abs(input_voltage - output_voltage)
    power_dissipation = voltage_diff * output_current

    if (
        is_same_voltage
        and input_voltage == 5.0
        and output_current <= 3.0
        and normalized_priority in {"usb_power", "usb_c", "usb", "protection"}
    ):
        return TopologyRecommendation(
            topology="usb_c_sink_protection",
            confidence=0.85,
            reason=(
                "5V in/out with a USB/protection priority is a power-path input, "
                "not a regulator; use the USB-C sink protection topology with "
                "CC Rd resistors, VBUS TVS, and an eFuse"
            ),
            tradeoffs=(
                "No USB-PD negotiation or advertised-current detection",
                "3A operation still depends on the source, cable, connector, copper, and thermals",
                "Uses at least one Extended JLCPCB part for the eFuse/TVS",
            ),
            alternatives=("mosfet_switch", "dedicated_load_switch"),
        )

    # Same-voltage case: this is not a regulator, it is usually load switching
    # or protection. Route to the MOSFET switch topology as the current generic
    # load-control primitive.
    if is_same_voltage:
        return TopologyRecommendation(
            topology="mosfet_switch",
            confidence=0.65,
            reason=(
                f"Input and output are both {input_voltage}V, so no regulation "
                "is required; use a load-switch/MOSFET control topology"
            ),
            tradeoffs=(
                "Current topology is low-side switching, not high-side power-path control",
                "High-current loads need MOSFET thermal review and suitable connectors",
            ),
            alternatives=("dedicated_load_switch", "high_side_switch"),
        )

    # Step-up case — we don't support this yet
    if not is_step_down:
        return TopologyRecommendation(
            topology="buck_converter",
            confidence=0.0,
            reason=(
                f"Output voltage ({output_voltage}V) >= input ({input_voltage}V) "
                f"requires a boost converter, which is not yet implemented"
            ),
            tradeoffs=("Boost converter topology needed but not available",),
            alternatives=(),
        )

    # Very small dropout — LDO is ideal
    if voltage_diff <= 2.0 and output_current <= 1.0:
        if priority == "efficiency" and power_dissipation > 0.5:
            return _buck_recommendation(
                input_voltage, output_voltage, output_current,
                reason=(
                    f"Low dropout ({voltage_diff}V) normally favors LDO, but "
                    f"efficiency priority and {power_dissipation:.1f}W dissipation "
                    f"makes a buck converter more appropriate"
                ),
            )
        return TopologyRecommendation(
            topology="ldo_regulator",
            confidence=0.9,
            reason=(
                f"Low voltage dropout ({voltage_diff:.1f}V) and moderate current "
                f"({output_current}A) — LDO is simple, low-noise, and low-cost"
            ),
            tradeoffs=(
                f"Power dissipation: {power_dissipation:.2f}W as heat",
                "Lower efficiency than a switching regulator",
            ),
            alternatives=("buck_converter",),
        )

    # High current or large voltage difference — buck converter
    if output_current > 1.0 or voltage_diff > 5.0:
        return _buck_recommendation(
            input_voltage, output_voltage, output_current,
            reason=(
                f"{'High current' if output_current > 1.0 else 'Large voltage drop'} "
                f"({voltage_diff}V, {output_current}A) requires efficient switching "
                f"regulation to avoid excessive heat"
            ),
        )

    # Moderate case — depends on priority
    if priority == "noise":
        return TopologyRecommendation(
            topology="ldo_regulator",
            confidence=0.7,
            reason=(
                f"Noise-sensitive application — LDO provides cleaner output "
                f"than switching regulator at the cost of {power_dissipation:.1f}W dissipation"
            ),
            tradeoffs=(
                f"Power dissipation: {power_dissipation:.2f}W",
                "May need heatsink depending on thermal environment",
            ),
            alternatives=("buck_converter",),
        )

    if priority == "cost":
        return TopologyRecommendation(
            topology="ldo_regulator",
            confidence=0.8,
            reason=(
                "LDO has fewer components (3 vs 6) and all basic JLCPCB parts "
                "($0 setup fee vs ~$12 for a buck converter)"
            ),
            tradeoffs=(
                f"Power dissipation: {power_dissipation:.2f}W",
                "Less efficient than switching regulator",
            ),
            alternatives=("buck_converter",),
        )

    if priority == "efficiency":
        return _buck_recommendation(
            input_voltage, output_voltage, output_current,
            reason=(
                f"Efficiency priority — buck converter achieves 85-95% vs "
                f"~{100 * output_voltage / input_voltage:.0f}% for an LDO"
            ),
        )

    # Balanced: use power dissipation as tiebreaker
    if power_dissipation > 1.0:
        return _buck_recommendation(
            input_voltage, output_voltage, output_current,
            reason=(
                f"Power dissipation ({power_dissipation:.1f}W) exceeds comfortable "
                f"LDO range — switching regulator recommended"
            ),
        )

    return TopologyRecommendation(
        topology="ldo_regulator",
        confidence=0.6,
        reason=(
            f"Moderate requirements ({voltage_diff}V drop, {output_current}A, "
            f"{power_dissipation:.1f}W) — LDO is simpler and cheaper"
        ),
        tradeoffs=(
            f"Power dissipation: {power_dissipation:.2f}W",
            "Buck converter would be more efficient",
        ),
        alternatives=("buck_converter",),
    )


def _buck_recommendation(
    input_voltage: float,
    output_voltage: float,
    output_current: float,
    reason: str,
) -> TopologyRecommendation:
    return TopologyRecommendation(
        topology="buck_converter",
        confidence=0.85,
        reason=reason,
        tradeoffs=(
            "More components and higher assembly cost than LDO",
            "Switching noise on output — may need additional filtering",
        ),
        alternatives=("ldo_regulator",),
    )
