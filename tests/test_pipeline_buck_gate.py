"""Tests for the buck electrical verification gate wired into the pipeline.

Two layers:
- the gate helper (`_verify_buck_electrical`): topology scoping, fail-safe on a
  missing simulator, and applicability -- most of which need no ngspice;
- the pipeline integration: a correct buck reaches fab export while a
  sabotaged one is blocked before any fabrication files are written. The KiCad
  stages are mocked (this environment has no pcbnew/kicad-cli), so the only
  real gate in the flow is the SPICE check under test.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from etchant.circuits.generative_buck import GenerativeBuckConverter
from etchant.core.models import CircuitSpec, DesignResult
from etchant.kicad.pipeline import (
    ElectricalVerificationError,
    _verify_buck_electrical,
    generate_pcb_artifacts,
)
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


class TestBuckElectricalGate:
    """Unit tests for the gate helper in isolation."""

    @requires_ngspice
    def test_correct_buck_passes(self) -> None:
        # A correct adjustable buck must not trip the gate.
        _verify_buck_electrical(_generate_buck(12.0, 3.3, 1.0))

    @requires_ngspice
    def test_sabotaged_buck_raises_with_detail(self) -> None:
        bad = _mutate_r1(_generate_buck(12.0, 3.3, 1.0), "100k")
        with pytest.raises(ElectricalVerificationError) as exc:
            _verify_buck_electrical(bad)
        message = str(exc.value).lower()
        assert "electrical" in message
        assert "vout" in message  # surfaces simulated-vs-target detail

    def test_fixed_output_buck_is_not_blocked(
        self, fixed_output_buck: DesignResult
    ) -> None:
        # Buck topology but no feedback divider -> not applicable, no ngspice
        # run, no block.
        _verify_buck_electrical(fixed_output_buck)

    def test_non_buck_topology_is_skipped_entirely(self) -> None:
        # A design that HAS a divider but is not a buck must not be simulated
        # by the buck gate -- proven by making verify_buck explode if called.
        divider_design = _generate_buck(12.0, 3.3, 1.0)
        boost_like = dataclasses.replace(
            divider_design,
            spec=dataclasses.replace(
                divider_design.spec, topology="boost_converter"
            ),
        )
        with patch(
            "etchant.kicad.pipeline.verify_buck",
            side_effect=AssertionError("verify_buck must not run for non-buck"),
        ):
            _verify_buck_electrical(boost_like)  # must not raise

    def test_missing_ngspice_fails_safe(self) -> None:
        # No simulator -> the gate must surface an error, never silently pass.
        design = _generate_buck(12.0, 3.3, 1.0)
        with (
            patch(
                "etchant.sim.ngspice_runner.shutil.which", return_value=None
            ),
            pytest.raises(RuntimeError),
        ):
            _verify_buck_electrical(design)


@pytest.fixture
def kicad_stack(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> dict[str, Any]:
    """Mock the KiCad-dependent pipeline stages.

    Lets ``generate_pcb_artifacts`` run to completion without pcbnew/kicad-cli
    so the SPICE gate is the only real check in the flow. ``design`` selects
    what the (mocked) generator returns; ``fab_called`` records whether fab
    export was reached.
    """
    holder: dict[str, Any] = {"design": None, "fab_called": False}

    class _FakeGenerator:
        def generate(self, spec: CircuitSpec) -> DesignResult:
            return holder["design"]

    monkeypatch.setattr(
        "etchant.kicad.pipeline.get_generator",
        lambda topology: _FakeGenerator(),
    )
    monkeypatch.setattr(
        "etchant.kicad.netlist_builder.check_skidl_available", lambda: True
    )

    class _FakeNetlistBuilder:
        def __init__(self, output_dir: Path) -> None:
            self._output_dir = output_dir

        def build(self, design: DesignResult) -> Path:
            path = tmp_path / f"{design.spec.name}.net"
            path.write_text("* netlist")
            return path

    monkeypatch.setattr(
        "etchant.kicad.netlist_builder.NetlistBuilder", _FakeNetlistBuilder
    )

    def _fake_write_project_and_board(
        design: DesignResult,
        netlist: Path,
        output_dir: Path,
        *,
        route: bool,
    ) -> tuple[Path, bool]:
        project = output_dir / f"{design.spec.name}.kicad_pro"
        project.write_text("{}")
        project.with_suffix(".kicad_pcb").write_text("(kicad_pcb)")
        return project, False

    monkeypatch.setattr(
        "etchant.kicad.pipeline._write_project_and_board",
        _fake_write_project_and_board,
    )

    def _fake_export_fab(
        pcb_path: Path, output_dir: Path | None = None
    ) -> Path:
        holder["fab_called"] = True
        zip_path = (output_dir or pcb_path.parent) / f"{pcb_path.stem}_gerbers.zip"
        zip_path.write_text("PK")
        return zip_path

    monkeypatch.setattr(
        "etchant.kicad.fab_export.export_fabrication_files", _fake_export_fab
    )
    return holder


@requires_ngspice
class TestPipelineBlocksFabExport:
    def test_correct_buck_reaches_fab_export(
        self,
        kicad_stack: dict[str, Any],
        tmp_path: Path,
        constraints_dir: Path,
    ) -> None:
        kicad_stack["design"] = _generate_buck(12.0, 3.3, 1.0)
        result = generate_pcb_artifacts(
            kicad_stack["design"].spec,
            output_dir=tmp_path,
            constraints_dir=constraints_dir,
            route=False,
            render=False,
            run_drc=False,
            optimize_parts=False,
        )
        assert kicad_stack["fab_called"] is True
        assert result.fab_zip is not None
        assert result.fab_zip.exists()

    def test_sabotaged_buck_is_blocked_before_fab(
        self,
        kicad_stack: dict[str, Any],
        tmp_path: Path,
        constraints_dir: Path,
    ) -> None:
        good = _generate_buck(12.0, 3.3, 1.0)
        kicad_stack["design"] = _mutate_r1(good, "100k")

        with pytest.raises(ElectricalVerificationError) as exc:
            generate_pcb_artifacts(
                kicad_stack["design"].spec,
                output_dir=tmp_path,
                constraints_dir=constraints_dir,
                route=False,
                render=False,
                run_drc=False,
                optimize_parts=False,
            )

        assert "electrical" in str(exc.value).lower()
        # The fab stage was never reached and no fab zip exists on disk.
        assert kicad_stack["fab_called"] is False
        assert not list(tmp_path.glob("*_gerbers.zip"))
