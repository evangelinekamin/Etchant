"""Export fabrication files (Gerber X2 + Excellon drill) for JLCPCB.

JLCPCB and most Chinese fabs accept a single .zip containing:
  - Gerber files for each layer (F.Cu/B.Cu/F.Mask/B.Mask/F.Silk/B.Silk/
    F.Paste/B.Paste/Edge.Cuts) — Gerber X2 format with netlist metadata
  - Excellon drill files (PTH + NPTH separated)
  - The KiCad-generated .gbrjob file describing the layer stackup

This module wraps ``kicad-cli pcb export gerbers`` and
``kicad-cli pcb export drill`` to produce a fab-ready zip next to the
input PCB. Invoked from scripts/full_pipeline.py so every generated
board ships with a file you can upload straight to the JLCPCB quote
page.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Standard JLCPCB-accepted 2-layer stackup. Paste layers are included
# for users who'll also order PCBA (stencil manufacturing).
_GERBER_LAYERS = (
    "F.Cu", "B.Cu",
    "F.Mask", "B.Mask",
    "F.Silkscreen", "B.Silkscreen",
    "F.Paste", "B.Paste",
    "Edge.Cuts",
)


def export_fabrication_files(
    pcb_path: Path, output_dir: Path | None = None,
) -> Path | None:
    """Export gerbers + drill, zip them. Returns the zip path, or None.

    The zip lives next to the .kicad_pcb by default and is named
    ``<board_stem>_gerbers.zip``. Raw gerber files are kept under
    ``<board_stem>_gerbers/`` for inspection.

    Returns None if kicad-cli isn't available or export fails.
    """
    base = output_dir or pcb_path.parent
    gerber_dir = base / f"{pcb_path.stem}_gerbers"
    zip_path = base / f"{pcb_path.stem}_gerbers.zip"

    # Clean stale output — stale gerbers from a prior run would end up
    # in the new zip alongside the current ones.
    if gerber_dir.exists():
        shutil.rmtree(gerber_dir)
    gerber_dir.mkdir(parents=True)
    zip_path.unlink(missing_ok=True)

    try:
        gerber_cmd = [
            "kicad-cli", "pcb", "export", "gerbers",
            "--layers", ",".join(_GERBER_LAYERS),
            "--output", str(gerber_dir) + "/",
            str(pcb_path),
        ]
        result = subprocess.run(
            gerber_cmd, capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            logger.warning(
                "gerber export failed (rc=%d): %s",
                result.returncode, result.stderr.strip()[-200:],
            )
            return None

        drill_cmd = [
            "kicad-cli", "pcb", "export", "drill",
            "--format", "excellon",
            "--excellon-separate-th",
            "--generate-map",
            "--output", str(gerber_dir) + "/",
            str(pcb_path),
        ]
        result = subprocess.run(
            drill_cmd, capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            logger.warning(
                "drill export failed (rc=%d): %s",
                result.returncode, result.stderr.strip()[-200:],
            )
            return None
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.warning("kicad-cli fab export unavailable: %s", e)
        return None

    # Bundle everything in the gerber dir into the zip at root level
    # (JLCPCB's uploader expects flat files, not nested directories).
    files = sorted(p for p in gerber_dir.iterdir() if p.is_file())
    if not files:
        return None
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, arcname=f.name)

    logger.info(
        "Fab export: %d files -> %s", len(files), zip_path.name,
    )
    return zip_path
