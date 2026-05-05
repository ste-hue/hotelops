"""Pilot source MPS_BANCA_ORTI_APPEND must be on backend=gcs."""

from core.lineage.source_resolver import load_registry

PILOT_SOURCE = "MPS_BANCA_ORTI_APPEND"


def test_pilot_mps_banca_orti_uses_gcs_backend() -> None:
    reg = load_registry()
    src = reg.get(PILOT_SOURCE)
    assert src is not None
    assert src.raw_storage.backend == "gcs"
    assert src.raw_storage.bucket == "hotelops-raw"
    # Sanity: pilot is APPEND lifecycle (the whole point of switching from
    # the original SNAPSHOT proposal — exercises content_hash dedup).
    assert src.lifecycle == "APPEND"


def test_other_sources_remain_drive() -> None:
    """Bulk flip is a separate PR; verify only pilot moved."""
    reg = load_registry()
    not_pilot_gcs = []
    # SourceRegistry exposes sources via the public `sources` attribute.
    for name, src in reg.sources.items():
        if name == PILOT_SOURCE:
            continue
        if src.raw_storage and src.raw_storage.backend == "gcs":
            not_pilot_gcs.append(name)
    assert not_pilot_gcs == [], (
        f"Only the pilot should be on gcs in this PR; found extra: {not_pilot_gcs}"
    )
