"""Translate a buck-converter design into an ngspice simulation deck.

Slice 1 verifies output-voltage regulation only. Rather than simulating the
switching stage, the regulator is modelled as an ideal high-gain block that
drives VOUT until the feedback node settles at the reference voltage, using the
design's real feedback-divider resistors. A wrong divider therefore produces a
wrong VOUT, which is exactly what the verification gate is built to catch.
"""

from __future__ import annotations

import re

from etchant.core.models import ComponentSpec, DesignResult

DEFAULT_VREF = 0.8
"""Feedback reference voltage assumed for adjustable buck regulators.

Matches the 0.8 V reference the generative buck converter designs against
(see ``etchant.circuits.generative_buck``). Exposed as a parameter so a later
slice can source it per-IC.
"""

DEFAULT_GAIN = 1e5
"""Open-loop gain of the behavioural regulator block.

High enough that the settled VOUT tracks the ideal divider ratio to well under
0.01%, low enough that the algebraic feedback loop converges reliably for
realistic divider values.
"""

# SI prefixes accepted by ``parse_component_value``. Case matters: lowercase
# ``m`` is milli, uppercase ``M`` is mega.
_SI_PREFIXES = {
    "p": 1e-12,
    "n": 1e-9,
    "u": 1e-6,
    "µ": 1e-6,
    "m": 1e-3,
    "k": 1e3,
    "M": 1e6,
}

# number, optional SI prefix, optional trailing unit letters (F, H, ohm, ...).
_VALUE_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([pnuµmkM]?)\s*([a-zA-ZΩ]*)\s*$")


def parse_component_value(value: str) -> float:
    """Parse an EE value string into a base-unit float.

    Handles an optional SI prefix (``p n u µ m k M``) and an optional trailing
    unit that is ignored::

        "31.6k" -> 31600.0
        "10k"   -> 10000.0
        "22uF"  -> 2.2e-05
        "3.3uH" -> 3.3e-06
        "470"   -> 470.0

    Raises ValueError on anything that is not a number with an optional prefix.
    """
    if not isinstance(value, str):
        raise ValueError(f"component value must be a string, got {type(value)!r}")
    match = _VALUE_RE.match(value)
    if match is None:
        raise ValueError(f"unparseable component value: {value!r}")
    number, prefix, _unit = match.groups()
    multiplier = _SI_PREFIXES[prefix] if prefix else 1.0
    return float(number) * multiplier


def find_component(design: DesignResult, reference: str) -> ComponentSpec | None:
    """Return the component with the given reference, or None if absent."""
    for component in design.components:
        if component.reference == reference:
            return component
    return None


def has_feedback_divider(design: DesignResult) -> bool:
    """True when the design is an adjustable buck with an R1/R2/FB divider."""
    has_r1 = find_component(design, "R1") is not None
    has_r2 = find_component(design, "R2") is not None
    has_fb = any(net.name == "FB" for net in design.nets)
    return has_r1 and has_r2 and has_fb


def build_buck_deck(
    design: DesignResult,
    *,
    gain: float = DEFAULT_GAIN,
    vref: float = DEFAULT_VREF,
) -> str:
    """Build an ngspice deck that checks an adjustable buck's regulated VOUT.

    Raises ValueError if the design has no feedback divider (see
    ``has_feedback_divider``); callers should check applicability first.
    """
    if not has_feedback_divider(design):
        raise ValueError(
            "design has no R1/R2/FB feedback divider; output-voltage "
            "verification only applies to adjustable buck converters"
        )

    r1 = find_component(design, "R1")
    r2 = find_component(design, "R2")
    assert r1 is not None and r2 is not None  # guaranteed by check above
    r1_ohms = parse_component_value(r1.value)
    r2_ohms = parse_component_value(r2.value)

    spec = design.spec
    if spec.output_current <= 0:
        raise ValueError(
            f"output current must be positive, got {spec.output_current}"
        )
    rload_ohms = spec.output_voltage / spec.output_current

    return _render_deck(
        vin=spec.input_voltage,
        vref=vref,
        gain=gain,
        r1_ohms=r1_ohms,
        r2_ohms=r2_ohms,
        rload_ohms=rload_ohms,
    )


def _render_deck(
    *,
    vin: float,
    vref: float,
    gain: float,
    r1_ohms: float,
    r2_ohms: float,
    rload_ohms: float,
) -> str:
    """Render the behavioural-regulator deck for the given parameters."""
    return (
        "* etchant buck output-voltage verification (behavioural regulator)\n"
        "* VOUT is driven until the feedback node settles at Vref, using the\n"
        "* design's real divider resistors R1 (VOUT->FB) and R2 (FB->GND).\n"
        f"Bout vout 0 V = max(0, min({vin:g}, {gain:g}*({vref:g} - V(fb))))\n"
        f"R1 vout fb {r1_ohms:g}\n"
        f"R2 fb 0 {r2_ohms:g}\n"
        f"Rload vout 0 {rload_ohms:g}\n"
        ".control\n"
        "op\n"
        "print v(vout)\n"
        ".endc\n"
        ".end\n"
    )
