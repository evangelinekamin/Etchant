"""Tests for the jlcparts database adapter.

Tests against the extracted power parts DB (60 MB, 237K parts).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from etchant.core.component_selector import PartClassification

_REPO_ROOT = Path(__file__).resolve().parents[1]
_JLCPARTS_DB = Path(
    os.environ.get(
        "ETCHANT_JLCPARTS_DB",
        str(_REPO_ROOT / "data" / "jlcpcb_power_parts.db"),
    )
)
_has_db = _JLCPARTS_DB.exists()

requires_jlcparts = pytest.mark.skipif(
    not _has_db,
    reason="JLCPCB power parts database not available",
)


@requires_jlcparts
class TestJLCPartsAdapter:
    @pytest.fixture
    def adapter(self):  # type: ignore[no-untyped-def]
        from etchant.data.jlcparts_adapter import JLCPartsAdapter

        db = JLCPartsAdapter(_JLCPARTS_DB)
        yield db
        db.close()

    def test_search_ams1117(self, adapter) -> None:  # type: ignore[no-untyped-def]
        results = adapter.search("AMS1117-3.3", limit=5)
        assert len(results) > 0
        assert any(r.classification == PartClassification.BASIC for r in results)

    def test_search_lm2596(self, adapter) -> None:  # type: ignore[no-untyped-def]
        results = adapter.search("LM2596", limit=5)
        assert len(results) > 0

    def test_search_basic_only(self, adapter) -> None:  # type: ignore[no-untyped-def]
        results = adapter.search("AMS1117", basic_only=True, limit=5)
        assert all(r.classification == PartClassification.BASIC for r in results)

    def test_get_by_lcsc_string(self, adapter) -> None:  # type: ignore[no-untyped-def]
        result = adapter.get_by_lcsc_string("C6186")
        assert result is not None
        assert result.part_number == "C6186"
        assert result.classification == PartClassification.BASIC

    def test_nonexistent_part(self, adapter) -> None:  # type: ignore[no-untyped-def]
        result = adapter.get_by_lcsc_string("C999999999")
        assert result is None

    def test_part_has_stock(self, adapter) -> None:  # type: ignore[no-untyped-def]
        results = adapter.search("AMS1117", min_stock=100, limit=3)
        assert all(r.stock >= 100 for r in results)

    def test_search_100r_resistor_uses_ohm_value_not_capacitor_mfr(
        self,
        adapter,
    ) -> None:  # type: ignore[no-untyped-def]
        results = adapter.search_assembly_candidates(
            "100R",
            category="Resistor",
            package="0603",
            basic_only=True,
            min_stock=1,
            limit=5,
        )

        assert results
        assert results[0].category == "Resistors"
        assert results[0].package == "0603"
        assert "100Ω" in results[0].description

    def test_search_10k_resistor_prefers_exact_value_matches(
        self,
        adapter,
    ) -> None:  # type: ignore[no-untyped-def]
        results = adapter.search_assembly_candidates(
            "10k",
            category="Resistor",
            package="0603",
            basic_only=True,
            min_stock=1,
            limit=5,
        )

        assert results
        assert all("10kΩ" in result.description for result in results)
        assert not any("510kΩ" in result.description for result in results)

    def test_count_total(self, adapter) -> None:  # type: ignore[no-untyped-def]
        count = adapter.count_total()
        assert count > 200000
