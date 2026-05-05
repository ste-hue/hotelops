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


class SourceRegistry:
    def __init__(self, sources: dict[str, SourceDefinition]):
        self.sources = sources

    def find_by_detector_category(
        self, detector_category: str, societa: Optional[str] = None
    ) -> list[SourceDefinition] | Optional[SourceDefinition]:
        """Lookup sources matching detector_category (and optionally societa).

        - With societa: returns single SourceDefinition or None.
        - Without societa: returns list of all matches.
        """
        matches = [
            s for s in self.sources.values() if s.detector_category == detector_category
        ]
        if societa is None:
            return matches
        narrow = [s for s in matches if s.societa == societa]
        if not narrow:
            return None
        if len(narrow) > 1:
            raise InvalidRegistry(
                f"Ambiguous lookup: {detector_category}+{societa} matches "
                f"{[s.source_name for s in narrow]}"
            )
        return narrow[0]

    def get(self, source_name: str) -> Optional[SourceDefinition]:
        return self.sources.get(source_name)


def load_registry(path: Optional[Path] = None) -> SourceRegistry:
    """Load + validate the registry. Raises InvalidRegistry on any failure."""
    p = path or REGISTRY_PATH
    if not p.exists():
        raise InvalidRegistry(f"Registry file not found: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
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
