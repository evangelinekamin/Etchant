"""Tool executor for the LLM agent layer.

Maps tool call names to actual pipeline functions. The agent sends a tool name
and arguments; the executor runs the corresponding pipeline operation and returns
a structured result.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from etchant.circuits import get_generator, list_topologies
from etchant.core.assembly_validator import validate_jlcpcb_assembly
from etchant.core.bom import BOMGenerator, CostBreakdown
from etchant.core.component_selector import (
    connect_default_parts_db,
    lookup_jlcpcb_part,
)
from etchant.core.constraint_engine import ConstraintEngine, Severity
from etchant.core.manufacturing import check_assembly_compatibility, estimate_board_cost
from etchant.core.models import CircuitSpec
from etchant.core.part_optimizer import optimize_jlcpcb_assembly
from etchant.core.topology_advisor import recommend_topology
from etchant.kicad.design_export import DesignExporter

logger = logging.getLogger(__name__)


class ToolExecutor:
    """Executes tool calls from the LLM agent."""

    def __init__(
        self, constraints_dir: Path | None = None, output_dir: Path | None = None
    ) -> None:
        default_constraints = Path(__file__).parent.parent.parent / "constraints"
        self._constraints_dir = constraints_dir or default_constraints
        self._output_dir = (output_dir or Path("./output")).resolve()
        connect_default_parts_db()

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool call and return the result as a dict."""
        handlers = {
            "list_topologies": self._list_topologies,
            "generate_circuit": self._generate_circuit,
            "validate_design": self._validate_design,
            "estimate_cost": self._estimate_cost,
            "lookup_jlcpcb_part": self._lookup_part,
            "suggest_topology": self._suggest_topology,
            "export_design": self._export_design,
            "validate_jlcpcb_assembly": self._validate_jlcpcb_assembly,
            "optimize_jlcpcb_assembly": self._optimize_jlcpcb_assembly,
            "generate_pcb_project": self._generate_pcb_project,
        }

        handler = handlers.get(tool_name)
        if handler is None:
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            return handler(arguments)
        except Exception as exc:
            logger.debug("Tool '%s' failed", tool_name, exc_info=True)
            return {"error": f"Tool '{tool_name}' failed: {_safe_error_message(exc)}"}

    def _list_topologies(self, _args: dict[str, Any]) -> dict[str, Any]:
        return {"topologies": list(list_topologies())}

    def _generate_circuit(self, args: dict[str, Any]) -> dict[str, Any]:
        spec = self._make_spec(args)
        generator = get_generator(spec.topology)
        design = generator.generate(spec)

        return {
            "spec": {
                "name": design.spec.name,
                "topology": design.spec.topology,
                "input_voltage": design.spec.input_voltage,
                "output_voltage": design.spec.output_voltage,
                "output_current": design.spec.output_current,
            },
            "components": [
                {
                    "reference": c.reference,
                    "value": c.value,
                    "category": c.category.name,
                    "footprint": c.footprint,
                    "description": c.description,
                }
                for c in design.components
            ],
            "nets": [
                {"name": n.name, "connection_count": len(n.connections)}
                for n in design.nets
            ],
            "placement_constraints": len(design.placement_constraints),
            "design_notes": list(design.design_notes),
        }

    def _validate_design(self, args: dict[str, Any]) -> dict[str, Any]:
        spec = self._make_spec(args)
        generator = get_generator(spec.topology)
        design = generator.generate(spec)

        engine = ConstraintEngine(self._constraints_dir)
        violations = engine.validate_design(design)

        issues = check_assembly_compatibility(design, self._constraints_dir)

        return {
            "errors": [
                {"rule": v.rule, "message": v.message}
                for v in violations if v.severity == Severity.ERROR
            ],
            "warnings": [
                {"rule": v.rule, "message": v.message}
                for v in violations if v.severity == Severity.WARNING
            ],
            "info": [
                {"rule": v.rule, "message": v.message}
                for v in violations if v.severity == Severity.INFO
            ],
            "assembly_issues": issues,
        }

    def _estimate_cost(self, args: dict[str, Any]) -> dict[str, Any]:
        spec = self._make_spec(args)
        generator = get_generator(spec.topology)
        design = generator.generate(spec)

        bom_gen = BOMGenerator()
        bom = bom_gen.generate(design)
        cost = CostBreakdown.from_bom(bom)

        board_cost = estimate_board_cost(
            board_size_mm=(
                args.get("board_width_mm", 50.0),
                args.get("board_height_mm", 50.0),
            ),
            layers=2,
            quantity=args.get("quantity", 5),
        )

        return {
            "bom": {
                "total_parts": len(bom),
                "basic_parts": cost.basic_parts_count,
                "extended_parts": cost.extended_parts_count,
                "unknown_parts": cost.unknown_parts_count,
                "assembly_setup_fee_usd": cost.total_setup_fee_usd,
            },
            "board": board_cost,
            "summary": cost.summary(),
        }

    def _lookup_part(self, args: dict[str, Any]) -> dict[str, Any]:
        value = args.get("value", "")
        info = lookup_jlcpcb_part(value)
        if info is None:
            return {"found": False, "value": value}
        return {
            "found": True,
            "value": value,
            "part_number": info.part_number,
            "classification": info.classification.value,
            "description": info.description,
            "stock": info.stock,
            "setup_fee_usd": info.setup_fee_usd,
        }

    def _suggest_topology(self, args: dict[str, Any]) -> dict[str, Any]:
        vin = args.get("input_voltage")
        vout = args.get("output_voltage")
        iout = args.get("output_current")
        priority = args.get("priority", "balanced")

        if vin is not None and vout is not None and iout is not None:
            rec = recommend_topology(
                float(vin), float(vout), float(iout), priority=priority,
            )
            return {
                "suggested_topology": rec.topology,
                "confidence": rec.confidence,
                "reason": rec.reason,
                "tradeoffs": list(rec.tradeoffs),
                "alternatives": list(rec.alternatives),
            }

        desc = args.get("description", "").lower()

        if any(w in desc for w in ("low noise", "ldo", "linear", "low dropout")):
            return {
                "suggested_topology": "ldo_regulator",
                "reason": "LDO regulators provide clean, low-noise output",
            }

        if any(w in desc for w in ("efficient", "high current", "step down", "buck")):
            return {
                "suggested_topology": "buck_converter",
                "reason": "Buck converters are highly efficient (85-95%)",
            }

        return {
            "suggested_topology": "buck_converter",
            "reason": "Default — use LDO if noise is critical",
            "available_topologies": list(list_topologies()),
        }

    def _export_design(self, args: dict[str, Any]) -> dict[str, Any]:
        spec = self._make_spec(args)
        generator = get_generator(spec.topology)
        design = generator.generate(spec)

        export_format = args.get("format", "both")

        out_dir = self._resolve_output_dir(args.get("output_dir", str(self._output_dir)))
        if out_dir is None:
            return {"error": f"output_dir must be within {self._output_dir}"}

        exporter = DesignExporter(out_dir)

        result: dict[str, Any] = {"exported": []}

        if export_format in ("json", "both"):
            json_path = exporter.export_json(design)
            result["exported"].append({"format": "json", "path": str(json_path)})

        if export_format in ("csv", "both"):
            csv_path = exporter.export_bom_csv(design)
            result["exported"].append({"format": "csv", "path": str(csv_path)})

        return result

    def _validate_jlcpcb_assembly(self, args: dict[str, Any]) -> dict[str, Any]:
        """Check whether a generated design is ready for JLCPCB assembly."""
        spec = self._make_spec(args)
        generator = get_generator(spec.topology)
        design = generator.generate(spec)

        report = validate_jlcpcb_assembly(
            design,
            min_stock=int(args.get("min_stock", 1)),
            prefer_basic=_bool_arg(args, "prefer_basic", False),
        )
        return report.as_dict()

    def _optimize_jlcpcb_assembly(self, args: dict[str, Any]) -> dict[str, Any]:
        """Apply automatic JLCPCB part substitutions to a generated design."""
        spec = self._make_spec(args)
        generator = get_generator(spec.topology)
        design = generator.generate(spec)

        result = optimize_jlcpcb_assembly(
            design,
            min_stock=int(args.get("min_stock", 1)),
            prefer_basic=_bool_arg(args, "prefer_basic", True),
        )
        return result.as_dict()

    def _generate_pcb_project(self, args: dict[str, Any]) -> dict[str, Any]:
        """Generate full KiCad/Fab artifacts for an agent-selected design."""
        from etchant.kicad.pipeline import build_spec, generate_pcb_artifacts

        required = ("topology", "input_voltage", "output_voltage", "output_current")
        missing = [k for k in required if k not in args]
        if missing:
            return {"error": f"Missing required parameters: {', '.join(missing)}"}

        out_dir = self._resolve_output_dir(args.get("output_dir", str(self._output_dir)))
        if out_dir is None:
            return {"error": f"output_dir must be within {self._output_dir}"}

        spec = build_spec(
            name=args.get("name"),
            topology=str(args["topology"]),
            input_voltage=float(args["input_voltage"]),
            output_voltage=float(args["output_voltage"]),
            output_current=float(args["output_current"]),
        )

        try:
            result = generate_pcb_artifacts(
                spec,
                output_dir=out_dir,
                constraints_dir=self._constraints_dir,
                route=_bool_arg(args, "route", True),
                render=_bool_arg(args, "render", True),
                export_fab=_bool_arg(args, "export_fab", True),
                run_drc=_bool_arg(args, "run_drc", True),
                prefer_basic=_bool_arg(args, "prefer_basic", False),
                optimize_parts=_bool_arg(args, "optimize_parts", True),
            )
        except RuntimeError as e:
            return {"error": str(e)}

        return result.as_dict()

    def _resolve_output_dir(self, requested: object) -> Path | None:
        """Resolve output paths and reject escapes from configured root."""
        requested_path = Path(str(requested))
        if requested_path.is_absolute():
            resolved = requested_path.resolve()
        else:
            resolved = (self._output_dir / requested_path).resolve()
        if not resolved.is_relative_to(self._output_dir):
            return None
        return resolved

    def _make_spec(self, args: dict[str, Any]) -> CircuitSpec:
        required = ("topology", "input_voltage", "output_voltage", "output_current")
        missing = [k for k in required if k not in args]
        if missing:
            raise ValueError(f"Missing required parameters: {', '.join(missing)}")

        vin = float(args["input_voltage"])
        vout = float(args["output_voltage"])
        iout = float(args["output_current"])

        if vin <= 0 or vout <= 0 or iout <= 0:
            raise ValueError("Voltages and current must be positive")

        topology = str(args["topology"])

        return CircuitSpec(
            name=f"{topology}_{int(vin)}v_{int(vout)}v",
            topology=topology,
            input_voltage=vin,
            output_voltage=vout,
            output_current=iout,
            description=f"{topology}: {vin}V to {vout}V @ {iout}A",
        )


def _bool_arg(args: dict[str, Any], name: str, default: bool) -> bool:
    value = args.get(name, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _safe_error_message(exc: Exception) -> str:
    """Return useful tool errors without leaking local absolute paths."""
    message = str(exc) or exc.__class__.__name__
    for sensitive in {str(Path.home()), str(Path.cwd())}:
        if sensitive:
            message = message.replace(sensitive, "<path>")
    return message
