"""Component selector with JLCPCB-first part matching.

Maps component values to JLCPCB parts, prioritizing basic parts (no setup fee)
over extended parts ($3 per unique part). Also provides design rule lookups
from the constraints YAML.

Week 1: Static lookup table for LM2596 reference design parts.
Week 2+: Wire up to JLCPCB parts database API via mixelpixx MCP server.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class PartClassification(Enum):
    BASIC = "basic"
    EXTENDED = "extended"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class JLCPCBPartInfo:
    """JLCPCB part metadata for cost optimization."""

    part_number: str
    classification: PartClassification
    description: str
    stock: int
    mfr_part: str | None = None
    package: str | None = None
    category: str | None = None
    subcategory: str | None = None

    @property
    def setup_fee_usd(self) -> float:
        if self.classification == PartClassification.BASIC:
            return 0.0
        return 3.0


# Static lookup table for Week 1 — known parts for the LM2596 reference design.
# Week 2+ replaces this with live JLCPCB API queries.
_KNOWN_PARTS: dict[str, JLCPCBPartInfo] = {
    "LM2596S-5": JLCPCBPartInfo(
        part_number="C2837",
        classification=PartClassification.EXTENDED,
        description="LM2596S-5.0 TO-263 step-down regulator",
        stock=5000,
        package="TO-263",
        category="Power Management ICs",
    ),
    "680uF": JLCPCBPartInfo(
        part_number="C296751",
        classification=PartClassification.EXTENDED,
        description="680uF 25V electrolytic capacitor",
        stock=10000,
        category="Capacitors",
    ),
    "220uF": JLCPCBPartInfo(
        part_number="C120318",
        classification=PartClassification.EXTENDED,
        description="220uF 10V electrolytic capacitor",
        stock=15000,
        category="Capacitors",
    ),
    "33uH": JLCPCBPartInfo(
        part_number="C339984",
        classification=PartClassification.EXTENDED,
        description="33uH power inductor",
        stock=8000,
        category="Inductors/Coils/Transformers",
    ),
    "1N5822": JLCPCBPartInfo(
        part_number="C35722",
        classification=PartClassification.BASIC,
        description="1N5822 Schottky diode 40V 5A DO-201AD",
        stock=50000,
        package="DO-201AD",
        category="Diodes",
    ),
    "10k": JLCPCBPartInfo(
        part_number="C17414",
        classification=PartClassification.BASIC,
        description="10k 0805 1% resistor",
        stock=500000,
        package="0805",
        category="Resistors",
    ),
    "AMS1117-3.3": JLCPCBPartInfo(
        part_number="C6186",
        classification=PartClassification.BASIC,
        description="AMS1117-3.3 SOT-223 3.3V 1A LDO",
        stock=200000,
        package="SOT-223",
        category="Power Management ICs",
    ),
    "MCP6001UT-I/OT": JLCPCBPartInfo(
        part_number="C21403",
        classification=PartClassification.EXTENDED,
        description=(
            "MCP6001UT-I/OT 1MHz rail-to-rail input/output op-amp SOT-23-5"
        ),
        stock=5338,
        package="SOT-23-5",
        category="Amplifiers/Comparators",
        subcategory="Operational Amplifier",
    ),
    "ESP32-C3-WROOM-02": JLCPCBPartInfo(
        part_number="C2934560",
        classification=PartClassification.EXTENDED,
        description=(
            "ESP32-C3-WROOM-02-N4 WiFi/BLE module with PCB antenna"
        ),
        stock=18840,
        package="VFQFN-32-EP",
        category="IoT/Communication Modules",
        subcategory="WiFi Modules",
    ),
    "ESP32-C3-WROOM-02-N4": JLCPCBPartInfo(
        part_number="C2934560",
        classification=PartClassification.EXTENDED,
        description=(
            "ESP32-C3-WROOM-02-N4 WiFi/BLE module with PCB antenna"
        ),
        stock=18840,
        package="VFQFN-32-EP",
        category="IoT/Communication Modules",
        subcategory="WiFi Modules",
    ),
    "KT-0805G": JLCPCBPartInfo(
        part_number="C2297",
        classification=PartClassification.BASIC,
        description="KT-0805G emerald green 0805 LED indication diode",
        stock=1_731_350,
        package="0805",
        category="Optoelectronics",
        subcategory="LED Indication - Discrete",
    ),
    "100nF_0603": JLCPCBPartInfo(
        part_number="C14663",
        classification=PartClassification.BASIC,
        description="100nF 50V X7R 0603 ceramic capacitor",
        stock=33_259_009,
        package="0603",
        category="Capacitors",
        subcategory="Multilayer Ceramic Capacitors MLCC - SMD/SMT",
    ),
    "10k_0603": JLCPCBPartInfo(
        part_number="C25804",
        classification=PartClassification.BASIC,
        description="10k 0603 1% resistor",
        stock=25_411_718,
        package="0603",
        category="Resistors",
        subcategory="Chip Resistor - Surface Mount",
    ),
    "1k_0603": JLCPCBPartInfo(
        part_number="C21190",
        classification=PartClassification.BASIC,
        description="1k 0603 1% resistor",
        stock=34_305_467,
        package="0603",
        category="Resistors",
        subcategory="Chip Resistor - Surface Mount",
    ),
    "DRV8837DSGR": JLCPCBPartInfo(
        part_number="C39159",
        classification=PartClassification.EXTENDED,
        description=(
            "DRV8837DSGR 1.8A brushed DC motor driver WSON-8-EP(2x2)"
        ),
        stock=56_457,
        package="WSON-8-EP(2x2)",
        category="Power Management ICs",
        subcategory="Motor Driver ICs",
    ),
    "TPS259571DSGR": JLCPCBPartInfo(
        part_number="C471038",
        classification=PartClassification.EXTENDED,
        description=(
            "TPS259571DSGR 2.7V to 18V 4A eFuse WSON-8-EP(2x2)"
        ),
        stock=464,
        mfr_part="TPS259571DSGR",
        package="WSON-8-EP(2x2)",
        category="Power Management ICs",
        subcategory="Monitors & Reset Circuits",
    ),
    "SMF5.0CA": JLCPCBPartInfo(
        part_number="C4749140",
        classification=PartClassification.EXTENDED,
        description="SMF5.0CA bidirectional 5V TVS diode SOD-123FL",
        stock=17_278,
        mfr_part="SMF5.0CA",
        package="SOD-123FL",
        category="Diodes",
        subcategory="TVS",
    ),
    "5.1k_0603": JLCPCBPartInfo(
        part_number="C23186",
        classification=PartClassification.BASIC,
        description="5.1k 0603 1% resistor",
        stock=2_807_038,
        package="0603",
        category="Resistors",
        subcategory="Chip Resistor - Surface Mount",
    ),
    "680R_0603": JLCPCBPartInfo(
        part_number="C23228",
        classification=PartClassification.BASIC,
        description="680R 0603 1% resistor",
        stock=761_783,
        package="0603",
        category="Resistors",
        subcategory="Chip Resistor - Surface Mount",
    ),
    "3.3nF_0603": JLCPCBPartInfo(
        part_number="C1613",
        classification=PartClassification.BASIC,
        description="3.3nF 50V X7R 0603 ceramic capacitor",
        stock=330_219,
        package="0603",
        category="Capacitors",
        subcategory="Multilayer Ceramic Capacitors MLCC - SMD/SMT",
    ),
    "10uF": JLCPCBPartInfo(
        part_number="C15850",
        classification=PartClassification.BASIC,
        description="10uF 16V 0805 X5R ceramic capacitor",
        stock=300000,
        package="0805",
        category="Capacitors",
    ),
    "22uF": JLCPCBPartInfo(
        part_number="C45783",
        classification=PartClassification.BASIC,
        description="22uF 10V 0805 X5R ceramic capacitor",
        stock=250000,
        package="0805",
        category="Capacitors",
    ),
}


_db_instance: object | None = None
_DEFAULT_PARTS_DB = Path(__file__).resolve().parents[2] / "data" / "jlcpcb_power_parts.db"


def set_parts_db(db: object | None) -> None:
    """Set the JLCPCB parts database instance for live lookups.

    Call this at startup with a JLCPCBPartsDB instance to use real data
    instead of the static lookup table.
    """
    global _db_instance  # noqa: PLW0603
    _db_instance = db


def connect_default_parts_db(db_path: Path | None = None) -> bool:
    """Connect the bundled JLCPCB parts DB when it is available."""
    if _db_instance is not None:
        return True

    path = db_path or _DEFAULT_PARTS_DB
    if not path.exists():
        return False

    from etchant.data.jlcparts_adapter import JLCPartsAdapter

    set_parts_db(JLCPartsAdapter(path))
    return True


def lookup_jlcpcb_part_by_lcsc(lcsc_part: str) -> JLCPCBPartInfo | None:
    """Look up a JLCPCB part by LCSC part number, e.g. ``C17414``."""
    if _db_instance is not None:
        if hasattr(_db_instance, "get_by_lcsc_string"):
            result = _db_instance.get_by_lcsc_string(lcsc_part)
            if result:
                return result
        elif hasattr(_db_instance, "get_by_lcsc"):
            result = _db_instance.get_by_lcsc(lcsc_part)
            if result:
                return result.to_part_info()

    for info in _KNOWN_PARTS.values():
        if info.part_number == lcsc_part:
            return info
    return None


def lookup_jlcpcb_part(
    value: str,
    constraints_dir: Path | None = None,
) -> JLCPCBPartInfo | None:
    """Look up a JLCPCB part by component value.

    Curated exact matches are preferred over broad database searches, because
    values like "10k" and "10uF" can match many package/voltage variants in the
    local catalog. The database fills gaps for ICs and other non-curated parts.
    """
    known = _lookup_known_part(value)
    if known is not None:
        return known

    inferred_category = _infer_value_category(value)
    if inferred_category is not None:
        candidates = find_jlcpcb_part_candidates(
            value,
            category=inferred_category,
            min_stock=1,
            limit=1,
        )
        return candidates[0] if candidates else None

    if _db_instance is not None:
        # Avoid circular imports — check by method presence, not isinstance
        if hasattr(_db_instance, "search_by_value"):
            results = _db_instance.search_by_value(value, min_stock=1)
            if results:
                return results[0].to_part_info()
        elif hasattr(_db_instance, "search"):
            results = _db_instance.search(value, min_stock=1, limit=1)
            if results:
                return results[0]

    return None


def find_jlcpcb_part_candidates(
    value: str,
    *,
    category: str | None = None,
    package: str | None = None,
    basic_only: bool = False,
    min_stock: int = 1,
    limit: int = 10,
) -> tuple[JLCPCBPartInfo, ...]:
    """Find assembly candidates for a component value and optional package."""
    candidates: list[JLCPCBPartInfo] = []

    known = _lookup_known_part(value)
    if known is not None and _candidate_matches(
        known,
        category=category,
        package=package,
        basic_only=basic_only,
        min_stock=min_stock,
    ):
        candidates.append(known)

    if _db_instance is not None:
        if hasattr(_db_instance, "search_assembly_candidates"):
            results = _db_instance.search_assembly_candidates(
                value,
                category=category,
                package=package,
                basic_only=basic_only,
                min_stock=min_stock,
                limit=limit,
            )
            candidates.extend(results)
        elif hasattr(_db_instance, "search_by_value"):
            results = _db_instance.search_by_value(
                value,
                category=category,
                basic_only=basic_only,
                min_stock=min_stock,
            )
            candidates.extend(r.to_part_info() for r in results[:limit])
        elif hasattr(_db_instance, "search"):
            results = _db_instance.search(
                value,
                basic_only=basic_only,
                min_stock=min_stock,
                limit=limit,
            )
            candidates.extend(results)

    return _dedupe_candidates(candidates, limit=limit)


def _lookup_known_part(value: str) -> JLCPCBPartInfo | None:
    candidates = (value, _canonical_component_value(value))
    for candidate in candidates:
        if candidate in _KNOWN_PARTS:
            return _KNOWN_PARTS[candidate]
    return None


def _canonical_component_value(value: str) -> str:
    text = value.strip().replace(" ", "")
    text = re.sub(r"(?<=\d)\.0+(?=[A-Za-z])", "", text)

    match = re.fullmatch(r"([0-9.]+)([A-Za-z]+)", text)
    if match is None:
        return text

    magnitude, unit = match.groups()
    unit_aliases = {
        "K": "k",
        "k": "k",
        "M": "M",
        "PF": "pF",
        "pf": "pF",
        "pF": "pF",
        "NF": "nF",
        "nf": "nF",
        "nF": "nF",
        "UF": "uF",
        "uf": "uF",
        "uF": "uF",
        "UH": "uH",
        "uh": "uH",
        "uH": "uH",
    }
    return f"{magnitude}{unit_aliases.get(unit, unit)}"


def _candidate_matches(
    candidate: JLCPCBPartInfo,
    *,
    category: str | None,
    package: str | None,
    basic_only: bool,
    min_stock: int,
) -> bool:
    if candidate.stock < min_stock:
        return False
    if basic_only and candidate.classification != PartClassification.BASIC:
        return False
    if category and not _part_text_matches(candidate, category):
        return False
    return not package or _part_package_matches(candidate, package)


def _part_text_matches(candidate: JLCPCBPartInfo, needle: str) -> bool:
    haystack = " ".join(
        value
        for value in (
            candidate.category,
            candidate.subcategory,
            candidate.description,
        )
        if value
    )
    return needle.lower() in haystack.lower()


def _part_package_matches(candidate: JLCPCBPartInfo, package: str) -> bool:
    text = " ".join(
        value
        for value in (
            candidate.package,
            candidate.description,
            candidate.mfr_part,
        )
        if value
    )
    return _normalized_text(package) in _normalized_text(text)


def _infer_value_category(value: str) -> str | None:
    text = _canonical_component_value(value).strip()
    if re.fullmatch(r"[0-9.]+(?:R|k|M|Ω|kΩ|KΩ|MΩ)", text):
        return "Resistor"
    if re.fullmatch(r"[0-9.]+(?:pF|nF|uF)", text):
        return "Capacitor"
    if re.fullmatch(r"[0-9.]+(?:nH|uH|mH)", text):
        return "Inductor"
    return None


def _normalized_text(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", value.upper())


def _dedupe_candidates(
    candidates: list[JLCPCBPartInfo],
    *,
    limit: int,
) -> tuple[JLCPCBPartInfo, ...]:
    seen: set[str] = set()
    unique: list[JLCPCBPartInfo] = []
    for candidate in candidates:
        if candidate.part_number in seen:
            continue
        seen.add(candidate.part_number)
        unique.append(candidate)
        if len(unique) >= limit:
            break
    return tuple(unique)


def find_trace_width(
    current_a: float,
    constraints_dir: Path,
) -> dict[str, Any] | None:
    """Find the appropriate trace width rule for a given current.

    Reads from design_rules.yaml and returns the matching rule dict,
    or the highest rule if current exceeds all entries.
    """
    rules_path = constraints_dir / "design_rules.yaml"
    if not rules_path.exists():
        return None

    with open(rules_path) as f:
        rules = yaml.safe_load(f)

    trace_rules = rules.get("trace_width", [])
    if not trace_rules:
        return None

    for rule in trace_rules:
        if rule["current_a"] >= current_a:
            return dict(rule)

    # Current exceeds all rules — return the highest
    return dict(trace_rules[-1])
