"""CLI wrapper around ToolExecutor for subagent-as-LLM flows.

Lets a Claude Code subagent (or any shell-driven LLM) invoke the
agent-layer tools without needing the Anthropic SDK or an API key.
Each invocation takes a tool name + JSON arguments and prints a
JSON result.

Usage:
    python -m etchant.agents.subagent_runner <tool_name> '<json_args>'

    python -m etchant.agents.subagent_runner list_topologies '{}'
    python -m etchant.agents.subagent_runner suggest_topology \\
        '{"input_voltage": 5, "output_voltage": 3.3, "output_current": 0.5}'
    python -m etchant.agents.subagent_runner generate_circuit \\
        '{"topology": "ldo_regulator", "input_voltage": 5, \\
          "output_voltage": 3.3, "output_current": 0.5}'

Tool list and schemas:
    python -m etchant.agents.subagent_runner --list-tools

Exits 0 on success, 1 on unknown tool / bad JSON, 2 on tool error.
Stdout is always valid JSON; diagnostics go to stderr.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from etchant.agents.executor import ToolExecutor
from etchant.agents.tools import TOOLS


def _format_tool_catalog() -> dict:
    """Machine-readable listing of every tool and its schema."""
    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "parameters": {
                    name: {
                        "type": spec["type"],
                        "description": spec["description"],
                    }
                    for name, spec in t.parameters.items()
                },
                "required": list(t.required_params),
            }
            for t in TOOLS
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Invoke a single Etchant agent-layer tool from the shell.",
    )
    parser.add_argument(
        "tool", nargs="?", help="Tool name (e.g., generate_circuit)",
    )
    parser.add_argument(
        "args_json", nargs="?", default="{}",
        help="Tool arguments as a JSON object",
    )
    parser.add_argument(
        "--list-tools", action="store_true",
        help="Print every available tool with its schema and exit.",
    )
    parser.add_argument(
        "--output-dir", default="./output",
        help="Output directory for tools that write files (default: ./output)",
    )
    ns = parser.parse_args(argv)

    if ns.list_tools:
        print(json.dumps(_format_tool_catalog(), indent=2))
        return 0

    if not ns.tool:
        parser.print_help(sys.stderr)
        return 1

    try:
        args = json.loads(ns.args_json)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"[runner] bad JSON for arguments: {e}\n")
        return 1
    if not isinstance(args, dict):
        sys.stderr.write(
            f"[runner] arguments must be a JSON object, got {type(args).__name__}\n"
        )
        return 1

    executor = ToolExecutor(output_dir=Path(ns.output_dir))
    result = executor.execute(ns.tool, args)
    print(json.dumps(result, indent=2, default=str))
    return 2 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())
