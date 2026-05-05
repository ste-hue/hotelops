"""Source registry loader + lookup."""

from pathlib import Path

import pytest

from core.lineage.source_resolver import (
    InvalidRegistry,
    SourceRegistry,
    load_registry,
)


# ── Registry load + invariant validation ─────────────────────────────────────


def test_load_real_registry() -> None:
    """The shipped registry must load + validate cleanly."""
    reg = load_registry()
    assert len(reg.sources) >= 10
    assert "ESOLVER_BILANCINO_ORTI_SNAPSHOT" in reg.sources
    assert "POWERBI_CRUSCOTTO_ORTI_APPEND" in reg.sources


def test_registry_lookup_by_detector_category(tmp_path: Path) -> None:
    reg = load_registry()
    matches = reg.find_by_detector_category("partite_fornitori")
    assert len(matches) == 2  # ORTI + INTUR
    societas = {m.societa for m in matches}
    assert societas == {"ORTI", "INTUR"}


def test_registry_lookup_with_societa(tmp_path: Path) -> None:
    reg = load_registry()
    match = reg.find_by_detector_category("partite_fornitori", societa="ORTI")
    assert match is not None
    assert match.source_name == "ESOLVER_PARTITE_ORTI_SNAPSHOT"


# ── Invariant: loop_targets == [] ⇔ promotion_policy == RAW_ONLY ─────────────


def test_invariant_violation_raw_only_with_loops(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        """
version: 1
sources:
  ESOLVER_BAD_ORTI_APPEND:
    system: ESOLVER
    dataset: BAD
    societa: ORTI
    lifecycle: APPEND
    canonical_table: f_x
    parser_module: ingest.flussi.x
    promotion_policy: RAW_ONLY
    detector_category: x
    loop_targets: [some_loop]
    raw_storage: {backend: local, path_template: "x"}
"""
    )
    with pytest.raises(InvalidRegistry, match="RAW_ONLY"):
        load_registry(path=bad)


def test_invariant_violation_auto_without_loops(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        """
version: 1
sources:
  ESOLVER_BAD_ORTI_APPEND:
    system: ESOLVER
    dataset: BAD
    societa: ORTI
    lifecycle: APPEND
    canonical_table: f_x
    parser_module: ingest.flussi.x
    promotion_policy: AUTO
    detector_category: x
    loop_targets: []
    raw_storage: {backend: local, path_template: "x"}
"""
    )
    with pytest.raises(InvalidRegistry, match="loop_targets"):
        load_registry(path=bad)


def test_invalid_source_name_in_registry(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        """
version: 1
sources:
  bad_lowercase_name:
    system: ESOLVER
    dataset: X
    societa: ORTI
    lifecycle: APPEND
    canonical_table: f_x
    parser_module: ingest.flussi.x
    promotion_policy: AUTO
    detector_category: x
    loop_targets: [some_loop]
    raw_storage: {backend: local, path_template: "x"}
"""
    )
    with pytest.raises(Exception):  # InvalidSourceName wrapped or surfaced
        load_registry(path=bad)
