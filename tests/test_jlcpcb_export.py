"""Tests for JLCPCB upload-format BOM and CPL export.

These cover the two artifacts that turn a generated design into something a
non-expert can actually upload to JLCPCB and order: a BOM grouped by unique
part with JLCPCB's column names, and a CPL/pick-and-place reformatted from
KiCad's position export.
"""

from __future__ import annotations

import csv
import io
from unittest.mock import patch

from etchant.circuits.generative_ldo import GenerativeLDORegulator
from etchant.core.bom import BOMEntry, BOMGenerator
from etchant.core.component_selector import PartClassification
from etchant.core.jlcpcb_export import (
    JLCPCBBOMRow,
    aggregate_jlcpcb_bom,
    cpl_rows_from_kicad_pos,
    write_jlcpcb_bom_csv,
    write_jlcpcb_cpl_csv,
)
from etchant.core.models import CircuitSpec


def _entry(reference: str, value: str, footprint: str, lcsc: str | None) -> BOMEntry:
    return BOMEntry(
        reference=reference,
        value=value,
        footprint=footprint,
        description="",
        quantity=1,
        jlcpcb_part_number=lcsc,
        classification=PartClassification.BASIC if lcsc else PartClassification.UNKNOWN,
        unit_price_usd=None,
    )


class TestAggregateBOM:
    def test_identical_parts_collapse_to_one_row(self) -> None:
        bom = (
            _entry("C1", "10uF", "Capacitor_SMD:C_0805_2012Metric", "C15850"),
            _entry("C2", "10uF", "Capacitor_SMD:C_0805_2012Metric", "C15850"),
        )
        rows = aggregate_jlcpcb_bom(bom)
        assert len(rows) == 1
        assert rows[0].designators == ("C1", "C2")
        assert rows[0].comment == "10uF"
        assert rows[0].lcsc_part == "C15850"

    def test_distinct_parts_stay_separate(self) -> None:
        bom = (
            _entry("C1", "10uF", "Capacitor_SMD:C_0805_2012Metric", "C15850"),
            _entry("C2", "22uF", "Capacitor_SMD:C_0805_2012Metric", "C45783"),
        )
        rows = aggregate_jlcpcb_bom(bom)
        assert len(rows) == 2

    def test_footprint_is_cleaned_of_library_prefix(self) -> None:
        bom = (_entry("U1", "AMS1117-3.3", "Package_TO_SOT_SMD:SOT-223-3_TabPin2", "C6186"),)
        rows = aggregate_jlcpcb_bom(bom)
        assert rows[0].footprint == "SOT-223-3_TabPin2"

    def test_designators_sorted_naturally(self) -> None:
        fp = "Capacitor_SMD:C_0805_2012Metric"
        bom = (
            _entry("C10", "10uF", fp, "C15850"),
            _entry("C2", "10uF", fp, "C15850"),
        )
        rows = aggregate_jlcpcb_bom(bom)
        assert rows[0].designators == ("C2", "C10")

    def test_part_without_lcsc_keeps_none(self) -> None:
        bom = (_entry("J1", "Conn_01x02", "Connector:PinHeader", None),)
        rows = aggregate_jlcpcb_bom(bom)
        assert rows[0].lcsc_part is None


class TestWriteBOMCSV:
    def test_header_and_joined_designators(self, tmp_path) -> None:
        rows = (
            JLCPCBBOMRow(
                comment="10uF",
                designators=("C1", "C2"),
                footprint="C_0805_2012Metric",
                lcsc_part="C15850",
            ),
            JLCPCBBOMRow(
                comment="Conn_01x02",
                designators=("J1",),
                footprint="PinHeader",
                lcsc_part=None,
            ),
        )
        path = write_jlcpcb_bom_csv(rows, tmp_path / "bom.csv")
        with open(path, newline="") as f:
            parsed = list(csv.reader(f))
        assert parsed[0] == ["Comment", "Designator", "Footprint", "LCSC Part #"]
        assert parsed[1] == ["10uF", "C1,C2", "C_0805_2012Metric", "C15850"]
        assert parsed[2] == ["Conn_01x02", "J1", "PinHeader", ""]


class TestCPLFromKicadPos:
    # KiCad 9 `kicad-cli pcb export pos --format csv --units mm` output.
    SAMPLE_POS = (
        'Ref,Val,Package,PosX,PosY,Rot,Side\n'
        '"C1","10uF","C_0805_2012Metric",10.5000,-20.2500,90.0000,"top"\n'
        '"U1","AMS1117-3.3","SOT-223-3_TabPin2",15.0000,-18.0000,180.0000,"top"\n'
        '"J1","Conn_01x02","PinHeader_1x02",2.0000,-25.0000,0.0000,"bottom"\n'
    )

    def test_remaps_columns_and_side(self) -> None:
        rows = cpl_rows_from_kicad_pos(self.SAMPLE_POS)
        assert len(rows) == 3
        c1 = rows[0]
        assert c1.designator == "C1"
        assert c1.mid_x_mm == 10.5
        assert c1.mid_y_mm == -20.25
        assert c1.rotation_deg == 90.0
        assert c1.layer == "Top"
        assert rows[2].layer == "Bottom"

    def test_cpl_csv_header_and_rows(self, tmp_path) -> None:
        rows = cpl_rows_from_kicad_pos(self.SAMPLE_POS)
        path = write_jlcpcb_cpl_csv(rows, tmp_path / "cpl.csv")
        with open(path, newline="") as f:
            parsed = list(csv.reader(f))
        assert parsed[0] == ["Designator", "Mid X", "Mid Y", "Layer", "Rotation"]
        assert parsed[1][0] == "C1"
        assert parsed[1][3] == "Top"


class TestLDOIntegration:
    @patch("etchant.circuits.generative_ldo.GenerativeLDORegulator._query_webench")
    def test_ldo_bom_aggregates_matching_caps(self, mock_wb: object) -> None:
        mock_wb.return_value = None  # type: ignore[union-attr]
        gen = GenerativeLDORegulator()
        spec = CircuitSpec(
            name="ldo", topology="ldo_regulator",
            input_voltage=5.0, output_voltage=3.3, output_current=0.5,
            description="test",
        )
        design = gen.generate(spec)
        bom = BOMGenerator().generate(design)
        rows = aggregate_jlcpcb_bom(bom)

        # At 0.5A both decoupling caps are 10uF/0805 -> one grouped row.
        cap_rows = [r for r in rows if r.comment == "10uF"]
        assert len(cap_rows) == 1
        assert cap_rows[0].designators == ("C1", "C2")
        # The regulator is present as its own row.
        assert any("AMS1117" in r.comment for r in rows)
