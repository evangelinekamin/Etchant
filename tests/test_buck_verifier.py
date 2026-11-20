"""Tests for the buck output-voltage verification gate.

The integration and "money" tests run a real ngspice simulation and are
skipped when the binary is absent; the not-applicable path needs no simulation.
"""

from __future__ import annotations

import dataclasses
from unittest.mock import patch

import pytest

from etchant.circuits.generative_buck import GenerativeBuckConverter
from etchant.core.models import CircuitSpec, DesignResult
from etchant.sim.buck_verifier import VerifyResult, verify_buck
from etchant.sim.ngspice_runner import check_ngspice_available

requires_ngspice = pytest.mark.skipif(
    not check_ngspice_available(), reason="ngspice binary not on PATH"
)


def _generate_buck(vin: float, vout: float, iout: float) -> DesignResult:
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


def _mutate_r1(design: DesignResult, new_value: str) -> DesignResult:
    """Return a NEW design with R1's value replaced (frozen-safe rebuild)."""
    new_components = tuple(
        dataclasses.replace(component, value=new_value)
        if component.reference == "R1"
        else component
        for component in design.components
    )
    return dataclasses.replace(design, components=new_components)


class TestNotApplicable:
    def test_fixed_output_design_is_not_applicable(
        self, fixed_output_buck: DesignResult
    ) -> None:
        result = verify_buck(fixed_output_buck)
        assert isinstance(result, VerifyResult)
        assert result.applicable is False
        # A design the gate cannot judge must not be reported as a failure.
        assert result.passed is True
        assert "not applicable" in result.detail.lower()


@requires_ngspice
class TestRegulationPasses:
    def test_12v_to_3v3_within_tolerance(self) -> None:
        design = _generate_buck(12.0, 3.3, 1.0)
        result = verify_buck(design)

        assert result.applicable is True
        assert result.passed is True
        assert result.vout_target == pytest.approx(3.3)
        # E24 rounding of the ideal 31.25k top resistor down to 30k pulls the
        # real output to ~3.2V -- a genuine ~3% drift the gate should surface.
        assert result.vout_sim == pytest.approx(3.2, abs=0.05)
        assert result.error_pct < result.tolerance_pct


@requires_ngspice
class TestCatchesElectricallyWrongBoard:
    """The money test.

    A board whose feedback resistor is wrong is graph-complete, in stock, and
    passes DRC -- Etchant's existing four checks wave it through. Only an
    electrical simulation catches that it regulates to the wrong voltage.
    """

    def test_mutated_r1_fails_the_gate(self) -> None:
        good = _generate_buck(12.0, 3.3, 1.0)
        bad = _mutate_r1(good, "100k")  # ideal top resistor is ~30k

        result = verify_buck(bad)

        assert result.applicable is True
        assert result.passed is False
        # 100k/10k divider drives VOUT far above the 3.3V target.
        assert result.vout_sim > 6.0
        assert result.error_pct > 50.0

    def test_good_and_bad_differ_only_by_r1(self) -> None:
        good = _generate_buck(12.0, 3.3, 1.0)
        bad = _mutate_r1(good, "100k")
        good_r1 = next(c for c in good.components if c.reference == "R1")
        bad_r1 = next(c for c in bad.components if c.reference == "R1")
        assert good_r1.value != bad_r1.value
        # Everything else is untouched (immutability preserved).
        assert good.spec == bad.spec
        assert len(good.components) == len(bad.components)
