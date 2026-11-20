"""End-to-end KiCad artifact generation for Etchant designs.

This module is the reusable version of ``scripts/full_pipeline.py``. It turns a
``CircuitSpec`` into the files users actually care about: design JSON, BOM CSV,
netlist, KiCad project, placed/routed PCB, renders, fab zip, and optional DRC
summary.

KiCad-specific imports are intentionally lazy so normal CLI commands and tests
do not emit SKiDL/pcbnew warnings just by importing Etchant.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from etchant.circuits import get_generator
from etchant.core.assembly_validator import validate_jlcpcb_assembly
from etchant.core.bom import BOMGenerator, CostBreakdown
from etchant.core.component_selector import connect_default_parts_db
from etchant.core.constraint_engine import ConstraintEngine, Severity
from etchant.core.models import CircuitSpec, DesignResult
from etchant.core.part_optimizer import optimize_jlcpcb_assembly
from etchant.core.serialization import save_design
from etchant.kicad.design_export import DesignExporter

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONSTRAINTS_DIR = REPO_ROOT / "constraints"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "demo"


@dataclass(frozen=True)
class PCBArtifactResult:
    """Generated file paths and verification summary for a PCB pipeline run."""

    spec: CircuitSpec
    component_count: int
    net_count: int
    validation_errors: int
    setup_fee_usd: float
    design_json: Path
    bom_csv: Path
    netlist: Path | None
    project: Path | None
    pcb: Path | None
    svg: Path | None
    top_png: Path | None
    render_3d_png: Path | None
    fab_zip: Path | None
    drc_report: Path | None
    drc: dict[str, int] | None
    assembly: dict[str, object]
    part_optimization: dict[str, object] | None
    routed: bool
    notes: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable view suitable for agent tools."""
        return {
            "spec": {
                "name": self.spec.name,
                "topology": self.spec.topology,
                "input_voltage": self.spec.input_voltage,
                "output_voltage": self.spec.output_voltage,
                "output_current": self.spec.output_current,
            },
            "component_count": self.component_count,
            "net_count": self.net_count,
            "validation_errors": self.validation_errors,
            "setup_fee_usd": self.setup_fee_usd,
            "paths": {
                "design_json": _path_str(self.design_json),
                "bom_csv": _path_str(self.bom_csv),
                "netlist": _path_str(self.netlist),
                "project": _path_str(self.project),
                "pcb": _path_str(self.pcb),
                "svg": _path_str(self.svg),
                "top_png": _path_str(self.top_png),
                "render_3d_png": _path_str(self.render_3d_png),
                "fab_zip": _path_str(self.fab_zip),
                "drc_report": _path_str(self.drc_report),
            },
            "drc": self.drc,
            "assembly": self.assembly,
            "part_optimization": self.part_optimization,
            "routed": self.routed,
            "notes": list(self.notes),
        }


def configure_kicad_environment() -> None:
    """Set KiCad symbol env vars when standard Linux library paths exist."""
    symbol_dirs = (
        Path("/usr/share/kicad/symbols"),
        Path("/usr/local/share/kicad/symbols"),
    )
    for sym_dir in symbol_dirs:
        if sym_dir.exists():
            for var in ("KICAD_SYMBOL_DIR", "KICAD8_SYMBOL_DIR", "KICAD9_SYMBOL_DIR"):
                os.environ.setdefault(var, str(sym_dir))
            return


def build_spec(
    *,
    topology: str,
    input_voltage: float,
    output_voltage: float,
    output_current: float,
    name: str | None = None,
    description: str | None = None,
) -> CircuitSpec:
    """Build a normalized CircuitSpec from user/tool parameters."""
    design_name = name or f"{topology}_{int(input_voltage)}v_{int(output_voltage)}v"
    return CircuitSpec(
        name=design_name,
        topology=topology,
        input_voltage=input_voltage,
        output_voltage=output_voltage,
        output_current=output_current,
        description=(
            description
            or f"{design_name}: {input_voltage}V to {output_voltage}V @ {output_current}A"
        ),
    )


def generate_pcb_artifacts(
    spec: CircuitSpec,
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    constraints_dir: Path = DEFAULT_CONSTRAINTS_DIR,
    route: bool = True,
    render: bool = True,
    export_fab: bool = True,
    run_drc: bool = True,
    prefer_basic: bool = False,
    optimize_parts: bool = True,
) -> PCBArtifactResult:
    """Generate full KiCad/fabrication artifacts for one design.

    Raises RuntimeError if the KiCad/SKiDL environment is unavailable. This is
    expected outside the distrobox and should be surfaced by callers as a tool
    capability error.
    """
    configure_kicad_environment()
    connect_default_parts_db()

    generator = get_generator(spec.topology)
    design = generator.generate(spec)
    output_dir.mkdir(parents=True, exist_ok=True)

    optimization_report: dict[str, object] | None = None
    if optimize_parts:
        optimization = optimize_jlcpcb_assembly(
            design,
            prefer_basic=prefer_basic,
        )
        design = optimization.optimized_design
        optimization_report = optimization.as_dict(include_design=False)

    engine = ConstraintEngine(constraints_dir)
    violations = engine.validate_design(design)
    errors = [v for v in violations if v.severity == Severity.ERROR]

    bom = BOMGenerator().generate(design)
    cost = CostBreakdown.from_bom(bom)
    assembly = validate_jlcpcb_assembly(
        design,
        prefer_basic=prefer_basic,
    ).as_dict()

    design_json = output_dir / f"{spec.name}.json"
    save_design(design, design_json)

    exporter = DesignExporter(output_dir)
    bom_csv = exporter.export_bom_csv(design)

    from etchant.kicad.netlist_builder import NetlistBuilder, check_skidl_available

    if not check_skidl_available():
        raise RuntimeError(
            "SKiDL/KiCad symbol libraries are unavailable. Run inside the etchant "
            "distrobox or install KiCad libraries before generating PCB artifacts."
        )

    netlist = NetlistBuilder(output_dir).build(design)
    project, routed = _write_project_and_board(
        design,
        netlist,
        output_dir,
        route=route,
    )
    pcb = project.with_suffix(".kicad_pcb")

    svg: Path | None = None
    top_png: Path | None = None
    render_3d_png: Path | None = None
    if render:
        svg, top_png, render_3d_png = _render_board(pcb)

    fab_zip: Path | None = None
    if export_fab:
        from etchant.kicad.fab_export import export_fabrication_files

        fab_zip = export_fabrication_files(pcb)

    drc_report: Path | None = None
    drc: dict[str, int] | None = None
    if run_drc:
        drc_report, drc = _run_drc(pcb)

    return PCBArtifactResult(
        spec=spec,
        component_count=len(design.components),
        net_count=len(design.nets),
        validation_errors=len(errors),
        setup_fee_usd=cost.total_setup_fee_usd,
        design_json=design_json,
        bom_csv=bom_csv,
        netlist=netlist,
        project=project,
        pcb=pcb,
        svg=svg,
        top_png=top_png,
        render_3d_png=render_3d_png,
        fab_zip=fab_zip,
        drc_report=drc_report,
        drc=drc,
        assembly=assembly,
        part_optimization=optimization_report,
        routed=routed,
        notes=design.design_notes,
    )


def _write_project_and_board(
    design: DesignResult,
    netlist: Path,
    output_dir: Path,
    *,
    route: bool,
) -> tuple[Path, bool]:
    from etchant.kicad.placement import ComponentPlacer, check_pcbnew_available
    from etchant.kicad.project_writer import ProjectWriter

    if not check_pcbnew_available():
        raise RuntimeError(
            "pcbnew is unavailable. Run inside KiCad's Python environment."
        )

    project = ProjectWriter(output_dir).write_project(design, netlist)
    pcb = project.with_suffix(".kicad_pcb")
    ComponentPlacer().create_board(design, pcb)

    routed = False
    if route:
        from etchant.kicad.design_rules import power_trace_width_mm
        from etchant.kicad.router import FreeroutingRouter, check_freerouting_available

        if check_freerouting_available():
            FreeroutingRouter(max_passes=20).route_board(
                pcb,
                power_track_width_mm=power_trace_width_mm(design.spec.output_current),
            )
            routed = True

    return project, routed


def _render_board(pcb: Path) -> tuple[Path | None, Path | None, Path | None]:
    svg = pcb.with_suffix(".svg")
    top_png = pcb.parent / f"{pcb.stem}_top.png"
    render_3d_png = pcb.parent / f"{pcb.stem}_3d.png"

    try:
        subprocess.run(
            [
                "kicad-cli", "pcb", "export", "svg",
                "--layers", "F.Cu,B.Cu,Edge.Cuts,F.SilkS",
                "--fit-page-to-board",
                "--exclude-drawing-sheet",
                "-o", str(svg),
                str(pcb),
            ],
            capture_output=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        svg = None

    render_size = ["--width", "1600", "--height", "1200"]
    renders = [
        (top_png, ["--side", "top"]),
        (render_3d_png, ["--side", "top", "--rotate", "-30,0,-20", "--perspective"]),
    ]
    for out_path, extra_args in renders:
        try:
            subprocess.run(
                [
                    "kicad-cli", "pcb", "render",
                    "--quality", "high",
                    *render_size,
                    *extra_args,
                    "-o", str(out_path),
                    str(pcb),
                ],
                capture_output=True,
                timeout=60,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            out_path.unlink(missing_ok=True)

    svg_result = svg if svg is not None and svg.exists() else None
    top_result = top_png if top_png.exists() else None
    render_3d_result = render_3d_png if render_3d_png.exists() else None
    return svg_result, top_result, render_3d_result


def _run_drc(pcb: Path) -> tuple[Path, dict[str, int]]:
    from etchant.kicad.drc_report import parse_drc_report

    report_path = pcb.with_suffix(".drc.rpt")
    result = subprocess.run(
        [
            "kicad-cli", "pcb", "drc",
            "--severity-all",
            "--output", str(report_path),
            str(pcb),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if not report_path.exists():
        raise RuntimeError(f"kicad-cli drc produced no report: {result.stderr}")

    report = parse_drc_report(report_path)
    return report_path, {
        "errors": report.errors_only,
        "warnings": report.warnings_only,
        "unconnected_pads": report.unconnected_pads,
        "total_violations": report.total_violations,
    }


def _path_str(path: Path | None) -> str | None:
    return str(path) if path is not None else None
