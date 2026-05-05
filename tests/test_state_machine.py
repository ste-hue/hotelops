"""Pure transition rules for the lineage state machine.

Spec: §5.2
"""

import pytest

from core.lineage.state_machine import (
    InvalidTransition,
    can_transition,
    next_status_after_event,
)


# ── Allowed transitions ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "from_status, event_type, expected_to",
    [
        (None, "RAW_INGESTED", "RAW_ONLY"),
        ("RAW_ONLY", "SOURCE_RESOLVED", "CLASSIFIED"),
        ("CLASSIFIED", "PROMOTION_REQUESTED", None),  # no transition, just event
        ("PROMOTABLE", "PROMOTED", "PROMOTED"),
        ("CLASSIFIED", "REJECTED", "REJECTED"),
        ("PROMOTABLE", "REJECTED", "REJECTED"),
        ("REJECTED", "RECLASSIFIED", "CLASSIFIED"),
    ],
)
def test_allowed(from_status, event_type, expected_to) -> None:
    assert can_transition(from_status, event_type)
    if expected_to is not None:
        assert next_status_after_event(from_status, event_type) == expected_to


# ── Forbidden transitions ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "from_status, event_type",
    [
        ("PROMOTED", "RAW_INGESTED"),  # already promoted, can't re-ingest
        ("PROMOTED", "PROMOTED"),  # idempotent guard
        ("RAW_ONLY", "PROMOTED"),  # skip CLASSIFIED+PROMOTABLE
        (None, "PROMOTED"),  # no genesis
    ],
)
def test_forbidden(from_status, event_type) -> None:
    assert not can_transition(from_status, event_type)
    with pytest.raises(InvalidTransition):
        next_status_after_event(from_status, event_type)
