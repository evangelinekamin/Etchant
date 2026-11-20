"""Tool definitions for the LLM agent layer.

These are the tools the agent can call to interact with the Etchant pipeline.
Each tool maps to a function in the core/kicad modules. The agent's job is to
go from natural language -> tool calls -> KiCad project.

Week 2: Wire these up to Claude or another LLM as a tool-using agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolDefinition:
    """Definition of a tool the agent can call."""

    name: str
    description: str
    parameters: dict[str, Any]
    required_params: tuple[str, ...]


# Tool definitions for the agent
TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="list_topologies",
        description="List all available circuit topologies that can be generated.",
        parameters={},
        required_params=(),
    ),
    ToolDefinition(
        name="generate_circuit",
        description=(
            "Generate a complete circuit design from a specification. "
            "Returns component list, netlist, placement constraints, and cost estimate."
        ),
        parameters={
            "topology": {
                "type": "string",
                "description": "Circuit topology (e.g., 'buck_converter', 'ldo_regulator')",
            },
            "input_voltage": {
                "type": "number",
                "description": "Input voltage in volts",
            },
            "output_voltage": {
                "type": "number",
                "description": "Output voltage in volts",
            },
            "output_current": {
                "type": "number",
                "description": "Output current in amps",
            },
        },
        required_params=("topology", "input_voltage", "output_voltage", "output_current"),
    ),
    ToolDefinition(
        name="validate_design",
        description=(
            "Validate a generated design against manufacturing and electrical constraints. "
            "Returns violations and recommendations."
        ),
        parameters={
            "topology": {"type": "string", "description": "Circuit topology"},
            "input_voltage": {"type": "number", "description": "Input voltage in volts"},
            "output_voltage": {"type": "number", "description": "Output voltage in volts"},
            "output_current": {"type": "number", "description": "Output current in amps"},
        },
        required_params=("topology", "input_voltage", "output_voltage", "output_current"),
    ),
    ToolDefinition(
        name="estimate_cost",
        description=(
            "Estimate JLCPCB manufacturing and assembly cost for a design. "
            "Shows basic vs extended parts breakdown and setup fees."
        ),
        parameters={
            "topology": {"type": "string", "description": "Circuit topology"},
            "input_voltage": {"type": "number", "description": "Input voltage in volts"},
            "output_voltage": {"type": "number", "description": "Output voltage in volts"},
            "output_current": {"type": "number", "description": "Output current in amps"},
            "board_width_mm": {
                "type": "number",
                "description": "Board width in mm (default: 50)",
            },
            "board_height_mm": {
                "type": "number",
                "description": "Board height in mm (default: 50)",
            },
            "quantity": {
                "type": "integer",
                "description": "Number of boards to order (default: 5)",
            },
        },
        required_params=("topology", "input_voltage", "output_voltage", "output_current"),
    ),
    ToolDefinition(
        name="lookup_jlcpcb_part",
        description=(
            "Look up a component in the JLCPCB parts database. "
            "Returns part number, classification (basic/extended), stock level."
        ),
        parameters={
            "value": {
                "type": "string",
                "description": "Component value to look up (e.g., '10k', 'LM2596S-5')",
            },
        },
        required_params=("value",),
    ),
    ToolDefinition(
        name="suggest_topology",
        description=(
            "Suggest the best circuit topology for given power requirements. "
            "Provide either numerical specs or a natural language description."
        ),
        parameters={
            "description": {
                "type": "string",
                "description": "Natural language description of the power supply needed",
            },
            "input_voltage": {
                "type": "number",
                "description": "Input voltage in volts (for precise recommendation)",
            },
            "output_voltage": {
                "type": "number",
                "description": "Output voltage in volts",
            },
            "output_current": {
                "type": "number",
                "description": "Output current in amps",
            },
            "priority": {
                "type": "string",
                "description": (
                    "Design priority: balanced, efficiency, noise, cost, size, "
                    "usb_power, or protection"
                ),
            },
        },
        required_params=(),
    ),
    ToolDefinition(
        name="export_design",
        description=(
            "Export a generated design to JSON (full design) and/or CSV (JLCPCB BOM)."
        ),
        parameters={
            "topology": {"type": "string", "description": "Circuit topology"},
            "input_voltage": {"type": "number", "description": "Input voltage in volts"},
            "output_voltage": {"type": "number", "description": "Output voltage in volts"},
            "output_current": {"type": "number", "description": "Output current in amps"},
            "format": {
                "type": "string",
                "description": "Export format: 'json', 'csv', or 'both'",
            },
            "output_dir": {
                "type": "string",
                "description": "Output directory path",
            },
        },
        required_params=("topology", "input_voltage", "output_voltage", "output_current"),
    ),
    ToolDefinition(
        name="validate_jlcpcb_assembly",
        description=(
            "Validate whether a generated design is ready for JLCPCB assembly. "
            "Checks LCSC part matches, Basic vs Extended parts, stock, package/footprint "
            "mismatches, and through-hole/manual-assembly items."
        ),
        parameters={
            "topology": {"type": "string", "description": "Circuit topology"},
            "input_voltage": {"type": "number", "description": "Input voltage in volts"},
            "output_voltage": {"type": "number", "description": "Output voltage in volts"},
            "output_current": {"type": "number", "description": "Output current in amps"},
            "min_stock": {
                "type": "integer",
                "description": "Minimum acceptable JLCPCB stock per part (default: 1)",
            },
            "prefer_basic": {
                "type": "boolean",
                "description": (
                    "Warn on Extended Parts so Basic Parts can be prioritized "
                    "(default: false)"
                ),
            },
        },
        required_params=("topology", "input_voltage", "output_voltage", "output_current"),
    ),
    ToolDefinition(
        name="optimize_jlcpcb_assembly",
        description=(
            "Automatically select stocked JLCPCB parts for a generated design. "
            "Prioritizes Basic Parts, tags chosen LCSC part numbers, and applies safe "
            "footprint corrections when the selected package is known."
        ),
        parameters={
            "topology": {"type": "string", "description": "Circuit topology"},
            "input_voltage": {"type": "number", "description": "Input voltage in volts"},
            "output_voltage": {"type": "number", "description": "Output voltage in volts"},
            "output_current": {"type": "number", "description": "Output current in amps"},
            "min_stock": {
                "type": "integer",
                "description": "Minimum acceptable JLCPCB stock per part (default: 1)",
            },
            "prefer_basic": {
                "type": "boolean",
                "description": "Prefer JLCPCB Basic Parts over Extended Parts (default: true)",
            },
        },
        required_params=("topology", "input_voltage", "output_voltage", "output_current"),
    ),
    ToolDefinition(
        name="generate_pcb_project",
        description=(
            "Generate full KiCad PCB artifacts for a design: JSON, BOM CSV, netlist, "
            "KiCad project, placed/routed PCB, renders, Gerber zip, DRC summary, and "
            "JLCPCB assembly-readiness report. Requires the KiCad/SKiDL distrobox "
            "environment."
        ),
        parameters={
            "topology": {"type": "string", "description": "Circuit topology"},
            "input_voltage": {"type": "number", "description": "Input voltage in volts"},
            "output_voltage": {"type": "number", "description": "Output voltage in volts"},
            "output_current": {"type": "number", "description": "Output current in amps"},
            "name": {
                "type": "string",
                "description": "Optional output/project name",
            },
            "output_dir": {
                "type": "string",
                "description": "Output directory path within the configured output root",
            },
            "route": {
                "type": "boolean",
                "description": "Run Freerouting if available (default: true)",
            },
            "render": {
                "type": "boolean",
                "description": "Render top/3D PNGs (default: true)",
            },
            "export_fab": {
                "type": "boolean",
                "description": "Export JLCPCB-ready Gerber zip (default: true)",
            },
            "run_drc": {
                "type": "boolean",
                "description": "Run kicad-cli DRC and return counts (default: true)",
            },
            "prefer_basic": {
                "type": "boolean",
                "description": (
                    "Warn on Extended Parts in the assembly report so Basic Parts can "
                    "be prioritized (default: false)"
                ),
            },
            "optimize_parts": {
                "type": "boolean",
                "description": (
                    "Apply automatic JLCPCB part substitutions before exporting "
                    "(default: true)"
                ),
            },
        },
        required_params=("topology", "input_voltage", "output_voltage", "output_current"),
    ),
)


def get_tool_definitions_for_api() -> list[dict[str, Any]]:
    """Convert tool definitions to the format expected by Claude's tool_use API."""
    api_tools: list[dict[str, Any]] = []
    for tool in TOOLS:
        properties: dict[str, Any] = {}
        for param_name, param_info in tool.parameters.items():
            properties[param_name] = {
                "type": param_info["type"],
                "description": param_info["description"],
            }

        api_tools.append({
            "name": tool.name,
            "description": tool.description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": list(tool.required_params),
            },
        })
    return api_tools
