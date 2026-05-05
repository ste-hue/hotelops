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


def test_registry_find_all_by_detector_category(tmp_path: Path) -> None:
    reg = load_registry()
    matches = reg.find_all_by_detector_category("partite_fornitori")
    assert len(matches) == 2  # ORTI + INTUR
    societas = {m.societa for m in matches}
    assert societas == {"ORTI", "INTUR"}


def test_registry_resolve(tmp_path: Path) -> None:
    reg = load_registry()
    match = reg.resolve("partite_fornitori", societa="ORTI")
    assert match is not None
    assert match.source_name == "ESOLVER_PARTITE_ORTI_SNAPSHOT"


def test_registry_resolve_missing_returns_none(tmp_path: Path) -> None:
    reg = load_registry()
    assert reg.resolve("partite_fornitori", societa="GROUP") is None
    assert reg.resolve("nonexistent_category", societa="ORTI") is None


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
    with pytest.raises(InvalidRegistry, match="bad_lowercase_name"):
        load_registry(path=bad)


def test_invariant_legitimate_raw_only_loads(tmp_path: Path) -> None:
    """A row with loop_targets=[] AND promotion_policy=RAW_ONLY must load."""
    good = tmp_path / "good.yaml"
    good.write_text(
        """
version: 1
sources:
  POWERBI_OK_ORTI_APPEND:
    system: POWERBI
    dataset: OK
    societa: ORTI
    lifecycle: APPEND
    canonical_table: f_x
    parser_module: ingest.flussi.x
    promotion_policy: RAW_ONLY
    detector_category: x
    loop_targets: []
    raw_storage: {backend: local, path_template: "x"}
"""
    )
    reg = load_registry(path=good)
    assert "POWERBI_OK_ORTI_APPEND" in reg.sources
    assert reg.sources["POWERBI_OK_ORTI_APPEND"].promotion_policy == "RAW_ONLY"


# ── raw_storage.backend ∈ {drive, local, gcs} (Phase 4) ──────────────────────


def test_load_registry_rejects_unknown_backend(tmp_path: Path) -> None:
    """raw_storage.backend not in {drive, local, gcs} must be rejected at boot."""
    yaml_text = """
version: 1
sources:
  X_Y_ORTI_APPEND:
    system: X
    dataset: Y
    societa: ORTI
    lifecycle: APPEND
    canonical_table: f_x
    parser_module: ingest.fake
    hash_basis: hash_riga
    loop_targets: [some_loop]
    promotion_policy: AUTO
    detector_category: x
    raw_storage:
      backend: floppy_disk
      path_template: "x"
"""
    p = tmp_path / "registry.yaml"
    p.write_text(yaml_text)

    with pytest.raises(InvalidRegistry, match="backend"):
        load_registry(p)


def test_load_registry_accepts_gcs_backend(tmp_path: Path) -> None:
    """raw_storage.backend=gcs (with bucket) is a valid configuration."""
    yaml_text = """
version: 1
sources:
  X_Y_ORTI_APPEND:
    system: X
    dataset: Y
    societa: ORTI
    lifecycle: APPEND
    canonical_table: f_x
    parser_module: ingest.fake
    hash_basis: hash_riga
    loop_targets: [some_loop]
    promotion_policy: AUTO
    detector_category: x
    raw_storage:
      backend: gcs
      bucket: hotelops-raw
      path_template: "x"
"""
    p = tmp_path / "registry.yaml"
    p.write_text(yaml_text)

    reg = load_registry(p)
    assert reg.get("X_Y_ORTI_APPEND").raw_storage.backend == "gcs"
    assert reg.get("X_Y_ORTI_APPEND").raw_storage.bucket == "hotelops-raw"
