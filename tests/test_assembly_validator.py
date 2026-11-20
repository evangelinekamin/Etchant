"""Tests for JLCPCB assembly-readiness validation."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from etchant.core.assembly_validator import (
    AssemblyValidationReport,
    validate_jlcpcb_assembly,
)
from etchant.core.component_selector import set_parts_db
from etchant.core.models import (
    CircuitSpec,
    ComponentCategory,
    ComponentSpec,
    DesignResult,
)
from etchant.data.jlcparts_adapter import JLCPartsAdapter


@pytest.fixture(autouse=True)
def static_parts_db() -> Iterator[None]:
    """Keep these tests independent from any live DB fixture state."""
    set_parts_db(None)
    yield
    set_parts_db(None)


def _spec() -> CircuitSpec:
    return CircuitSpec(
        name="assembly_test",
        topology="test",
        input_voltage=5.0,
        output_voltage=3.3,
        output_current=0.1,
        description="Assembly validator test",
    )


def _design(*components: ComponentSpec) -> DesignResult:
    return DesignResult(
        spec=_spec(),
        components=components,
        nets=(),
        placement_constraints=(),
        design_notes=(),
    )


def _component(
    *,
    reference: str = "R1",
    category: ComponentCategory = ComponentCategory.RESISTOR,
    value: str = "10k",
    footprint: str = "Resistor_SMD:R_0805_2012Metric",
    jlcpcb_part_number: str | None = None,
    do_not_populate: bool = False,
) -> ComponentSpec:
    kwargs: dict[str, object] = dict(
        reference=reference,
        category=category,
        value=value,
        footprint=footprint,
        kicad_library="Device",
        kicad_symbol="R",
        description="Test component",
        jlcpcb_part_number=jlcpcb_part_number,
    )
    if do_not_populate:
        # Policy (b): parts explicitly marked do-not-populate (hand-solder) are
        # exempt from the JLC-orderable requirement but must still be surfaced.
        kwargs["do_not_populate"] = True
    return ComponentSpec(**kwargs)


def _rules(report: AssemblyValidationReport) -> set[str]:
    return {issue.rule for check in report.checks for issue in check.issues}


class TestValidateJLCPCBAssembly:
    def test_basic_0805_part_is_ready(self) -> None:
        report = validate_jlcpcb_assembly(_design(_component()))

        assert report.assembly_ready is True
        assert report.basic_components == 1
        assert report.extended_components == 0
        assert report.error_count == 0
        assert report.warning_count == 0

    def test_missing_non_connector_part_is_error(self) -> None:
        report = validate_jlcpcb_assembly(_design(_component(
            category=ComponentCategory.IC,
            value="NOT_A_REAL_PART",
            footprint="Package_TO_SOT_SMD:SOT-23",
        )))

        assert report.assembly_ready is False
        assert report.unknown_components == 1
        assert report.error_count == 1
        assert "jlcpcb_part_missing" in _rules(report)

    def test_board_with_unsourced_non_dnp_connector_is_not_ready(self) -> None:
        # Policy (b) honesty fix -- the owner's false-confidence case. The SMD
        # part resolves, but an unsourced connector that is NOT marked
        # do-not-populate must make the board honestly NOT assembly-ready.
        # (Today the CONNECTOR category is silently downgraded to a WARNING.)
        report = validate_jlcpcb_assembly(_design(
            _component(reference="R1"),  # 10k 0805 -> resolves
            _component(
                reference="J1",
                category=ComponentCategory.CONNECTOR,
                value="Conn_01x02",
                footprint="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
            ),
        ))

        assert report.assembly_ready is False
        assert report.error_count >= 1
        assert report.matched_components >= 1  # R1 was fine; the connector blocks

    def test_dnp_connector_is_allowed_but_surfaced(self) -> None:
        # A connector explicitly marked do-not-populate (hand-solder) must not
        # block assembly, but must still be surfaced -- not silently ignored.
        report = validate_jlcpcb_assembly(_design(_component(
            reference="J1",
            category=ComponentCategory.CONNECTOR,
            value="Conn_01x02",
            footprint="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
            do_not_populate=True,
        )))

        j1 = next(check for check in report.checks if check.reference == "J1")
        assert report.assembly_ready is True
        assert j1.has_error is False   # do-not-populate -> not blocking
        assert j1.issues               # ...but still surfaced, not silently dropped

    def test_dnp_through_hole_connector_is_ready_and_flagged(self) -> None:
        report = validate_jlcpcb_assembly(_design(_component(
            reference="J1",
            category=ComponentCategory.CONNECTOR,
            value="Conn_01x02",
            footprint="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
            do_not_populate=True,
        )))

        assert report.assembly_ready is True
        assert report.error_count == 0
        assert "through_hole_manual_assembly" in _rules(report)

    def test_dnp_smd_connector_is_ready(self) -> None:
        report = validate_jlcpcb_assembly(_design(_component(
            reference="J1",
            category=ComponentCategory.CONNECTOR,
            value="Conn_01x02",
            footprint=(
                "Connector_PinHeader_2.54mm:"
                "PinHeader_1x02_P2.54mm_Vertical_SMD_Pin1Left"
            ),
            do_not_populate=True,
        )))

        assert report.assembly_ready is True
        assert "through_hole_manual_assembly" not in _rules(report)

    def test_footprint_package_mismatch_is_error(self) -> None:
        report = validate_jlcpcb_assembly(_design(_component(
            category=ComponentCategory.IC,
            value="AMS1117-3.3",
            footprint="Package_TO_SOT_SMD:SOT-563",
        )))

        assert report.assembly_ready is False
        assert report.error_count == 1
        assert "footprint_package_mismatch" in _rules(report)

    def test_prefer_basic_flags_extended_parts(self) -> None:
        report = validate_jlcpcb_assembly(
            _design(_component(
                category=ComponentCategory.IC,
                value="LM2596S-5",
                footprint="Package_TO_SOT_SMD:TO-263-5_TabPin3",
            )),
            prefer_basic=True,
        )

        assert report.assembly_ready is True
        assert report.extended_components == 1
        assert report.warning_count == 1
        assert "extended_part_setup_fee" in _rules(report)

    def test_lcsc_part_number_overrides_value_lookup(self) -> None:
        report = validate_jlcpcb_assembly(_design(_component(
            value="CUSTOM_10K_ALIAS",
            footprint="Resistor_SMD:R_0805_2012Metric",
            jlcpcb_part_number="C17414",
        )))

        assert report.assembly_ready is True
        assert report.matched_components == 1
        assert report.basic_components == 1
        assert report.checks[0].lcsc_part == "C17414"

    def test_powerpak_so8l_package_matches_kicad_footprint(
        self,
        tmp_path: Path,
    ) -> None:
        db_path = tmp_path / "parts.db"
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE parts (
                lcsc_part TEXT PRIMARY KEY,
                mfr_part TEXT,
                package TEXT,
                description TEXT,
                classification TEXT,
                stock INTEGER,
                category TEXT,
                subcategory TEXT,
                price_usd REAL
            )
        """)
        conn.execute(
            "INSERT INTO parts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "CPOWER",
                "SQJA36EP-T1_GE3",
                "PowerPAK-SO-8L",
                "40V N-Channel PowerPAK-SO-8L MOSFET",
                "extended",
                3000,
                "Power Management ICs",
                "MOSFETs",
                None,
            ),
        )
        conn.commit()
        conn.close()

        db = JLCPartsAdapter(db_path)
        try:
            set_parts_db(db)
            report = validate_jlcpcb_assembly(_design(_component(
                reference="Q1",
                category=ComponentCategory.IC,
                value="SQJA36EP-T1_GE3",
                footprint="Package_SO:PowerPAK_SO-8L_Single",
                jlcpcb_part_number="CPOWER",
            )))
        finally:
            db.close()

        assert report.error_count == 0
        assert "footprint_package_mismatch" not in _rules(report)
