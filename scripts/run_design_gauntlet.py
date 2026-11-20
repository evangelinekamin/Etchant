"""Run repeatable PCB idea prompts through Etchant's current tool pipeline.

The gauntlet is intentionally pragmatic: it records what Etchant can generate
today and what still needs topology, research, or KiCad/backend work. By
default it avoids KiCad-heavy PCB artifact generation so it can run in a normal
``uv`` environment. Use ``--full-pcb`` inside the KiCad distrobox when you want
netlists, boards, renders, Gerbers, and DRC.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from etchant.agents.executor import ToolExecutor  # noqa: E402

DEFAULT_CASES = REPO_ROOT / "evals" / "pcb_ideas.yaml"
DEFAULT_OUTPUT = REPO_ROOT / "output" / "gauntlet"

_REQUIRED_SPEC_FIELDS = ("input_voltage", "output_voltage", "output_current")
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@dataclass(frozen=True)
class GauntletCase:
    """One PCB idea prompt and the current structured interpretation."""

    id: str
    title: str
    prompt: str
    expected_maturity: str
    topology: str | None
    spec: dict[str, float]
    priority: str | None = None
    advisor_expected: str | None = None
    tags: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    run_full_pcb: bool = True

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> GauntletCase:
        case_id = str(raw.get("id", "")).strip()
        if not _SAFE_ID.match(case_id):
            raise ValueError(f"Invalid case id: {case_id!r}")

        spec = raw.get("spec") or {}
        if not isinstance(spec, dict):
            raise ValueError(f"Case {case_id}: spec must be a mapping")

        numeric_spec: dict[str, float] = {}
        for key in _REQUIRED_SPEC_FIELDS:
            if key in spec and spec[key] is not None:
                numeric_spec[key] = float(spec[key])

        topology = raw.get("topology")
        if topology is not None:
            topology = str(topology).strip() or None

        return cls(
            id=case_id,
            title=str(raw.get("title", case_id)).strip(),
            prompt=str(raw.get("prompt", "")).strip(),
            expected_maturity=str(raw.get("expected_maturity", "unknown")).strip(),
            topology=topology,
            spec=numeric_spec,
            priority=str(raw["priority"]).strip() if raw.get("priority") else None,
            advisor_expected=(
                str(raw["advisor_expected"]).strip()
                if raw.get("advisor_expected") else None
            ),
            tags=tuple(str(t) for t in raw.get("tags", ())),
            notes=tuple(str(n) for n in raw.get("notes", ())),
            run_full_pcb=bool(raw.get("run_full_pcb", True)),
        )

    @property
    def can_generate(self) -> bool:
        """Whether this case has enough structured data for current generators."""
        return self.topology is not None and all(k in self.spec for k in _REQUIRED_SPEC_FIELDS)

    def tool_args(self) -> dict[str, Any]:
        """Return arguments accepted by Etchant's agent-layer tools."""
        if not self.can_generate:
            raise ValueError(f"Case {self.id} is missing topology or spec")
        return {
            "topology": self.topology,
            "input_voltage": self.spec["input_voltage"],
            "output_voltage": self.spec["output_voltage"],
            "output_current": self.spec["output_current"],
        }

    def advisor_args(self) -> dict[str, Any] | None:
        """Return topology-advisor args when the case has numerical requirements."""
        if not all(k in self.spec for k in _REQUIRED_SPEC_FIELDS):
            return None
        args: dict[str, Any] = dict(self.spec)
        if self.priority:
            args["priority"] = self.priority
        return args


def load_cases(path: Path) -> list[GauntletCase]:
    """Load gauntlet cases from YAML."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise ValueError(f"{path} must contain a top-level 'cases' list")

    return [GauntletCase.from_mapping(raw) for raw in data["cases"]]


def run_case(
    case: GauntletCase,
    *,
    executor: ToolExecutor,
    output_root: Path,
    full_pcb: bool,
    route: bool,
    render: bool,
    run_drc: bool,
    export_fab: bool,
    prefer_basic: bool,
) -> dict[str, Any]:
    """Run one case and return a JSON-serializable result record."""
    case_dir = output_root / case.id
    case_dir.mkdir(parents=True, exist_ok=True)

    record: dict[str, Any] = {
        "id": case.id,
        "title": case.title,
        "prompt": case.prompt,
        "expected_maturity": case.expected_maturity,
        "topology": case.topology,
        "spec": case.spec,
        "tags": list(case.tags),
        "notes": list(case.notes),
        "status": "pending",
        "findings": [],
        "steps": {},
        "paths": {},
    }

    (case_dir / "prompt.txt").write_text(case.prompt + "\n", encoding="utf-8")

    advisor_args = case.advisor_args()
    if advisor_args is not None:
        suggestion = executor.execute("suggest_topology", advisor_args)
        record["steps"]["suggest_topology"] = suggestion
        suggested = suggestion.get("suggested_topology")
        if case.advisor_expected and suggested != case.advisor_expected:
            _add_finding(
                record,
                "topology_advisor_mismatch",
                f"advisor suggested {suggested!r}, expected {case.advisor_expected!r}",
            )

    if not case.can_generate:
        blockers = []
        if case.topology is None:
            blockers.append("missing supported topology")
        missing_spec = [k for k in _REQUIRED_SPEC_FIELDS if k not in case.spec]
        if missing_spec:
            blockers.append(f"missing spec fields: {', '.join(missing_spec)}")
        record["status"] = "blocked"
        record["verdict"] = "blocked: " + "; ".join(blockers)
        _add_finding(record, "capability_gap", record["verdict"])
        _write_case_record(case_dir, record)
        return record

    args = case.tool_args()
    generated = executor.execute("generate_circuit", args)
    record["steps"]["generate_circuit"] = generated
    if "error" in generated:
        record["status"] = "failed"
        record["verdict"] = generated["error"]
        _add_finding(record, "generation_error", str(generated["error"]))
        _write_case_record(case_dir, record)
        return record

    preview = case_dir / "preview.svg"
    write_svg_preview(preview, case, generated)
    record["paths"]["preview_svg"] = str(preview)

    validation = executor.execute("validate_design", args)
    cost = executor.execute("estimate_cost", args)
    optimization = executor.execute(
        "optimize_jlcpcb_assembly",
        {**args, "prefer_basic": prefer_basic},
    )
    assembly = executor.execute(
        "validate_jlcpcb_assembly",
        {**args, "prefer_basic": prefer_basic},
    )
    export = executor.execute(
        "export_design",
        {
            **args,
            "format": "both",
            "output_dir": str(case_dir / "exports"),
        },
    )

    record["steps"].update({
        "validate_design": validation,
        "estimate_cost": cost,
        "optimize_jlcpcb_assembly": optimization,
        "validate_jlcpcb_assembly": assembly,
        "export_design": export,
    })
    _collect_export_paths(record, export)
    _collect_common_findings(record, validation, assembly, optimization)

    if full_pcb and case.run_full_pcb:
        pcb = executor.execute(
            "generate_pcb_project",
            {
                **args,
                "name": case.id,
                "output_dir": str(case_dir / "pcb"),
                "route": route,
                "render": render,
                "run_drc": run_drc,
                "export_fab": export_fab,
                "prefer_basic": prefer_basic,
                "optimize_parts": True,
            },
        )
        record["steps"]["generate_pcb_project"] = pcb
        if "error" in pcb:
            _add_finding(record, "pcb_artifact_error", str(pcb["error"]))
        else:
            for key, value in (pcb.get("paths") or {}).items():
                if value:
                    record["paths"][f"pcb_{key}"] = value

    record["status"] = _status_for(record)
    record["verdict"] = _verdict_for(record)
    _write_case_record(case_dir, record)
    return record


def write_svg_preview(path: Path, case: GauntletCase, generated: dict[str, Any]) -> None:
    """Write a lightweight block-diagram SVG from generated components/nets."""
    components = list(generated.get("components") or [])
    nets = list(generated.get("nets") or [])

    box_w = 245
    box_h = 58
    gap_x = 28
    gap_y = 18
    cols = 3
    rows = max(1, (len(components) + cols - 1) // cols)
    net_rows = min(10, len(nets))
    width = cols * box_w + (cols + 1) * gap_x
    height = 190 + rows * (box_h + gap_y) + max(0, net_rows) * 22

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}">'
        ),
        "<style>",
        "text{font-family:Arial,sans-serif;fill:#17202a}",
        ".title{font-size:24px;font-weight:700}",
        ".small{font-size:12px;fill:#566573}",
        ".box{fill:#f8fbff;stroke:#2e86ab;stroke-width:2;rx:10}",
        ".net{font-size:13px;fill:#1f618d}",
        "</style>",
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#f4f1e8"/>',
        f'<text class="title" x="28" y="42">{_xml(case.title)}</text>',
        (
            f'<text class="small" x="28" y="66">{_xml(case.id)} | '
            f'{_xml(str(case.topology or "no topology"))} | '
            f'{_xml(case.expected_maturity)}</text>'
        ),
        f'<text class="small" x="28" y="90">{_xml(_shorten(case.prompt, 140))}</text>',
    ]

    start_y = 126
    for i, component in enumerate(components):
        col = i % cols
        row = i // cols
        x = gap_x + col * (box_w + gap_x)
        y = start_y + row * (box_h + gap_y)
        ref = str(component.get("reference", "?"))
        value = str(component.get("value", ""))
        category = str(component.get("category", ""))
        footprint = str(component.get("footprint", ""))
        value_line = f"{_xml(ref)} - {_xml(value)}"
        lines.extend([
            f'<rect class="box" x="{x}" y="{y}" width="{box_w}" height="{box_h}"/>',
            (
                f'<text x="{x + 14}" y="{y + 22}" font-size="16" '
                f'font-weight="700">{value_line}</text>'
            ),
            f'<text class="small" x="{x + 14}" y="{y + 40}">{_xml(category)}</text>',
            f'<text class="small" x="{x + 14}" y="{y + 54}">{_xml(_shorten(footprint, 34))}</text>',
        ])

    nets_y = start_y + rows * (box_h + gap_y) + 28
    lines.append(f'<text x="28" y="{nets_y}" font-size="18" font-weight="700">Nets</text>')
    for i, net in enumerate(nets[:10]):
        y = nets_y + 24 + i * 22
        name = str(net.get("name", "?"))
        count = str(net.get("connection_count", "?"))
        lines.append(
            f'<text class="net" x="28" y="{y}">{_xml(name)} ({_xml(count)} connections)</text>'
        )
    if len(nets) > 10:
        lines.append(
            f'<text class="small" x="28" y="{nets_y + 24 + 10 * 22}">'
            f'+ {len(nets) - 10} more nets</text>'
        )

    lines.append("</svg>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_reports(output_root: Path, results: list[dict[str, Any]]) -> tuple[Path, Path]:
    """Write aggregate JSON and Markdown reports."""
    output_root.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "case_count": len(results),
        "summary": _summary_counts(results),
        "results": results,
    }

    json_path = output_root / "report.json"
    md_path = output_root / "report.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_markdown_report(report), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--case", action="append", dest="case_ids", help="Run one case id")
    parser.add_argument("--limit", type=int, help="Run only the first N selected cases")
    parser.add_argument("--full-pcb", action="store_true", help="Run KiCad artifact generation")
    parser.add_argument(
        "--route",
        action="store_true",
        help="Run Freerouting when --full-pcb is set",
    )
    parser.add_argument("--no-render", action="store_true", help="Skip KiCad render exports")
    parser.add_argument("--no-drc", action="store_true", help="Skip KiCad DRC")
    parser.add_argument("--no-fab", action="store_true", help="Skip Gerber/fab export")
    parser.add_argument(
        "--no-prefer-basic",
        action="store_true",
        help="Do not warn on JLCPCB Extended Parts",
    )
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Exit non-zero if any selected case fails unexpectedly",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show debug logs from tool execution",
    )
    args = parser.parse_args(argv)

    if not args.verbose:
        logging.getLogger("etchant.agents.executor").setLevel(logging.CRITICAL)

    cases = load_cases(args.cases)
    if args.case_ids:
        wanted = set(args.case_ids)
        cases = [case for case in cases if case.id in wanted]
        missing = wanted - {case.id for case in cases}
        if missing:
            raise SystemExit(f"Unknown case id(s): {', '.join(sorted(missing))}")
    if args.limit is not None:
        cases = cases[: args.limit]

    output_root = args.output_dir.resolve()
    executor = ToolExecutor(output_dir=output_root)

    results = [
        run_case(
            case,
            executor=executor,
            output_root=output_root,
            full_pcb=args.full_pcb,
            route=args.route,
            render=not args.no_render,
            run_drc=not args.no_drc,
            export_fab=not args.no_fab,
            prefer_basic=not args.no_prefer_basic,
        )
        for case in cases
    ]
    json_path, md_path = write_reports(output_root, results)

    summary = _summary_counts(results)
    print(
        "Gauntlet complete: "
        + ", ".join(f"{key}={value}" for key, value in sorted(summary.items()))
    )
    print(f"JSON: {json_path}")
    print(f"Markdown: {md_path}")

    if args.fail_on_error and any(r["status"] == "failed" for r in results):
        return 1
    return 0


def _collect_export_paths(record: dict[str, Any], export: dict[str, Any]) -> None:
    for item in export.get("exported", []):
        fmt = item.get("format")
        path = item.get("path")
        if fmt and path:
            record["paths"][f"export_{fmt}"] = path


def _collect_common_findings(
    record: dict[str, Any],
    validation: dict[str, Any],
    assembly: dict[str, Any],
    optimization: dict[str, Any],
) -> None:
    if "error" in validation:
        _add_finding(record, "validation_error", str(validation["error"]))
    for issue in validation.get("errors", []):
        _add_finding(record, "constraint_error", str(issue.get("message", issue)))
    for issue in validation.get("warnings", []):
        _add_finding(record, "constraint_warning", str(issue.get("message", issue)))

    if "error" in assembly:
        _add_finding(record, "assembly_validation_error", str(assembly["error"]))
    elif _effective_assembly(assembly, optimization).get("assembly_ready") is not True:
        _add_finding(record, "assembly_not_ready", "JLCPCB assembly report is not ready")

    substitutions = optimization.get("substitutions", [])
    if substitutions:
        _add_finding(
            record,
            "part_substitutions",
            f"{len(substitutions)} automatic JLCPCB substitution(s)",
        )
    if "error" in optimization:
        _add_finding(record, "part_optimization_error", str(optimization["error"]))


def _status_for(record: dict[str, Any]) -> str:
    if any(step.get("error") for step in record["steps"].values() if isinstance(step, dict)):
        # If generation succeeded but later optional steps failed, this is still useful output.
        generated = record["steps"].get("generate_circuit", {})
        if isinstance(generated, dict) and "error" not in generated:
            return "needs_review"
        return "failed"

    validation = record["steps"].get("validate_design", {})
    assembly = record["steps"].get("validate_jlcpcb_assembly", {})
    optimization = record["steps"].get("optimize_jlcpcb_assembly", {})
    effective_assembly = _effective_assembly(assembly, optimization)
    if validation.get("errors") or effective_assembly.get("assembly_ready") is not True:
        return "needs_review"
    if record["expected_maturity"] in {"architecture_only", "research_required"}:
        return "needs_review"
    return "generated"


def _verdict_for(record: dict[str, Any]) -> str:
    status = record["status"]
    if status == "generated":
        return "generated draft with no blocking tool-level issues"
    if status == "needs_review":
        if record["expected_maturity"] == "architecture_only":
            return "architecture-level draft only; requires expert layout/reference design"
        if record["expected_maturity"] == "research_required":
            return "partial draft; requires research or a new topology before fabrication"
        return "generated draft with findings that need review"
    if status == "failed":
        return "failed before producing a usable design draft"
    return str(record.get("verdict", status))


def _effective_assembly(
    assembly: dict[str, Any],
    optimization: dict[str, Any],
) -> dict[str, Any]:
    optimized = optimization.get("after")
    if isinstance(optimized, dict) and optimized.get("assembly_ready") is True:
        return optimized
    return assembly


def _add_finding(record: dict[str, Any], kind: str, message: str) -> None:
    record["findings"].append({"kind": kind, "message": message})


def _write_case_record(case_dir: Path, record: dict[str, Any]) -> None:
    (case_dir / "result.json").write_text(json.dumps(record, indent=2), encoding="utf-8")


def _summary_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for result in results:
        status = str(result["status"])
        summary[status] = summary.get(status, 0) + 1
    return summary


def _markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Etchant PCB Design Gauntlet",
        "",
        f"Generated: {report['generated_at']}",
        f"Cases: {report['case_count']}",
        "",
        "## Summary",
        "",
    ]
    for key, value in sorted(report["summary"].items()):
        lines.append(f"- {key}: {value}")

    lines.extend([
        "",
        "## Cases",
        "",
        "| Case | Status | Maturity | Topology | Components | Assembly | Findings |",
        "| --- | --- | --- | --- | ---: | --- | --- |",
    ])
    for result in report["results"]:
        generated = result["steps"].get("generate_circuit", {})
        assembly = result["steps"].get("validate_jlcpcb_assembly", {})
        optimization = result["steps"].get("optimize_jlcpcb_assembly", {})
        effective_assembly = _effective_assembly(assembly, optimization)
        component_count = len(generated.get("components", []))
        assembly_status = (
            "ready" if effective_assembly.get("assembly_ready") is True
            else "not ready" if assembly else "n/a"
        )
        findings = "; ".join(
            f"{f['kind']}: {f['message']}" for f in result.get("findings", [])[:3]
        )
        if len(result.get("findings", [])) > 3:
            findings += f"; +{len(result['findings']) - 3} more"
        lines.append(
            "| "
            + " | ".join([
                _md(str(result["id"])),
                _md(str(result["status"])),
                _md(str(result["expected_maturity"])),
                _md(str(result.get("topology") or "none")),
                str(component_count),
                _md(assembly_status),
                _md(findings or "none"),
            ])
            + " |"
        )

    lines.extend(["", "## Per-Case Artifacts", ""])
    for result in report["results"]:
        lines.append(f"### {result['id']}")
        lines.append("")
        lines.append(result.get("verdict", ""))
        lines.append("")
        for name, path in sorted((result.get("paths") or {}).items()):
            rel = _relative(path)
            lines.append(f"- {name}: `{rel}`")
        if result.get("findings"):
            lines.append("")
            lines.append("Findings:")
            for finding in result["findings"]:
                lines.append(f"- {finding['kind']}: {finding['message']}")
        lines.append("")

    return "\n".join(lines)


def _relative(path: str) -> str:
    try:
        return str(Path(path).resolve().relative_to(REPO_ROOT))
    except ValueError:
        return path


def _shorten(value: str, limit: int) -> str:
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."


def _xml(value: str) -> str:
    return html.escape(value, quote=True)


def _md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
