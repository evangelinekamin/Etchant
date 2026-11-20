"""Adapter for JLCPCB parts databases.

Supports two database formats:
1. Our extracted power_parts.db (60 MB, 237K parts, fast)
2. The full jlcparts cache.sqlite3 (12 GB, 7M parts, slow without mmap)

Auto-detects the schema on first connection.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from etchant.core.component_selector import JLCPCBPartInfo, PartClassification


class JLCPartsAdapter:
    """Read-only adapter for JLCPCB parts databases."""

    def __init__(self, db_path: Path) -> None:
        if not db_path.exists():
            raise FileNotFoundError(f"JLCPCB database not found: {db_path}")
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._schema: str | None = None  # "extracted" or "jlcparts"

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            self._detect_schema()
        return self._conn

    def _detect_schema(self) -> None:
        """Detect whether this is our extracted DB or the jlcparts cache."""
        conn = self._conn
        if conn is None:
            return
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t[0] for t in tables}

        if "parts" in table_names:
            self._schema = "extracted"
        elif "components" in table_names:
            self._schema = "jlcparts"
        else:
            raise ValueError(f"Unknown database schema: tables = {table_names}")

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def search(
        self,
        query: str,
        basic_only: bool = False,
        min_stock: int = 0,
        limit: int = 20,
    ) -> list[JLCPCBPartInfo]:
        """Search parts by manufacturer part number."""
        conn = self._get_conn()

        if self._schema == "extracted":
            return self._search_extracted(conn, query, basic_only, min_stock, limit)
        return self._search_jlcparts(conn, query, basic_only, min_stock, limit)

    def search_assembly_candidates(
        self,
        value: str,
        *,
        category: str | None = None,
        package: str | None = None,
        basic_only: bool = False,
        min_stock: int = 0,
        limit: int = 20,
    ) -> list[JLCPCBPartInfo]:
        """Search by electrical value plus optional assembly package/category."""
        conn = self._get_conn()

        if self._schema == "extracted":
            return self._search_extracted_candidates(
                conn,
                value,
                category=category,
                package=package,
                basic_only=basic_only,
                min_stock=min_stock,
                limit=limit,
            )
        return self._search_jlcparts_candidates(
            conn,
            value,
            basic_only=basic_only,
            min_stock=min_stock,
            limit=limit,
        )

    def _search_extracted(
        self,
        conn: sqlite3.Connection,
        query: str,
        basic_only: bool,
        min_stock: int,
        limit: int,
    ) -> list[JLCPCBPartInfo]:
        sql = "SELECT * FROM parts WHERE mfr_part LIKE ?"
        params: list[Any] = [f"{query}%"]

        if basic_only:
            sql += " AND classification = 'basic'"
        if min_stock > 0:
            sql += " AND stock >= ?"
            params.append(min_stock)

        sql += " ORDER BY classification ASC, stock DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [
            JLCPCBPartInfo(
                part_number=r["lcsc_part"],
                classification=(
                    PartClassification.BASIC
                    if r["classification"] == "basic"
                    else PartClassification.EXTENDED
                ),
                description=r["description"] or "",
                stock=r["stock"] or 0,
                mfr_part=r["mfr_part"] or None,
                package=r["package"] or None,
                category=r["category"] or None,
                subcategory=r["subcategory"] or None,
            )
            for r in rows
        ]

    def _search_extracted_candidates(
        self,
        conn: sqlite3.Connection,
        value: str,
        *,
        category: str | None,
        package: str | None,
        basic_only: bool,
        min_stock: int,
        limit: int,
    ) -> list[JLCPCBPartInfo]:
        terms = _value_terms(value)
        if not terms:
            return []

        sql = "SELECT * FROM parts WHERE ("
        clauses: list[str] = []
        params: list[Any] = []
        for term in terms:
            clauses.append("(description LIKE ? OR mfr_part LIKE ?)")
            like = f"%{term}%"
            params.extend((like, like))
        sql += " OR ".join(clauses) + ")"

        if category:
            sql += " AND category LIKE ?"
            params.append(f"%{category}%")
        if package:
            sql += " AND package = ?"
            params.append(package)
        if basic_only:
            sql += " AND classification = 'basic'"
        if min_stock > 0:
            sql += " AND stock >= ?"
            params.append(min_stock)

        sql += " ORDER BY classification ASC, stock DESC LIMIT ?"
        params.append(max(limit * 5, 50))

        rows = conn.execute(sql, params).fetchall()
        candidates = [
            JLCPCBPartInfo(
                part_number=r["lcsc_part"],
                classification=(
                    PartClassification.BASIC
                    if r["classification"] == "basic"
                    else PartClassification.EXTENDED
                ),
                description=r["description"] or "",
                stock=r["stock"] or 0,
                mfr_part=r["mfr_part"] or None,
                package=r["package"] or None,
                category=r["category"] or None,
                subcategory=r["subcategory"] or None,
            )
            for r in rows
        ]
        return _prefer_exact_value_matches(value, candidates)[:limit]

    def _search_jlcparts(
        self,
        conn: sqlite3.Connection,
        query: str,
        basic_only: bool,
        min_stock: int,
        limit: int,
    ) -> list[JLCPCBPartInfo]:
        sql = "SELECT lcsc, mfr, description, basic, stock FROM components WHERE mfr LIKE ?"
        params: list[Any] = [f"{query}%"]

        if basic_only:
            sql += " AND basic = 1"
        if min_stock > 0:
            sql += " AND stock >= ?"
            params.append(min_stock)

        sql += " ORDER BY basic DESC, stock DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [
            JLCPCBPartInfo(
                part_number=f"C{r['lcsc']}",
                classification=(
                    PartClassification.BASIC if r["basic"] == 1
                    else PartClassification.EXTENDED
                ),
                description=r["description"] or "",
                stock=r["stock"] or 0,
                mfr_part=r["mfr"] or None,
            )
            for r in rows
        ]

    def _search_jlcparts_candidates(
        self,
        conn: sqlite3.Connection,
        value: str,
        *,
        basic_only: bool,
        min_stock: int,
        limit: int,
    ) -> list[JLCPCBPartInfo]:
        terms = _value_terms(value)
        if not terms:
            return []

        sql = "SELECT lcsc, mfr, description, basic, stock FROM components WHERE ("
        clauses: list[str] = []
        params: list[Any] = []
        for term in terms:
            clauses.append("(description LIKE ? OR mfr LIKE ?)")
            like = f"%{term}%"
            params.extend((like, like))
        sql += " OR ".join(clauses) + ")"

        if basic_only:
            sql += " AND basic = 1"
        if min_stock > 0:
            sql += " AND stock >= ?"
            params.append(min_stock)

        sql += " ORDER BY basic DESC, stock DESC LIMIT ?"
        params.append(max(limit * 5, 50))

        rows = conn.execute(sql, params).fetchall()
        candidates = [
            JLCPCBPartInfo(
                part_number=f"C{r['lcsc']}",
                classification=(
                    PartClassification.BASIC if r["basic"] == 1
                    else PartClassification.EXTENDED
                ),
                description=r["description"] or "",
                stock=r["stock"] or 0,
                mfr_part=r["mfr"] or None,
            )
            for r in rows
        ]
        return _prefer_exact_value_matches(value, candidates)[:limit]

    def get_by_lcsc_string(self, lcsc_str: str) -> JLCPCBPartInfo | None:
        """Look up by LCSC string (e.g., "C17414")."""
        conn = self._get_conn()

        if self._schema == "extracted":
            row = conn.execute(
                "SELECT * FROM parts WHERE lcsc_part = ?", (lcsc_str,)
            ).fetchone()
            if row is None:
                return None
            return JLCPCBPartInfo(
                part_number=row["lcsc_part"],
                classification=(
                    PartClassification.BASIC
                    if row["classification"] == "basic"
                    else PartClassification.EXTENDED
                ),
                description=row["description"] or "",
                stock=row["stock"] or 0,
                mfr_part=row["mfr_part"] or None,
                package=row["package"] or None,
                category=row["category"] or None,
                subcategory=row["subcategory"] or None,
            )

        # jlcparts schema
        if lcsc_str.startswith("C") and lcsc_str[1:].isdigit():
            lcsc_num = int(lcsc_str[1:])
            row = conn.execute(
                "SELECT lcsc, mfr, description, basic, stock "
                "FROM components WHERE lcsc = ?",
                (lcsc_num,),
            ).fetchone()
            if row is None:
                return None
            return JLCPCBPartInfo(
                part_number=f"C{row['lcsc']}",
                classification=(
                    PartClassification.BASIC if row["basic"] == 1
                    else PartClassification.EXTENDED
                ),
                description=row["description"] or "",
                stock=row["stock"] or 0,
                mfr_part=row["mfr"] or None,
            )
        return None

    def count_total(self) -> int:
        conn = self._get_conn()
        table = "parts" if self._schema == "extracted" else "components"
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _value_terms(value: str) -> tuple[str, ...]:
    text = value.strip().replace(" ", "")
    text = re.sub(r"(?<=\d)\.0+(?=[A-Za-z])", "", text)
    terms = [text]

    ohm_match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)R", text, flags=re.IGNORECASE)
    if ohm_match is not None:
        magnitude = ohm_match.group(1)
        terms.append(f"{magnitude}Ω")
        terms.append(_resistor_code(magnitude, multiplier_scale=1))

    r_decimal_match = re.fullmatch(r"([0-9]+)R([0-9]+)", text, flags=re.IGNORECASE)
    if r_decimal_match is not None:
        magnitude = ".".join(r_decimal_match.groups())
        terms.append(f"{magnitude}Ω")
        terms.append(_resistor_code(magnitude, multiplier_scale=1))

    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([A-Za-z]+)", text)
    if match is not None:
        magnitude, unit = match.groups()
        unit_lower = unit.lower()
        if unit_lower == "k":
            terms.append(f"{magnitude}kΩ")
            terms.append(_resistor_code(magnitude, multiplier_scale=1_000))
        elif unit_lower == "m":
            terms.append(f"{magnitude}MΩ")
            terms.append(_resistor_code(magnitude, multiplier_scale=1_000_000))
        elif unit_lower == "uf":
            terms.append(f"{magnitude}uF")
            terms.append(_capacitor_code(magnitude))
        elif unit_lower == "nf":
            terms.append(f"{magnitude}nF")
            terms.append(_capacitor_code(magnitude, multiplier_scale=1_000))
        elif unit_lower == "uh":
            terms.append(f"{magnitude}uH")
            terms.append(f"{magnitude.replace('.', 'R')}")

    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        if term not in seen:
            unique.append(term)
            seen.add(term)
    return tuple(unique)


def _resistor_code(magnitude: str, *, multiplier_scale: float) -> str:
    try:
        ohms = float(magnitude) * multiplier_scale
    except ValueError:
        return magnitude
    if ohms <= 0:
        return magnitude

    significant = int(round(ohms))
    exponent = 0
    while significant >= 1000 and significant % 10 == 0:
        significant //= 10
        exponent += 1
    if 100 <= significant <= 999:
        return f"{significant}{exponent}"
    return magnitude


def _prefer_exact_value_matches(
    value: str,
    candidates: list[JLCPCBPartInfo],
) -> list[JLCPCBPartInfo]:
    if not candidates:
        return candidates

    value_matchers = (
        _description_matches_resistance,
        _description_matches_capacitance,
        _description_matches_inductance,
    )
    for matcher in value_matchers:
        exact = [candidate for candidate in candidates if matcher(value, candidate.description)]
        if exact:
            return exact
    return candidates


def _description_matches_resistance(value: str, description: str) -> bool:
    target = _target_resistance_ohms(value)
    if target is None:
        return False
    for magnitude, unit in re.findall(
        r"([0-9]+(?:\.[0-9]+)?)\s*(mΩ|R|Ω|kΩ|KΩ|MΩ)",
        description,
    ):
        scale = {
            "mΩ": 0.001,
            "R": 1.0,
            "Ω": 1.0,
            "kΩ": 1_000.0,
            "KΩ": 1_000.0,
            "MΩ": 1_000_000.0,
        }[unit]
        if _close(float(magnitude) * scale, target):
            return True
    return False


def _target_resistance_ohms(value: str) -> float | None:
    text = value.strip().replace(" ", "")
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)R?", text, flags=re.IGNORECASE)
    if match is not None:
        return float(match.group(1))

    r_decimal_match = re.fullmatch(r"([0-9]+)R([0-9]+)", text, flags=re.IGNORECASE)
    if r_decimal_match is not None:
        return float(".".join(r_decimal_match.groups()))

    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([kKmM])Ω?", text)
    if match is None:
        match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)Ω", text)
    if match is None:
        return None
    if len(match.groups()) == 1:
        return float(match.group(1))
    magnitude, unit = match.groups()
    scale = 1_000_000.0 if unit == "M" else 1_000.0
    return float(magnitude) * scale


def _description_matches_capacitance(value: str, description: str) -> bool:
    target = _target_capacitance_pf(value)
    if target is None:
        return False
    for magnitude, unit in re.findall(
        r"([0-9]+(?:\.[0-9]+)?)\s*(pF|nF|uF|µF)",
        description,
        flags=re.IGNORECASE,
    ):
        unit_lower = unit.lower().replace("µ", "u")
        scale = {"pf": 1.0, "nf": 1_000.0, "uf": 1_000_000.0}[unit_lower]
        if _close(float(magnitude) * scale, target):
            return True
    return False


def _target_capacitance_pf(value: str) -> float | None:
    match = re.fullmatch(
        r"([0-9]+(?:\.[0-9]+)?)(pF|nF|uF|µF)",
        value.strip().replace(" ", ""),
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    magnitude, unit = match.groups()
    unit_lower = unit.lower().replace("µ", "u")
    scale = {"pf": 1.0, "nf": 1_000.0, "uf": 1_000_000.0}[unit_lower]
    return float(magnitude) * scale


def _description_matches_inductance(value: str, description: str) -> bool:
    target = _target_inductance_uh(value)
    if target is None:
        return False
    for magnitude, unit in re.findall(
        r"([0-9]+(?:\.[0-9]+)?)\s*(nH|uH|µH|mH)",
        description,
        flags=re.IGNORECASE,
    ):
        unit_lower = unit.lower().replace("µ", "u")
        scale = {"nh": 0.001, "uh": 1.0, "mh": 1_000.0}[unit_lower]
        if _close(float(magnitude) * scale, target):
            return True
    return False


def _target_inductance_uh(value: str) -> float | None:
    match = re.fullmatch(
        r"([0-9]+(?:\.[0-9]+)?)(nH|uH|µH|mH)",
        value.strip().replace(" ", ""),
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    magnitude, unit = match.groups()
    unit_lower = unit.lower().replace("µ", "u")
    scale = {"nh": 0.001, "uh": 1.0, "mh": 1_000.0}[unit_lower]
    return float(magnitude) * scale


def _close(value: float, target: float) -> bool:
    tolerance = max(abs(target) * 1e-6, 1e-9)
    return abs(value - target) <= tolerance


def _capacitor_code(magnitude: str, *, multiplier_scale: float = 1_000_000) -> str:
    try:
        value_pf = float(magnitude) * multiplier_scale
    except ValueError:
        return magnitude
    if value_pf <= 0:
        return magnitude
    digits = f"{value_pf:.0f}"
    if len(digits) < 3:
        return digits
    significant = digits[:2]
    exponent = len(digits) - 2
    return f"{significant}{exponent}"
