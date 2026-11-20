"""Patch SKiDL 2.2.2 circular import bug.

The bug is in skidl/tools/kicad8/lib.py where `from skidl import get_default_tool`
is called during module initialization, before skidl is fully loaded.

Fix: Replace the dynamic tool version lookup with the tool module's hardcoded
KiCad version suffix. This script intentionally discovers the active virtual
environment instead of assuming `.venv/lib/python3.11`.
"""

import os
import sys
from pathlib import Path


def patch_tool_module(venv_path: Path, tool_name: str, version_suffix: str) -> None:
    lib_file = _skidl_tools_dir(venv_path) / tool_name / "lib.py"

    if not lib_file.exists():
        print(f"  {tool_name}: file not found, skipping")
        return

    content = lib_file.read_text()

    old_code = (
        '    from skidl import get_default_tool\n\n'
        '    kicad_version = get_default_tool()[len("kicad"):]\n'
    )
    new_code = (
        "    # Patched: avoid circular import (SKiDL 2.2.2 bug)\n"
        f'    kicad_version = "{version_suffix}"\n'
    )

    if old_code not in content:
        if "Patched: avoid circular import" in content:
            print(f"  {tool_name}: already patched")
            return
        print(f"  {tool_name}: code not found, skipping")
        return

    content = content.replace(old_code, new_code)
    lib_file.write_text(content)
    print(f"  {tool_name}: patched")


def patch_skidl(venv_path: Path) -> None:
    print("Patching SKiDL circular import bug...")
    tools_dir = _skidl_tools_dir(venv_path)
    if not tools_dir.exists():
        print(f"SKiDL tools directory not found: {tools_dir}")
        sys.exit(1)

    for tool_dir in sorted(tools_dir.iterdir()):
        if tool_dir.is_dir() and tool_dir.name.startswith("kicad"):
            version = tool_dir.name[len("kicad"):]
            patch_tool_module(venv_path, tool_dir.name, version)


def _skidl_tools_dir(venv_path: Path) -> Path:
    candidates = sorted(
        (venv_path / "lib").glob("python*/site-packages/skidl/tools")
    )
    if candidates:
        return candidates[0]
    return venv_path / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / (
        "site-packages/skidl/tools"
    )


def _active_venv() -> Path:
    if os.environ.get("VIRTUAL_ENV"):
        return Path(os.environ["VIRTUAL_ENV"])
    return Path(sys.prefix)


if __name__ == "__main__":
    patch_skidl(_active_venv())
