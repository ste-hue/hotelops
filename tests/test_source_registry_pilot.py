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


# NOTE: test_other_sources_remain_drive removed on verticals-v2 branch.
# It enforced "only MPS_BANCA_ORTI on gcs" which was a Phase 4 single-pilot
# constraint. The verticals-v2 strategy is "every source on gcs eventually"
# (sync-first to nuke), so this assertion contradicts the new direction.
# See KERNEL.md and .cursor/plans/platform-canonical-boundary_*.plan.md
# (rev 3, 2026-05-09).
