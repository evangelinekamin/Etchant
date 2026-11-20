"""Run Etchant's demo designs through the full KiCad artifact pipeline."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from etchant.kicad.pipeline import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    build_spec,
    configure_kicad_environment,
    generate_pcb_artifacts,
)


def _patch_skidl() -> None:
    patch_script = REPO_ROOT / "scripts" / "patch_skidl.py"
    exec(patch_script.read_text(), {"__file__": str(patch_script)})


def _run_design(
    name: str,
    topology: str,
    vin: float,
    vout: float,
    iout: float,
) -> Path:
    print(f"\n{'=' * 60}")
    print(f"  {name}: {vin}V -> {vout}V @ {iout}A")
    print(f"{'=' * 60}")

    spec = build_spec(
        name=name,
        topology=topology,
        input_voltage=vin,
        output_voltage=vout,
        output_current=iout,
    )
    result = generate_pcb_artifacts(
        spec,
        output_dir=DEFAULT_OUTPUT_DIR / name,
        route=True,
        render=True,
        export_fab=True,
        run_drc=True,
    )
    paths = result.as_dict()["paths"]

    print(f"  Components: {result.component_count}")
    print(f"  Nets: {result.net_count}")
    print(f"  Validation: {'PASS' if result.validation_errors == 0 else result.validation_errors}")
    print(f"  Setup fee: ${result.setup_fee_usd:.2f}")
    print(f"  Design JSON: {paths['design_json']}")
    print(f"  BOM CSV: {paths['bom_csv']}")
    print(f"  Netlist: {paths['netlist']}")
    print(f"  Project: {paths['project']}")
    print(f"  PCB: {paths['pcb']}")
    print(f"  Routed: {result.routed}")
    print(f"  Render top: {paths['top_png']}")
    print(f"  Render 3D: {paths['render_3d_png']}")
    print(f"  Fab zip: {paths['fab_zip']}")
    if result.drc:
        print(
            "  DRC: "
            f"errors={result.drc['errors']} "
            f"warnings={result.drc['warnings']} "
            f"unconnected={result.drc['unconnected_pads']}"
        )
    for note in result.notes:
        print(f"  Note: {note}")

    return DEFAULT_OUTPUT_DIR / name


def main() -> int:
    configure_kicad_environment()
    _patch_skidl()

    demo_specs = (
        ("ldo_5v_to_3v3", "ldo_regulator_ams1117", 5.0, 3.3, 0.5),
        ("buck_12v_to_5v", "buck_converter", 12.0, 5.0, 2.0),
        ("led_5v_20ma", "led_driver", 5.0, 2.0, 0.02),
        ("esp32c3_breakout", "mcu_breakout", 5.0, 3.3, 0.5),
        ("opamp_buffer_5v", "op_amp_buffer", 5.0, 5.0, 0.022),
        ("divider_5v_to_2v5", "voltage_divider", 5.0, 2.5, 0.001),
        ("mosfet_switch_5v_100ma", "mosfet_switch", 5.0, 5.0, 0.1),
    )

    dirs = [_run_design(*spec) for spec in demo_specs]

    zip_path = DEFAULT_OUTPUT_DIR / "etchant_demo.zip"
    print(f"\n{'=' * 60}")
    print(f"  Creating zip: {zip_path}")
    print(f"{'=' * 60}")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for directory in dirs:
            for filepath in directory.rglob("*"):
                if filepath.is_file():
                    zf.write(filepath, filepath.relative_to(DEFAULT_OUTPUT_DIR))

    print(f"  Zip size: {zip_path.stat().st_size} bytes")
    print(f"\n  Done. Open {zip_path} in KiCad or upload a *_gerbers.zip to your fab.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
