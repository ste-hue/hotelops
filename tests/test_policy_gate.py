"""Hard gate: 'no loop, no canonical'.

Spec: §7.1
"""

import pytest

from core.lineage.policy_gate import (
    PolicyViolation,
    enforce_loop_target_gate_consistency,
    enforce_loop_target_gate_at_promotion,
)
from core.lineage.schemas import SourceDefinition


def _src(**overrides) -> SourceDefinition:
    base = dict(
        source_name="ESOLVER_BILANCINO_ORTI_SNAPSHOT",
        system="ESOLVER",
        dataset="BILANCINO",
        societa="ORTI",
        lifecycle="SNAPSHOT",
        canonical_table="f_bilancino",
        parser_module="ingest.flussi.ingest_bilancino",
        natural_key=["data_snapshot", "societa_id"],
        loop_targets=["monthly_close"],
        promotion_policy="AUTO",
        detector_category="bilancino",
        raw_storage={"backend": "drive", "path_template": "bilancino/ORTI"},
    )
    base.update(overrides)
    return SourceDefinition(**base)


# ── Boot-time consistency ────────────────────────────────────────────────────


def test_consistent_auto_with_loops_passes() -> None:
    enforce_loop_target_gate_consistency(_src())  # no raise


def test_consistent_raw_only_no_loops_passes() -> None:
    src = _src(
        source_name="POWERBI_CRUSCOTTO_ORTI_APPEND",
        system="POWERBI",
        dataset="CRUSCOTTO",
        lifecycle="APPEND",
        canonical_table="f_pms_statistiche",
        parser_module="ingest.flussi.ingest_pms_statistiche",
        natural_key=None,
        loop_targets=[],
        promotion_policy="RAW_ONLY",
        detector_category="pms_statistiche",
    )
    enforce_loop_target_gate_consistency(src)  # no raise


def test_inconsistent_raw_only_with_loops_fails() -> None:
    src = _src(promotion_policy="RAW_ONLY")  # loops still set
    with pytest.raises(PolicyViolation) as exc:
        enforce_loop_target_gate_consistency(src)
    assert exc.value.reason == "NO_LOOP_TARGET"


def test_inconsistent_auto_without_loops_fails() -> None:
    src = _src(loop_targets=[])
    with pytest.raises(PolicyViolation):
        enforce_loop_target_gate_consistency(src)


# ── Promotion-time fail-closed ───────────────────────────────────────────────


def test_promotion_blocked_for_raw_only() -> None:
    src = _src(
        source_name="POWERBI_CRUSCOTTO_ORTI_APPEND",
        system="POWERBI",
        dataset="CRUSCOTTO",
        lifecycle="APPEND",
        canonical_table="f_pms_statistiche",
        parser_module="ingest.flussi.ingest_pms_statistiche",
        natural_key=None,
        loop_targets=[],
        promotion_policy="RAW_ONLY",
        detector_category="pms_statistiche",
    )
    with pytest.raises(PolicyViolation) as exc:
        enforce_loop_target_gate_at_promotion(src)
    assert exc.value.reason == "NO_LOOP_TARGET"


def test_promotion_allowed_for_auto() -> None:
    enforce_loop_target_gate_at_promotion(_src())  # no raise
