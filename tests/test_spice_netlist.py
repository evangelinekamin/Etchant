"""Tests for the buck SPICE netlist emitter and EE value parser.

These are pure-Python unit tests: they build deck strings and parse value
strings without invoking ngspice, so they run in every environment.
"""

from __future__ import annotations

import dataclasses
from unittest.mock import patch

import pytest

from etchant.circuits.generative_buck import GenerativeBuckConverter
from etchant.core.models import CircuitSpec, DesignResult
from etchant.sim.spice_netlist import (
    build_buck_deck,
    has_feedback_divider,
    parse_component_value,
)


def _generate_buck(vin: float, vout: float, iout: float) -> DesignResult:
    """Generate a real buck design offline (generic IC fallback)."""
    generator = GenerativeBuckConverter()
    spec = CircuitSpec(
        name=f"buck_{vin}_{vout}",
        topology="buck_converter",
        input_voltage=vin,
        output_voltage=vout,
        output_current=iout,
        description="test buck",
    )
    with patch.object(
        GenerativeBuckConverter, "_query_webench_live", return_value=None
    ):
        return generator.generate(spec)


class TestParseComponentValue:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("31.6k", 31_600.0),
            ("10k", 10_000.0),
            ("10.0k", 10_000.0),
            ("100k", 100_000.0),
            ("30.0k", 30_000.0),
            ("1M", 1_000_000.0),
            ("470", 470.0),
            ("4.7", 4.7),
            ("22uF", 22e-6),
            ("3.3uH", 3.3e-6),
            ("2.2µF", 2.2e-6),
            ("100n", 100e-9),
            ("10m", 10e-3),
            ("1p", 1e-12),
            ("  30.0k  ", 30_000.0),
        ],
    )
    def test_parses_values(self, text: str, expected: float) -> None:
        assert parse_component_value(text) == pytest.approx(expected)

    def test_micro_sign_and_letter_u_agree(self) -> None:
        assert parse_component_value("4.7µF") == parse_component_value("4.7uF")

    def test_milli_and_mega_are_case_sensitive(self) -> None:
        assert parse_component_value("2m") == pytest.approx(2e-3)
        assert parse_component_value("2M") == pytest.approx(2e6)

    @pytest.mark.parametrize("bad", ["", "   ", "abc", "k10", "..", "1.2.3"])
    def test_rejects_garbage(self, bad: str) -> None:
        with pytest.raises(ValueError):
            parse_component_value(bad)

    def test_rejects_non_string(self) -> None:
        with pytest.raises(ValueError):
            parse_component_value(123)  # type: ignore[arg-type]


class TestHasFeedbackDivider:
    def test_true_for_adjustable_buck(self) -> None:
        design = _generate_buck(12.0, 3.3, 1.0)
        assert has_feedback_divider(design) is True

    def test_false_for_fixed_output(
        self, fixed_output_buck: DesignResult
    ) -> None:
        assert has_feedback_divider(fixed_output_buck) is False


class TestBuildBuckDeck:
    def test_contains_real_divider_resistors(self) -> None:
        # 12V->3.3V rounds R1 to 30k over a fixed R2=10k.
        deck = build_buck_deck(_generate_buck(12.0, 3.3, 1.0))
        assert "30000" in deck  # R1 top resistor (ohms)
        assert "10000" in deck  # R2 bottom resistor (ohms)

    def test_contains_source_reference_and_feedback_node(self) -> None:
        deck = build_buck_deck(_generate_buck(12.0, 3.3, 1.0)).lower()
        assert "min(12" in deck  # Vin clamp
        assert "0.8" in deck  # Vref
        assert "v(fb)" in deck  # feedback node drives the regulator

    def test_emits_operating_point_analysis(self) -> None:
        deck = build_buck_deck(_generate_buck(12.0, 3.3, 1.0)).lower()
        assert ".control" in deck
        assert "\nop\n" in deck
        assert "print v(vout)" in deck
        assert ".end" in deck

    def test_load_reflects_target_over_current(self) -> None:
        # Rload = Vout_target / Iout = 3.3 / 1.0 = 3.3 ohms.
        deck = build_buck_deck(_generate_buck(12.0, 3.3, 1.0))
        assert "3.3" in deck

    def test_reflects_a_different_operating_point(self) -> None:
        # 12V->5V rounds R1 to 51k; the deck must track the real design.
        deck = build_buck_deck(_generate_buck(12.0, 5.0, 2.0))
        assert "51000" in deck

    def test_raises_without_feedback_divider(
        self, fixed_output_buck: DesignResult
    ) -> None:
        with pytest.raises(ValueError):
            build_buck_deck(fixed_output_buck)

    def test_raises_on_non_positive_current(self) -> None:
        design = _generate_buck(12.0, 3.3, 1.0)
        zero_current_spec = dataclasses.replace(design.spec, output_current=0.0)
        broken = dataclasses.replace(design, spec=zero_current_spec)
        with pytest.raises(ValueError):
            build_buck_deck(broken)
