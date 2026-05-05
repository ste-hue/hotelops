"""Load + validate core/source_registry.yaml. Lookup by detector_category + dims.

Spec: §4.1, §7.1
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import ValidationError

from core.lineage.policy_gate import (
    PolicyViolation,
    enforce_loop_target_gate_consistency,
)
from core.lineage.schemas import InvalidSourceName, SourceDefinition

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "core" / "source_registry.yaml"


class InvalidRegistry(Exception):
    """Registry yaml violates an invariant or schema."""


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that raises on duplicate keys in any mapping."""


def _construct_mapping_no_duplicates(loader, node, deep=False):
    seen: set = set()
    mapping: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise InvalidRegistry(f"duplicate key in registry: {key!r}")
        seen.add(key)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping_no_duplicates,
)


class SourceRegistry:
    def __init__(self, sources: dict[str, SourceDefinition]):
        self.sources = sources

    def find_all_by_detector_category(
        self, detector_category: str
    ) -> list[SourceDefinition]:
        """Return all sources matching this detector category (any società)."""
        return [
            s for s in self.sources.values() if s.detector_category == detector_category
        ]

    def resolve(
        self, detector_category: str, societa: str
    ) -> Optional[SourceDefinition]:
        """Resolve to a single source by (detector_category, società).

        Returns None if no match. Raises InvalidRegistry if more than one
        match (registry inconsistency — should be caught at boot but defensive).
        """
        matches = [
            s
            for s in self.find_all_by_detector_category(detector_category)
            if s.societa == societa
        ]
        if len(matches) > 1:
            raise InvalidRegistry(
                f"Ambiguous lookup: {detector_category}+{societa} matches "
                f"{[s.source_name for s in matches]}"
            )
        return matches[0] if matches else None

    def get(self, source_name: str) -> Optional[SourceDefinition]:
        return self.sources.get(source_name)


def load_registry(path: Optional[Path] = None) -> SourceRegistry:
    """Load + validate the registry. Raises InvalidRegistry on any failure."""
    p = path or REGISTRY_PATH
    if not p.exists():
        raise InvalidRegistry(f"Registry file not found: {p}")
    raw = yaml.load(p.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    if not isinstance(raw, dict) or "sources" not in raw:
        raise InvalidRegistry(f"{p}: missing top-level 'sources' key")

    sources: dict[str, SourceDefinition] = {}
    for source_name, spec in (raw["sources"] or {}).items():
        try:
            sd = SourceDefinition(source_name=source_name, **spec)
        except (ValidationError, InvalidSourceName) as e:
            raise InvalidRegistry(f"{p}::{source_name}: {e}") from e

        try:
            enforce_loop_target_gate_consistency(sd)
        except PolicyViolation as e:
            raise InvalidRegistry(f"{p}::{source_name}: {e}") from e

        sources[source_name] = sd

    return SourceRegistry(sources)
