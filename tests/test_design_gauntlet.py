"""Tests for the repeatable PCB idea gauntlet runner."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.run_design_gauntlet import DEFAULT_CASES, load_cases, main


def test_load_default_cases() -> None:
    cases = load_cases(DEFAULT_CASES)
    ids = {case.id for case in cases}

    assert "buck_12v_to_5v_2a" in ids
    assert "usb_c_5v_3a_power_input" in ids
    assert "usb_m2_2230_nvme_bridge" in ids
    assert "dual_nvme_raid1_usb_enclosure" in ids
    assert all(case.prompt for case in cases)

    usb_c_case = next(case for case in cases if case.id == "usb_c_5v_3a_power_input")
    assert usb_c_case.topology == "usb_c_sink_protection"
    assert usb_c_case.advisor_expected == "usb_c_sink_protection"


def test_run_single_supported_case(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.yaml"
    cases_path.write_text(
        """
version: 1
cases:
  - id: ldo_smoke
    title: LDO smoke test
    prompt: Make a 5V to 3.3V LDO board.
    expected_maturity: fabrication_candidate
    topology: ldo_regulator
    advisor_expected: ldo_regulator
    spec:
      input_voltage: 5.0
      output_voltage: 3.3
      output_current: 0.5
""",
        encoding="utf-8",
    )

    rc = main(["--cases", str(cases_path), "--output-dir", str(tmp_path / "out")])

    assert rc == 0
    report = json.loads((tmp_path / "out" / "report.json").read_text())
    result = report["results"][0]
    assert result["id"] == "ldo_smoke"
    assert result["status"] in {"generated", "needs_review"}
    assert (tmp_path / "out" / "ldo_smoke" / "preview.svg").exists()
    assert (tmp_path / "out" / "ldo_smoke" / "exports").exists()
    assert result["steps"]["generate_circuit"]["components"]


def test_run_blocked_case_records_capability_gap(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.yaml"
    cases_path.write_text(
        """
version: 1
cases:
  - id: missing_topology
    title: Missing topology smoke test
    prompt: Make a battery charger.
    expected_maturity: research_required
    topology:
    spec:
      input_voltage: 5.0
      output_voltage: 4.2
      output_current: 1.0
""",
        encoding="utf-8",
    )

    rc = main(["--cases", str(cases_path), "--output-dir", str(tmp_path / "out")])

    assert rc == 0
    report = json.loads((tmp_path / "out" / "report.json").read_text())
    result = report["results"][0]
    assert result["status"] == "blocked"
    assert result["findings"][0]["kind"] == "capability_gap"
    assert (tmp_path / "out" / "missing_topology" / "result.json").exists()
