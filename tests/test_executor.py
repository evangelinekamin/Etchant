"""Tests for the agent tool executor."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from etchant.agents.executor import ToolExecutor


@pytest.fixture
def executor(constraints_dir: Path, tmp_path: Path) -> ToolExecutor:
    return ToolExecutor(constraints_dir=constraints_dir, output_dir=tmp_path)


class TestListTopologies:
    def test_returns_topologies(self, executor: ToolExecutor) -> None:
        result = executor.execute("list_topologies", {})
        assert "topologies" in result
        assert "buck_converter" in result["topologies"]
        assert "ldo_regulator" in result["topologies"]


class TestGenerateCircuit:
    def test_buck_converter(self, executor: ToolExecutor) -> None:
        result = executor.execute("generate_circuit", {
            "topology": "buck_converter",
            "input_voltage": 12.0,
            "output_voltage": 5.0,
            "output_current": 2.0,
        })
        assert "error" not in result
        assert result["spec"]["topology"] == "buck_converter"
        # 6 active parts + J1 (VIN) + J2 (VOUT)
        assert len(result["components"]) == 8

    def test_ldo_regulator(self, executor: ToolExecutor) -> None:
        result = executor.execute("generate_circuit", {
            "topology": "ldo_regulator",
            "input_voltage": 5.0,
            "output_voltage": 3.3,
            "output_current": 0.5,
        })
        assert "error" not in result
        # 3 active parts (U1, C1, C2) + J1 (VIN) + J2 (VOUT)
        assert len(result["components"]) == 5

    def test_invalid_topology(self, executor: ToolExecutor) -> None:
        result = executor.execute("generate_circuit", {
            "topology": "flyback_converter",
            "input_voltage": 5.0,
            "output_voltage": 12.0,
            "output_current": 1.0,
        })
        assert "error" in result

    def test_boost_converter(self, executor: ToolExecutor) -> None:
        result = executor.execute("generate_circuit", {
            "topology": "boost_converter",
            "input_voltage": 3.7,
            "output_voltage": 5.0,
            "output_current": 1.0,
        })
        assert "error" not in result
        # 7 active parts (U1, L1, C1, C2, D1, R1, R2) + J1 (VIN) + J2 (VOUT)
        assert len(result["components"]) == 9

    def test_invalid_spec(self, executor: ToolExecutor) -> None:
        result = executor.execute("generate_circuit", {
            "topology": "buck_converter",
            "input_voltage": 3.0,
            "output_voltage": 5.0,
            "output_current": 2.0,
        })
        assert "error" in result


class TestValidateDesign:
    def test_valid_design(self, executor: ToolExecutor) -> None:
        result = executor.execute("validate_design", {
            "topology": "ldo_regulator",
            "input_voltage": 5.0,
            "output_voltage": 3.3,
            "output_current": 0.5,
        })
        assert "error" not in result
        assert "errors" in result
        assert "warnings" in result
        assert len(result["errors"]) == 0


class TestValidateJLCPCBAssembly:
    def test_ldo_reports_basic_parts_and_manual_headers(
        self,
        executor: ToolExecutor,
    ) -> None:
        result = executor.execute("validate_jlcpcb_assembly", {
            "topology": "ldo_regulator",
            "input_voltage": 5.0,
            "output_voltage": 3.3,
            "output_current": 0.5,
            "prefer_basic": True,
        })

        assert "error" not in result
        assert result["assembly_ready"] is True
        assert result["summary"]["basic_components"] >= 3
        assert result["summary"]["error_count"] == 0
        rules = {
            issue["rule"]
            for component in result["components"]
            for issue in component["issues"]
        }
        assert "through_hole_manual_assembly" in rules


class TestOptimizeJLCPCBAssembly:
    def test_buck_applies_part_substitutions(
        self,
        executor: ToolExecutor,
    ) -> None:
        result = executor.execute("optimize_jlcpcb_assembly", {
            "topology": "buck_converter",
            "input_voltage": 12.0,
            "output_voltage": 5.0,
            "output_current": 2.0,
            "prefer_basic": True,
        })

        assert "error" not in result
        assert result["substitution_count"] >= 1
        substitutions = {
            sub["reference"]: sub for sub in result["substitutions"]
        }
        assert substitutions["R1"]["new"]["classification"] == "basic"
        assert substitutions["R1"]["new"]["lcsc_part"] == "C17737"


class TestEstimateCost:
    def test_buck_cost(self, executor: ToolExecutor) -> None:
        result = executor.execute("estimate_cost", {
            "topology": "buck_converter",
            "input_voltage": 12.0,
            "output_voltage": 5.0,
            "output_current": 2.0,
        })
        assert "error" not in result
        # 6 active parts + 2 connectors
        assert result["bom"]["total_parts"] == 8
        assert result["bom"]["assembly_setup_fee_usd"] > 0

    def test_ldo_cost_is_cheaper(self, executor: ToolExecutor) -> None:
        ldo = executor.execute("estimate_cost", {
            "topology": "ldo_regulator",
            "input_voltage": 5.0,
            "output_voltage": 3.3,
            "output_current": 0.5,
        })
        buck = executor.execute("estimate_cost", {
            "topology": "buck_converter",
            "input_voltage": 12.0,
            "output_voltage": 5.0,
            "output_current": 2.0,
        })
        assert ldo["bom"]["assembly_setup_fee_usd"] < buck["bom"]["assembly_setup_fee_usd"]


class TestLookupPart:
    def test_known_part(self, executor: ToolExecutor) -> None:
        result = executor.execute("lookup_jlcpcb_part", {"value": "10k"})
        assert result["found"] is True
        assert result["classification"] == "basic"

    def test_unknown_part(self, executor: ToolExecutor) -> None:
        result = executor.execute("lookup_jlcpcb_part", {"value": "NONEXISTENT"})
        assert result["found"] is False


class TestSuggestTopology:
    def test_low_noise_suggests_ldo(self, executor: ToolExecutor) -> None:
        result = executor.execute("suggest_topology", {
            "description": "I need a low noise 3.3V supply for my ADC",
        })
        assert result["suggested_topology"] == "ldo_regulator"

    def test_efficient_suggests_buck(self, executor: ToolExecutor) -> None:
        result = executor.execute("suggest_topology", {
            "description": "efficient 5V to 3.3V at high current",
        })
        assert result["suggested_topology"] == "buck_converter"

    def test_numerical_params_uses_advisor(self, executor: ToolExecutor) -> None:
        result = executor.execute("suggest_topology", {
            "input_voltage": 12.0,
            "output_voltage": 5.0,
            "output_current": 2.0,
        })
        assert result["suggested_topology"] == "buck_converter"
        assert "confidence" in result
        assert "tradeoffs" in result

    def test_numerical_with_priority(self, executor: ToolExecutor) -> None:
        result = executor.execute("suggest_topology", {
            "input_voltage": 5.0,
            "output_voltage": 3.3,
            "output_current": 0.5,
            "priority": "noise",
        })
        assert result["suggested_topology"] == "ldo_regulator"


class TestExportDesign:
    def test_export_json(self, executor: ToolExecutor, tmp_path: Path) -> None:
        result = executor.execute("export_design", {
            "topology": "ldo_regulator",
            "input_voltage": 5.0,
            "output_voltage": 3.3,
            "output_current": 0.5,
            "format": "json",
            "output_dir": str(tmp_path),
        })
        assert "error" not in result
        assert len(result["exported"]) == 1
        assert result["exported"][0]["format"] == "json"

    def test_export_both(self, executor: ToolExecutor, tmp_path: Path) -> None:
        result = executor.execute("export_design", {
            "topology": "ldo_regulator",
            "input_voltage": 5.0,
            "output_voltage": 3.3,
            "output_current": 0.5,
            "format": "both",
            "output_dir": str(tmp_path),
        })
        assert len(result["exported"]) == 2


class TestGeneratePCBProject:
    def test_invokes_full_pipeline(
        self,
        executor: ToolExecutor,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: dict[str, Any] = {}

        class FakePipelineResult:
            def as_dict(self) -> dict[str, Any]:
                return {
                    "spec": {"topology": "ldo_regulator"},
                    "paths": {"pcb": str(tmp_path / "demo.kicad_pcb")},
                    "drc": {"errors": 0, "warnings": 0, "unconnected_pads": 0},
                    "routed": False,
                }

        def fake_generate_pcb_artifacts(*args: Any, **kwargs: Any) -> FakePipelineResult:
            calls["spec"] = args[0]
            calls.update(kwargs)
            return FakePipelineResult()

        monkeypatch.setattr(
            "etchant.kicad.pipeline.generate_pcb_artifacts",
            fake_generate_pcb_artifacts,
        )

        result = executor.execute("generate_pcb_project", {
            "topology": "ldo_regulator",
            "input_voltage": 5.0,
            "output_voltage": 3.3,
            "output_current": 0.5,
            "name": "demo_ldo",
            "output_dir": str(tmp_path),
            "route": False,
            "render": False,
            "prefer_basic": True,
        })

        assert "error" not in result
        assert result["drc"]["errors"] == 0
        assert calls["spec"].name == "demo_ldo"
        assert calls["spec"].topology == "ldo_regulator"
        assert calls["output_dir"] == tmp_path.resolve()
        assert calls["route"] is False
        assert calls["render"] is False
        assert calls["export_fab"] is True
        assert calls["run_drc"] is True
        assert calls["prefer_basic"] is True
        assert calls["optimize_parts"] is True

    def test_reports_missing_kicad_environment(
        self,
        executor: ToolExecutor,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def fake_generate_pcb_artifacts(*_args: Any, **_kwargs: Any) -> object:
            raise RuntimeError("pcbnew is unavailable")

        monkeypatch.setattr(
            "etchant.kicad.pipeline.generate_pcb_artifacts",
            fake_generate_pcb_artifacts,
        )

        result = executor.execute("generate_pcb_project", {
            "topology": "ldo_regulator",
            "input_voltage": 5.0,
            "output_voltage": 3.3,
            "output_current": 0.5,
            "output_dir": str(tmp_path),
        })

        assert "error" in result
        assert "pcbnew is unavailable" in result["error"]


class TestPathTraversal:
    def test_export_rejects_path_outside_output(
        self, constraints_dir: Path, tmp_path: Path
    ) -> None:
        executor = ToolExecutor(constraints_dir=constraints_dir, output_dir=tmp_path)
        result = executor.execute("export_design", {
            "topology": "ldo_regulator",
            "input_voltage": 5.0,
            "output_voltage": 3.3,
            "output_current": 0.5,
            "format": "json",
            "output_dir": "/etc/evil",
        })
        assert "error" in result

    def test_generate_pcb_rejects_path_outside_output(
        self, constraints_dir: Path, tmp_path: Path
    ) -> None:
        executor = ToolExecutor(constraints_dir=constraints_dir, output_dir=tmp_path)
        result = executor.execute("generate_pcb_project", {
            "topology": "ldo_regulator",
            "input_voltage": 5.0,
            "output_voltage": 3.3,
            "output_current": 0.5,
            "output_dir": "/etc/evil",
        })
        assert "error" in result
        assert "output_dir" in result["error"]

    def test_export_rejects_relative_traversal(
        self, constraints_dir: Path, tmp_path: Path
    ) -> None:
        executor = ToolExecutor(constraints_dir=constraints_dir, output_dir=tmp_path)
        result = executor.execute("export_design", {
            "topology": "ldo_regulator",
            "input_voltage": 5.0,
            "output_voltage": 3.3,
            "output_current": 0.5,
            "format": "json",
            "output_dir": str(tmp_path / ".." / ".." / "etc"),
        })
        assert "error" in result


class TestInputValidation:
    def test_missing_params_returns_error(self, executor: ToolExecutor) -> None:
        result = executor.execute("generate_circuit", {
            "topology": "buck_converter",
        })
        assert "error" in result

    def test_negative_voltage_returns_error(self, executor: ToolExecutor) -> None:
        result = executor.execute("generate_circuit", {
            "topology": "buck_converter",
            "input_voltage": -12.0,
            "output_voltage": 5.0,
            "output_current": 2.0,
        })
        assert "error" in result

    def test_error_does_not_leak_internal_paths(self, executor: ToolExecutor) -> None:
        result = executor.execute("generate_circuit", {
            "topology": "nonexistent",
            "input_voltage": 12.0,
            "output_voltage": 5.0,
            "output_current": 2.0,
        })
        assert "error" in result
        assert "/home/" not in result["error"]


class TestUnknownTool:
    def test_returns_error(self, executor: ToolExecutor) -> None:
        result = executor.execute("nonexistent_tool", {})
        assert "error" in result
        assert "Unknown tool" in result["error"]
