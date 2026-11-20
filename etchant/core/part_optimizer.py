"""JLCPCB part substitution and assembly optimization."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from etchant.core.assembly_validator import (
    AssemblyValidationReport,
    validate_jlcpcb_assembly,
)
from etchant.core.component_selector import (
    JLCPCBPartInfo,
    PartClassification,
    find_jlcpcb_part_candidates,
    lookup_jlcpcb_part,
    lookup_jlcpcb_part_by_lcsc,
)
from etchant.core.models import ComponentCategory, ComponentSpec, DesignResult
from etchant.core.serialization import design_to_dict


@dataclass(frozen=True)
class PartSubstitution:
    """One automatic JLCPCB assembly optimization."""

    reference: str
    action: str
    reason: str
    original_value: str
    original_footprint: str
    original_lcsc_part: str | None
    new_value: str
    new_footprint: str
    new_lcsc_part: str | None
    classification: PartClassification | None
    stock: int | None
    mfr_part: str | None
    package: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "reference": self.reference,
            "action": self.action,
            "reason": self.reason,
            "original": {
                "value": self.original_value,
                "footprint": self.original_footprint,
                "lcsc_part": self.original_lcsc_part,
            },
            "new": {
                "value": self.new_value,
                "footprint": self.new_footprint,
                "lcsc_part": self.new_lcsc_part,
                "classification": (
                    self.classification.value if self.classification else None
                ),
                "stock": self.stock,
                "mfr_part": self.mfr_part,
                "package": self.package,
            },
        }


@dataclass(frozen=True)
class PartOptimizationResult:
    """Before/after report for automatic JLCPCB part substitutions."""

    optimized_design: DesignResult
    substitutions: tuple[PartSubstitution, ...]
    before: AssemblyValidationReport
    after: AssemblyValidationReport

    def as_dict(self, *, include_design: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "substitution_count": len(self.substitutions),
            "substitutions": [s.as_dict() for s in self.substitutions],
            "before": self.before.as_dict(),
            "after": self.after.as_dict(),
        }
        if include_design:
            result["optimized_design"] = design_to_dict(self.optimized_design)
        return result


def optimize_jlcpcb_assembly(
    design: DesignResult,
    *,
    min_stock: int = 1,
    prefer_basic: bool = True,
) -> PartOptimizationResult:
    """Apply safe automatic JLCPCB part choices to a generated design."""
    before = validate_jlcpcb_assembly(
        design,
        min_stock=min_stock,
        prefer_basic=prefer_basic,
    )

    substitutions: list[PartSubstitution] = []
    optimized_components: list[ComponentSpec] = []
    for comp in design.components:
        optimized, substitution = _optimize_component(
            comp,
            min_stock=min_stock,
            prefer_basic=prefer_basic,
        )
        optimized_components.append(optimized)
        if substitution is not None:
            substitutions.append(substitution)

    optimized_design = replace(
        design,
        components=tuple(optimized_components),
        design_notes=design.design_notes + _optimization_notes(substitutions),
    )
    after = validate_jlcpcb_assembly(
        optimized_design,
        min_stock=min_stock,
        prefer_basic=prefer_basic,
    )

    return PartOptimizationResult(
        optimized_design=optimized_design,
        substitutions=tuple(substitutions),
        before=before,
        after=after,
    )


def _optimize_component(
    comp: ComponentSpec,
    *,
    min_stock: int,
    prefer_basic: bool,
) -> tuple[ComponentSpec, PartSubstitution | None]:
    connector_footprint = _suggest_smd_connector_footprint(comp)
    if connector_footprint and connector_footprint != comp.footprint:
        optimized = _apply_connector_footprint(comp, connector_footprint)
        return optimized, _footprint_substitution(
            original=comp,
            optimized=optimized,
            action="convert_connector_to_smd",
            reason=(
                "Converted through-hole pin header to an SMD pin-header footprint "
                "so standard SMT assembly no longer requires manual soldering."
            ),
        )

    current = _resolve_current_part(comp)

    if _should_search_replacement(comp, current, prefer_basic=prefer_basic):
        replacement = _find_replacement(comp, min_stock=min_stock, prefer_basic=prefer_basic)
        if replacement is not None and replacement.part_number != comp.jlcpcb_part_number:
            optimized = _apply_part(comp, replacement)
            return optimized, _substitution(
                original=comp,
                optimized=optimized,
                part=replacement,
                action="select_jlcpcb_part",
                reason=_selection_reason(comp, current, replacement),
            )

    if current is None:
        return comp, None

    corrected_footprint = _suggest_footprint_for_part(current)
    if corrected_footprint and corrected_footprint != comp.footprint:
        optimized = _apply_part(
            comp,
            current,
            footprint=corrected_footprint,
        )
        return optimized, _substitution(
            original=comp,
            optimized=optimized,
            part=current,
            action="correct_footprint",
            reason=(
                f"JLCPCB part {current.part_number} package {current.package or 'unknown'} "
                f"maps better to {corrected_footprint}."
            ),
        )

    if comp.jlcpcb_part_number is None:
        optimized = _apply_part(comp, current)
        return optimized, _substitution(
            original=comp,
            optimized=optimized,
            part=current,
            action="tag_existing_part",
            reason=f"Resolved existing value to stocked LCSC part {current.part_number}.",
        )

    return comp, None


def _resolve_current_part(comp: ComponentSpec) -> JLCPCBPartInfo | None:
    if comp.jlcpcb_part_number:
        by_lcsc = lookup_jlcpcb_part_by_lcsc(comp.jlcpcb_part_number)
        if by_lcsc is not None:
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


def _should_search_replacement(
    comp: ComponentSpec,
    current: JLCPCBPartInfo | None,
    *,
    prefer_basic: bool,
) -> bool:
    if comp.category not in _SEARCHABLE_CATEGORIES:
        return False
    if current is None:
        return True
    return prefer_basic and current.classification != PartClassification.BASIC


def _find_replacement(
    comp: ComponentSpec,
    *,
    min_stock: int,
    prefer_basic: bool,
) -> JLCPCBPartInfo | None:
    category = _category_query(comp.category)
    package = _package_query(comp)

    candidates = find_jlcpcb_part_candidates(
        comp.value,
        category=category,
        package=package,
        basic_only=prefer_basic,
        min_stock=min_stock,
        limit=10,
    )
    if not candidates and prefer_basic:
        candidates = find_jlcpcb_part_candidates(
            comp.value,
            category=category,
            package=package,
            basic_only=False,
            min_stock=min_stock,
            limit=10,
        )
    if not candidates and package is not None:
        candidates = find_jlcpcb_part_candidates(
            comp.value,
            category=category,
            basic_only=prefer_basic,
            min_stock=min_stock,
            limit=10,
        )
        if not candidates and prefer_basic:
            candidates = find_jlcpcb_part_candidates(
                comp.value,
                category=category,
                basic_only=False,
                min_stock=min_stock,
                limit=10,
            )

    candidates = _filter_by_component_constraints(comp, candidates)
    return candidates[0] if candidates else None


def _apply_part(
    comp: ComponentSpec,
    part: JLCPCBPartInfo,
    *,
    footprint: str | None = None,
) -> ComponentSpec:
    properties = dict(comp.properties)
    properties.update({
        "jlcpcb_classification": part.classification.value,
        "jlcpcb_stock": str(part.stock),
    })
    if part.mfr_part:
        properties["jlcpcb_mfr_part"] = part.mfr_part
    if part.package:
        properties["jlcpcb_package"] = part.package

    return replace(
        comp,
        footprint=footprint or comp.footprint,
        properties=properties,
        jlcpcb_part_number=part.part_number,
    )


def _substitution(
    *,
    original: ComponentSpec,
    optimized: ComponentSpec,
    part: JLCPCBPartInfo,
    action: str,
    reason: str,
) -> PartSubstitution:
    return PartSubstitution(
        reference=original.reference,
        action=action,
        reason=reason,
        original_value=original.value,
        original_footprint=original.footprint,
        original_lcsc_part=original.jlcpcb_part_number,
        new_value=optimized.value,
        new_footprint=optimized.footprint,
        new_lcsc_part=optimized.jlcpcb_part_number,
        classification=part.classification,
        stock=part.stock,
        mfr_part=part.mfr_part,
        package=part.package,
    )


def _footprint_substitution(
    *,
    original: ComponentSpec,
    optimized: ComponentSpec,
    action: str,
    reason: str,
) -> PartSubstitution:
    return PartSubstitution(
        reference=original.reference,
        action=action,
        reason=reason,
        original_value=original.value,
        original_footprint=original.footprint,
        original_lcsc_part=original.jlcpcb_part_number,
        new_value=optimized.value,
        new_footprint=optimized.footprint,
        new_lcsc_part=optimized.jlcpcb_part_number,
        classification=None,
        stock=None,
        mfr_part=None,
        package=None,
    )


def _selection_reason(
    comp: ComponentSpec,
    current: JLCPCBPartInfo | None,
    replacement: JLCPCBPartInfo,
) -> str:
    if current is None:
        return f"Resolved {comp.value} to stocked JLCPCB part {replacement.part_number}."
    if current.classification != PartClassification.BASIC:
        return (
            f"Replaced {current.classification.value} part {current.part_number} "
            f"with {replacement.classification.value} part {replacement.part_number}."
        )
    return f"Selected stocked JLCPCB part {replacement.part_number}."


_SEARCHABLE_CATEGORIES = {
    ComponentCategory.CAPACITOR,
    ComponentCategory.DIODE,
    ComponentCategory.INDUCTOR,
    ComponentCategory.RESISTOR,
}


def _suggest_smd_connector_footprint(comp: ComponentSpec) -> str | None:
    if comp.category != ComponentCategory.CONNECTOR:
        return None
    if not _is_tht_pin_header(comp.footprint):
        return None

    pin_count = _connector_pin_count(comp)
    if pin_count is None:
        return None

    return (
        "Connector_PinHeader_2.54mm:"
        f"PinHeader_1x{pin_count:02d}_P2.54mm_Vertical_SMD_Pin1Left"
    )


def _is_tht_pin_header(footprint: str) -> bool:
    text = footprint.upper()
    return "PINHEADER" in text and "SMD" not in text


def _connector_pin_count(comp: ComponentSpec) -> int | None:
    for value in (comp.value, comp.footprint, comp.kicad_symbol):
        match = re.search(r"1x0?([0-9]+)", value, flags=re.IGNORECASE)
        if match is not None:
            return int(match.group(1))
    return None


def _apply_connector_footprint(
    comp: ComponentSpec,
    footprint: str,
) -> ComponentSpec:
    properties = dict(comp.properties)
    properties["assembly_mount"] = "smd"
    properties["connector_substitution"] = "pin_header_smd"
    return replace(
        comp,
        footprint=footprint,
        properties=properties,
    )


def _category_query(category: ComponentCategory) -> str | None:
    return {
        ComponentCategory.CAPACITOR: "Capacitor",
        ComponentCategory.DIODE: "Diode",
        ComponentCategory.INDUCTOR: "Inductor",
        ComponentCategory.RESISTOR: "Resistor",
    }.get(category)


def _package_query(comp: ComponentSpec) -> str | None:
    if comp.category == ComponentCategory.INDUCTOR:
        return None

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


def _filter_by_component_constraints(
    comp: ComponentSpec,
    candidates: tuple[JLCPCBPartInfo, ...],
) -> tuple[JLCPCBPartInfo, ...]:
    if comp.category != ComponentCategory.INDUCTOR:
        return candidates

    required = _amp_value(comp.properties.get("saturation_current", ""))
    if required is None:
        return candidates

    filtered = [
        candidate for candidate in candidates
        if _description_has_current_at_least(candidate.description, required)
    ]
    return tuple(filtered or candidates)


def _amp_value(value: str) -> float | None:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*A", value)
    if match is None:
        return None
    return float(match.group(1))


def _description_has_current_at_least(description: str, required_a: float) -> bool:
    amps = [
        float(match.group(1))
        for match in re.finditer(r"([0-9]+(?:\.[0-9]+)?)\s*A", description)
    ]
    return bool(amps) and max(amps) >= required_a


def _suggest_footprint_for_part(part: JLCPCBPartInfo) -> str | None:
    text = _normalized_package_text(" ".join(
        value for value in (part.package, part.description) if value
    ))
    if "TSOT236" in text or "SOT236" in text:
        return "Package_TO_SOT_SMD:SOT-23-6"
    return None


def _normalized_package_text(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", value.upper())


def _optimization_notes(
    substitutions: list[PartSubstitution],
) -> tuple[str, ...]:
    if not substitutions:
        return ()
    basic = sum(1 for s in substitutions if s.classification == PartClassification.BASIC)
    return (
        f"JLCPCB optimization applied: {len(substitutions)} substitutions "
        f"({basic} Basic Part selections).",
    )
