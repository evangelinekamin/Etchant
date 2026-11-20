"""Tests for automatic JLCPCB part optimization."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from etchant.core.bom import BOMGenerator, CostBreakdown
from etchant.core.component_selector import PartClassification, set_parts_db
from etchant.core.models import (
    CircuitSpec,
    ComponentCategory,
    ComponentSpec,
    DesignResult,
)
from etchant.core.part_optimizer import optimize_jlcpcb_assembly
from etchant.data.jlcparts_adapter import JLCPartsAdapter


@pytest.fixture(autouse=True)
def isolated_parts_db() -> Iterator[None]:
    set_parts_db(None)
    yield
    set_parts_db(None)


@pytest.fixture
def parts_db(tmp_path: Path) -> Iterator[JLCPartsAdapter]:
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
    rows = [
        (
            "C100R07",
            "100R07X105KV4T",
            "0402",
            "10V 1uF X5R 0402 Multilayer Ceramic Capacitor",
            "extended",
            5000000,
            "Capacitors",
            "Multilayer Ceramic Capacitors MLCC - SMD/SMT",
            None,
        ),
        (
            "C100R",
            "0603WAF1000T5E",
            "0603",
            "-55C~+155C 100mW 100Ω 75V Thick Film Resistor ±1% 0603 Chip Resistor",
            "basic",
            100000,
            "Resistors",
            "Chip Resistor - Surface Mount",
            None,
        ),
        (
            "C17737",
            "0805W8F5102T5E",
            "0805",
            "-55C~+155C 125mW 150V 51kΩ 0805 Chip Resistor ROHS",
            "basic",
            877908,
            "Resistors",
            "Chip Resistor - Surface Mount",
            None,
        ),
        (
            "C167219",
            "FXL0630-3R3-M",
            "SMD,7x6.6mm",
            "22mΩ 3.3uH 8.5A 9.5A Molded Inductor ±20%",
            "extended",
            106717,
            "Inductors/Coils/Transformers",
            "Power Inductors",
            None,
        ),
        (
            "C97253",
            "TPS563200DDCR",
            "TSOT-23-6",
            "TPS563200 Adjustable Buck TSOT-23-6 DC-DC Converters ROHS",
            "extended",
            38,
            "Power Management ICs",
            "DC-DC Converters",
            None,
        ),
    ]
    conn.executemany("INSERT INTO parts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()

    db = JLCPartsAdapter(db_path)
    set_parts_db(db)
    try:
        yield db
    finally:
        db.close()


def _spec() -> CircuitSpec:
    return CircuitSpec(
        name="optimizer_test",
        topology="buck_converter",
        input_voltage=12.0,
        output_voltage=5.0,
        output_current=2.0,
        description="Optimizer test",
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
    reference: str,
    category: ComponentCategory,
    value: str,
    footprint: str,
    *,
    jlcpcb_part_number: str | None = None,
    properties: dict[str, str] | None = None,
) -> ComponentSpec:
    return ComponentSpec(
        reference=reference,
        category=category,
        value=value,
        footprint=footprint,
        kicad_library="Device",
        kicad_symbol=value,
        description="Test component",
        properties=properties or {},
        jlcpcb_part_number=jlcpcb_part_number,
    )


class TestOptimizeJLCPCBAssembly:
    def test_selects_basic_resistor_candidate(
        self,
        parts_db: JLCPartsAdapter,
    ) -> None:
        design = _design(_component(
            "R1",
            ComponentCategory.RESISTOR,
            "51.0k",
            "Resistor_SMD:R_0805_2012Metric",
        ))

        result = optimize_jlcpcb_assembly(design, prefer_basic=True)

        assert result.after.assembly_ready is True
        assert result.substitutions[0].new_lcsc_part == "C17737"
        assert result.substitutions[0].classification == PartClassification.BASIC
        optimized = result.optimized_design.components[0]
        assert optimized.jlcpcb_part_number == "C17737"
        assert optimized.properties["jlcpcb_package"] == "0805"

    def test_resistor_r_suffix_does_not_resolve_to_capacitor_mfr(
        self,
        parts_db: JLCPartsAdapter,
    ) -> None:
        design = _design(_component(
            "R1",
            ComponentCategory.RESISTOR,
            "100R",
            "Resistor_SMD:R_0603_1608Metric",
        ))

        result = optimize_jlcpcb_assembly(design, prefer_basic=True)

        assert result.after.assembly_ready is True
        assert result.optimized_design.components[0].jlcpcb_part_number == "C100R"
        assert result.substitutions[0].new_lcsc_part == "C100R"

    def test_selects_stocked_inductor_when_no_basic_exists(
        self,
        parts_db: JLCPartsAdapter,
    ) -> None:
        design = _design(_component(
            "L1",
            ComponentCategory.INDUCTOR,
            "3.3uH",
            "Inductor_SMD:L_Vishay_IHLP-2525",
            properties={"saturation_current": "2.6A"},
        ))

        result = optimize_jlcpcb_assembly(design, prefer_basic=True)

        assert result.after.assembly_ready is True
        assert result.substitutions[0].new_lcsc_part == "C167219"
        assert result.substitutions[0].classification == PartClassification.EXTENDED

    def test_does_not_record_noop_extended_replacement(
        self,
        parts_db: JLCPartsAdapter,
    ) -> None:
        design = _design(_component(
            "D1",
            ComponentCategory.DIODE,
            "SMF5.0CA",
            "Diode_SMD:D_SOD-123FL",
            jlcpcb_part_number="C4749140",
        ))

        result = optimize_jlcpcb_assembly(design, prefer_basic=True)

        assert result.after.assembly_ready is True
        assert result.substitutions == ()

    def test_corrects_known_ic_footprint_from_selected_package(
        self,
        parts_db: JLCPartsAdapter,
    ) -> None:
        design = _design(_component(
            "U1",
            ComponentCategory.IC,
            "TPS563200",
            "Package_TO_SOT_SMD:SOT-563",
            jlcpcb_part_number="C97253",
        ))

        result = optimize_jlcpcb_assembly(design, prefer_basic=True)

        optimized = result.optimized_design.components[0]
        assert optimized.footprint == "Package_TO_SOT_SMD:SOT-23-6"
        assert result.after.error_count == 0
        assert result.substitutions[0].action == "correct_footprint"

    def test_bom_uses_substituted_lcsc_part(self, parts_db: JLCPartsAdapter) -> None:
        design = _design(_component(
            "L1",
            ComponentCategory.INDUCTOR,
            "3.3uH",
            "Inductor_SMD:L_Vishay_IHLP-2525",
            properties={"saturation_current": "2.6A"},
        ))
        optimized = optimize_jlcpcb_assembly(design).optimized_design

        bom = BOMGenerator().generate(optimized)
        cost = CostBreakdown.from_bom(bom)

        assert bom[0].jlcpcb_part_number == "C167219"
        assert bom[0].classification == PartClassification.EXTENDED
        assert cost.total_setup_fee_usd == 3.0

    def test_converts_two_pin_header_to_smd_footprint(self) -> None:
        design = _design(_component(
            "J1",
            ComponentCategory.CONNECTOR,
            "Conn_01x02",
            "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
        ))

        result = optimize_jlcpcb_assembly(design)

        optimized = result.optimized_design.components[0]
        assert optimized.footprint == (
            "Connector_PinHeader_2.54mm:"
            "PinHeader_1x02_P2.54mm_Vertical_SMD_Pin1Left"
        )
        assert optimized.properties["assembly_mount"] == "smd"
        assert result.substitutions[0].action == "convert_connector_to_smd"
        assert "through_hole_manual_assembly" not in {
            issue.rule for check in result.after.checks for issue in check.issues
        }

    def test_converts_three_pin_header_to_smd_footprint(self) -> None:
        design = _design(_component(
            "J1",
            ComponentCategory.CONNECTOR,
            "Conn_01x03",
            "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical",
        ))

        result = optimize_jlcpcb_assembly(design)

        optimized = result.optimized_design.components[0]
        assert optimized.footprint == (
            "Connector_PinHeader_2.54mm:"
            "PinHeader_1x03_P2.54mm_Vertical_SMD_Pin1Left"
        )
