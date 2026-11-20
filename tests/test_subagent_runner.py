"""Tests for the subagent tool runner CLI.

Covers the JSON-in/JSON-out contract that a Claude Code subagent
(or any shell-driven reasoning layer) relies on. Doesn't exercise the
LLM side of things — just verifies the tool plumbing is clean.
"""

from __future__ import annotations

import json

import pytest

from etchant.agents.subagent_runner import main


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict]:
    rc = main(list(argv))
    out = capsys.readouterr()
    data = json.loads(out.out) if out.out.strip() else {}
    return rc, data


class TestListTools:
    def test_lists_all_tools(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc, data = _run(capsys, "--list-tools")
        assert rc == 0
        names = {t["name"] for t in data["tools"]}
        assert {"generate_circuit", "validate_design", "estimate_cost",
                "list_topologies", "suggest_topology"} <= names

    def test_tool_schema_shape(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc, data = _run(capsys, "--list-tools")
        assert rc == 0
        for tool in data["tools"]:
            assert "name" in tool
            assert "description" in tool
            assert "parameters" in tool
            assert "required" in tool
            assert isinstance(tool["required"], list)


class TestToolInvocation:
    def test_list_topologies(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc, data = _run(capsys, "list_topologies", "{}")
        assert rc == 0
        assert "topologies" in data
        assert "op_amp_buffer" in data["topologies"]

    def test_suggest_topology_picks_ldo(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc, data = _run(
            capsys, "suggest_topology",
            '{"input_voltage": 5, "output_voltage": 3.3, "output_current": 0.5}',
        )
        assert rc == 0
        assert data["suggested_topology"] == "ldo_regulator"

    def test_suggest_topology_picks_buck_for_high_current(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc, data = _run(
            capsys, "suggest_topology",
            '{"input_voltage": 12, "output_voltage": 5, "output_current": 2}',
        )
        assert rc == 0
        assert data["suggested_topology"] == "buck_converter"

    def test_generate_circuit_ldo(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc, data = _run(
            capsys, "generate_circuit",
            '{"topology": "ldo_regulator", "input_voltage": 5, '
            '"output_voltage": 3.3, "output_current": 0.5}',
        )
        assert rc == 0
        assert data["spec"]["topology"] == "ldo_regulator"
        assert len(data["components"]) >= 3


class TestErrorHandling:
    def test_unknown_tool_returns_rc2(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc, data = _run(capsys, "nonexistent_tool", "{}")
        assert rc == 2
        assert "error" in data

    def test_malformed_json_returns_rc1(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = main(["generate_circuit", "not a json object"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "bad JSON" in err or "JSON" in err.lower()

    def test_json_must_be_object_not_array(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = main(["generate_circuit", "[1, 2, 3]"])
        assert rc == 1

    def test_invalid_spec_returns_rc2(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Vout > Vin for a buck — generator should reject this
        rc, data = _run(
            capsys, "generate_circuit",
            '{"topology": "buck_converter", "input_voltage": 5, '
            '"output_voltage": 12, "output_current": 1}',
        )
        assert rc == 2
        assert "error" in data


class TestNoArgsPrintsHelp:
    def test_no_tool_name_returns_rc1(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = main([])
        assert rc == 1
