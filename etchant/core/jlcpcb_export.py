"""JLCPCB assembly export: BOM and CPL in JLCPCB's upload formats.

JLCPCB PCBA ordering needs two files alongside the Gerbers:

- a **BOM** with columns ``Comment, Designator, Footprint, LCSC Part #`` and one
  row per unique part (designators of identical parts joined together), and
- a **CPL** (component placement list / pick-and-place) with columns
  ``Designator, Mid X, Mid Y, Layer, Rotation``.

This module builds those structures and serializes them. The BOM is derived from
a design's :class:`~etchant.core.bom.BOMEntry` list and needs no KiCad. The CPL
is reformatted from KiCad's own position export (``kicad-cli pcb export pos``),
so the placement coordinates come from the real laid-out board.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path

from etchant.core.bom import BOMEntry

_REF_PATTERN = re.compile(r"([A-Za-z]+)(\d+)")

JLCPCB_BOM_HEADER = ["Comment", "Designator", "Footprint", "LCSC Part #"]
JLCPCB_CPL_HEADER = ["Designator", "Mid X", "Mid Y", "Layer", "Rotation"]


@dataclass(frozen=True)
class JLCPCBBOMRow:
    """One BOM line: a unique part and every designator that uses it."""

    comment: str
    designators: tuple[str, ...]
    footprint: str
    lcsc_part: str | None


@dataclass(frozen=True)
class JLCPCBCPLRow:
    """One placement line for the pick-and-place machine."""

    designator: str
    mid_x_mm: float
    mid_y_mm: float
    layer: str
    rotation_deg: float


def _natural_key(reference: str) -> tuple[str, int]:
    """Sort references so C2 precedes C10 (prefix, then numeric suffix)."""
    match = _REF_PATTERN.match(reference)
    if match:
        return (match.group(1), int(match.group(2)))
    return (reference, 0)


def _clean_footprint(footprint: str) -> str:
    """Strip the KiCad ``Library:`` prefix, leaving the package name."""
    return footprint.split(":", 1)[-1]


def aggregate_jlcpcb_bom(bom: tuple[BOMEntry, ...]) -> tuple[JLCPCBBOMRow, ...]:
    """Collapse per-component BOM entries into one row per unique part.

    Parts are considered identical when their value, footprint and LCSC part
    number all match, which is exactly the granularity JLCPCB assembles at.
    Group order follows first appearance so the BOM stays stable and reviewable.
    """
    groups: dict[tuple[str, str, str | None], list[BOMEntry]] = {}
    order: list[tuple[str, str, str | None]] = []
    for entry in bom:
        key = (entry.value, entry.footprint, entry.jlcpcb_part_number)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(entry)

    rows: list[JLCPCBBOMRow] = []
    for key in order:
        members = groups[key]
        designators = tuple(
            sorted((m.reference for m in members), key=_natural_key)
        )
        first = members[0]
        rows.append(
            JLCPCBBOMRow(
                comment=first.value,
                designators=designators,
                footprint=_clean_footprint(first.footprint),
                lcsc_part=first.jlcpcb_part_number,
            )
        )
    return tuple(rows)


def write_jlcpcb_bom_csv(rows: tuple[JLCPCBBOMRow, ...], path: Path) -> Path:
    """Write a JLCPCB-format BOM CSV. Returns the path written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(JLCPCB_BOM_HEADER)
    for row in rows:
        writer.writerow([
            row.comment,
            ",".join(row.designators),
            row.footprint,
            row.lcsc_part or "",
        ])

    with open(path, "w", newline="") as handle:
        handle.write(buffer.getvalue())
    return path


def cpl_rows_from_kicad_pos(pos_csv: str) -> tuple[JLCPCBCPLRow, ...]:
    """Parse ``kicad-cli pcb export pos --format csv`` text into CPL rows.

    KiCad emits ``Ref,Val,Package,PosX,PosY,Rot,Side``; JLCPCB wants
    ``Designator,Mid X,Mid Y,Layer,Rotation``. Side ``top``/``bottom`` maps to
    ``Top``/``Bottom``. Coordinates and rotation pass through unchanged (they are
    already board-relative in millimetres when exported with ``--units mm``).
    """
    reader = csv.DictReader(io.StringIO(pos_csv))
    rows: list[JLCPCBCPLRow] = []
    for record in reader:
        rows.append(
            JLCPCBCPLRow(
                designator=record["Ref"],
                mid_x_mm=float(record["PosX"]),
                mid_y_mm=float(record["PosY"]),
                layer=record["Side"].strip().capitalize(),
                rotation_deg=float(record["Rot"]),
            )
        )
    return tuple(rows)


def write_jlcpcb_cpl_csv(rows: tuple[JLCPCBCPLRow, ...], path: Path) -> Path:
    """Write a JLCPCB-format CPL CSV. Returns the path written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(JLCPCB_CPL_HEADER)
    for row in rows:
        writer.writerow([
            row.designator,
            f"{row.mid_x_mm:.4f}",
            f"{row.mid_y_mm:.4f}",
            row.layer,
            f"{row.rotation_deg:.4f}",
        ])

    with open(path, "w", newline="") as handle:
        handle.write(buffer.getvalue())
    return path
