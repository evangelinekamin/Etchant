"""JLCPCB assembly readiness validation.

DRC answers "can this board be fabricated?" This module answers the next
question: "can JLCPCB plausibly assemble the selected parts on this board?"
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from etchant.core.component_selector import (
    JLCPCBPartInfo,
    PartClassification,
    find_jlcpcb_part_candidates,
    lookup_jlcpcb_part,
    lookup_jlcpcb_part_by_lcsc,
)
from etchant.core.models import ComponentCategory, ComponentSpec, DesignResult


class AssemblySeverity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class AssemblyIssue:
    """One assembly-readiness issue for a component."""

    rule: str
    severity: AssemblySeverity
    message: str


@dataclass(frozen=True)
class ComponentAssemblyCheck:
    """Resolved JLCPCB state for one component."""

    reference: str
    value: str
    footprint: str
    category: str
    lcsc_part: str | None
    classification: PartClassification
    stock: int | None
    issues: tuple[AssemblyIssue, ...]

    @property
    def has_error(self) -> bool:
        return any(issue.severity == AssemblySeverity.ERROR for issue in self.issues)

    def as_dict(self) -> dict[str, object]:
        return {
            "reference": self.reference,
            "value": self.value,
            "footprint": self.footprint,
            "category": self.category,
            "lcsc_part": self.lcsc_part,
            "classification": self.classification.value,
            "stock": self.stock,
            "issues": [
                {
                    "rule": issue.rule,
                    "severity": issue.severity.value,
                    "message": issue.message,
                }
                for issue in self.issues
            ],
        }


@dataclass(frozen=True)
class AssemblyValidationReport:
    """Aggregate JLCPCB assembly readiness report."""

    assembly_ready: bool
    total_components: int
    matched_components: int
    basic_components: int
    extended_components: int
    unknown_components: int
    error_count: int
    warning_count: int
    checks: tuple[ComponentAssemblyCheck, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "assembly_ready": self.assembly_ready,
            "summary": {
                "total_components": self.total_components,
                "matched_components": self.matched_components,
                "basic_components": self.basic_components,
                "extended_components": self.extended_components,
                "unknown_components": self.unknown_components,
                "error_count": self.error_count,
                "warning_count": self.warning_count,
            },
            "components": [check.as_dict() for check in self.checks],
        }


def validate_jlcpcb_assembly(
    design: DesignResult,
    *,
    min_stock: int = 1,
    prefer_basic: bool = False,
) -> AssemblyValidationReport:
    """Validate that a design's parts are ready for JLCPCB assembly."""
    checks = tuple(
        _check_component(comp, min_stock=min_stock, prefer_basic=prefer_basic)
        for comp in design.components
    )
    error_count = sum(
        1 for check in checks for issue in check.issues
        if issue.severity == AssemblySeverity.ERROR
    )
    warning_count = sum(
        1 for check in checks for issue in check.issues
        if issue.severity == AssemblySeverity.WARNING
    )

    return AssemblyValidationReport(
        assembly_ready=error_count == 0,
        total_components=len(checks),
        matched_components=sum(1 for check in checks if check.lcsc_part is not None),
        basic_components=sum(
            1 for check in checks if check.classification == PartClassification.BASIC
        ),
        extended_components=sum(
            1 for check in checks if check.classification == PartClassification.EXTENDED
        ),
        unknown_components=sum(
            1 for check in checks if check.classification == PartClassification.UNKNOWN
        ),
        error_count=error_count,
        warning_count=warning_count,
        checks=checks,
    )


def _check_component(
    comp: ComponentSpec,
    *,
    min_stock: int,
    prefer_basic: bool,
) -> ComponentAssemblyCheck:
    part = _resolve_part(comp)
    issues: list[AssemblyIssue] = []

    if part is None:
        severity = (
            AssemblySeverity.WARNING
            if comp.category == ComponentCategory.CONNECTOR
            else AssemblySeverity.ERROR
        )
        issues.append(AssemblyIssue(
            rule="jlcpcb_part_missing",
            severity=severity,
            message=(
                "No matching LCSC/JLCPCB part found; exclude from PCBA or choose "
                "a stocked assembly part."
            ),
        ))
        classification = PartClassification.UNKNOWN
        lcsc_part = None
        stock = None
    else:
        classification = part.classification
        lcsc_part = part.part_number
        stock = part.stock
        if part.stock < min_stock:
            issues.append(AssemblyIssue(
                rule="stock_below_minimum",
                severity=AssemblySeverity.ERROR,
                message=f"Stock {part.stock} is below required minimum {min_stock}.",
            ))

        if prefer_basic and part.classification == PartClassification.EXTENDED:
            issues.append(AssemblyIssue(
                rule="extended_part_setup_fee",
                severity=AssemblySeverity.WARNING,
                message=(
                    "Extended JLCPCB part; prefer a Basic Part alternative to avoid "
                    "the per-unique-part setup fee when possible."
                ),
            ))

        if not _package_matches(comp.footprint, part):
            issues.append(AssemblyIssue(
                rule="footprint_package_mismatch",
                severity=AssemblySeverity.ERROR,
                message=(
                    f"Footprint '{comp.footprint}' does not appear to match "
                    f"JLCPCB part {part.part_number}: {part.description}"
                ),
            ))

    if _is_through_hole(comp):
        issues.append(AssemblyIssue(
            rule="through_hole_manual_assembly",
            severity=AssemblySeverity.WARNING,
            message=(
                "Through-hole footprint is not standard SMT assembly; plan manual "
                "soldering, THT assembly service, or exclude it from PCBA."
            ),
        ))

    if (
        comp.category in (ComponentCategory.RESISTOR, ComponentCategory.CAPACITOR)
        and "0201" in comp.footprint
    ):
        issues.append(AssemblyIssue(
            rule="tiny_passive_package",
            severity=AssemblySeverity.WARNING,
            message="0201 passives are harder to assemble/rework; prefer 0402 or 0603.",
        ))

    return ComponentAssemblyCheck(
        reference=comp.reference,
        value=comp.value,
        footprint=comp.footprint,
        category=comp.category.name,
        lcsc_part=lcsc_part,
        classification=classification,
        stock=stock,
        issues=tuple(issues),
    )


def _resolve_part(comp: ComponentSpec) -> JLCPCBPartInfo | None:
    if comp.jlcpcb_part_number:
        by_lcsc = lookup_jlcpcb_part_by_lcsc(comp.jlcpcb_part_number)
        if by_lcsc:
            return by_lcsc
    candidates = find_jlcpcb_part_candidates(
        comp.value,
        category=_category_query(comp.category),
        package=_package_query(comp),
        min_stock=1,
        limit=1,
    )
    if candidates:
        return candidates[0]
    return lookup_jlcpcb_part(comp.value)


def _category_query(category: ComponentCategory) -> str | None:
    return {
        ComponentCategory.CAPACITOR: "Capacitor",
        ComponentCategory.DIODE: "Diode",
        ComponentCategory.INDUCTOR: "Inductor",
        ComponentCategory.RESISTOR: "Resistor",
    }.get(category)


def _package_query(comp: ComponentSpec) -> str | None:
    text = comp.footprint.upper()
    metric_aliases = {
        "1005": "0402",
        "1608": "0603",
        "2012": "0805",
        "3216": "1206",
        "3225": "1210",
        "4532": "1812",
    }
    for metric, imperial in metric_aliases.items():
        if metric in text:
            return imperial
    for package in ("0201", "0402", "0603", "0805", "1206", "1210", "1812"):
        if package in text:
            return package
    return None


def _is_through_hole(comp: ComponentSpec) -> bool:
    footprint = comp.footprint.upper()
    return "_THT:" in footprint or ("PINHEADER" in footprint and "SMD" not in footprint)


def _package_matches(footprint: str, part: JLCPCBPartInfo) -> bool:
    tokens = _footprint_package_tokens(footprint)
    if not tokens:
        return True

    description = _normalize_package_text(part.description)
    return any(token in description for token in tokens)


def _footprint_package_tokens(footprint: str) -> tuple[str, ...]:
    text = _normalize_package_text(footprint)
    tokens: list[str] = []

    for pattern in (
        "0201", "0402", "0603", "0805", "1206", "1210", "1812",
        "SOT223", "SOT23", "TSOT23", "SOT563", "SOT323",
        "SOD123FL", "SOD123F", "SOD123", "SOD323", "SOD523",
        "SOIC", "SOP", "SSOP", "TSSOP", "QFN", "DFN",
        "SMA", "SMB", "SMC", "DO201", "TO263", "TO252",
        "POWERPAKSO8L", "POWERPAKSO8",
        "WSON8", "WSON",
    ):
        if pattern in text:
            tokens.append(pattern)

    # Metric passive aliases used by KiCad footprint names.
    metric_aliases = {
        "1005": "0402",
        "1608": "0603",
        "2012": "0805",
        "3216": "1206",
        "3225": "1210",
        "4532": "1812",
    }
    for metric, imperial in metric_aliases.items():
        if metric in text:
            tokens.append(imperial)

    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique = []
    for token in tokens:
        if token not in seen:
            unique.append(token)
            seen.add(token)
    return tuple(unique)


def _normalize_package_text(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", value.upper())
