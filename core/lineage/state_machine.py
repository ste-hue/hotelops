"""Pure transition rules. No I/O. No side effects.

Spec: §5.2
"""

from __future__ import annotations

from typing import Optional

from core.lineage.schemas import LineageEventType, RawObjectStatus


class InvalidTransition(Exception):
    """The (from_status, event_type) pair is not allowed by the state machine."""


# Map: (from_status, event_type) → next_status (or None if event is non-transitional)
# from_status=None means "no prior state" (genesis).
_TRANSITIONS: dict[
    tuple[Optional[str], LineageEventType], Optional[RawObjectStatus]
] = {
    # Genesis
    (None, "RAW_INGESTED"): "RAW_ONLY",
    # Detection (non-transitional events)
    ("RAW_ONLY", "DETECTED"): None,
    ("CLASSIFIED", "DETECTED"): None,  # re-detection on already-classified is logged
    # Source resolution
    ("RAW_ONLY", "SOURCE_RESOLVED"): "CLASSIFIED",
    # Validation events (non-transitional — they precede PROMOTED/REJECTED)
    ("PROMOTABLE", "VALIDATED_OK"): None,
    ("PROMOTABLE", "VALIDATED_FAIL"): None,
    ("CLASSIFIED", "VALIDATED_OK"): None,  # Task 4.6: promote from CLASSIFIED
    ("CLASSIFIED", "PROMOTION_REQUESTED"): None,
    ("PROMOTABLE", "PROMOTION_REQUESTED"): None,
    # Promotion
    ("PROMOTABLE", "PROMOTED"): "PROMOTED",
    ("CLASSIFIED", "PROMOTED"): "PROMOTED",  # Task 4.6: promote from CLASSIFIED
    # Rejection (from any non-terminal)
    ("RAW_ONLY", "REJECTED"): "REJECTED",
    ("CLASSIFIED", "REJECTED"): "REJECTED",
    ("PROMOTABLE", "REJECTED"): "REJECTED",
    # Reclassification (revive REJECTED or re-route CLASSIFIED)
    ("REJECTED", "RECLASSIFIED"): "CLASSIFIED",
    ("CLASSIFIED", "RECLASSIFIED"): "CLASSIFIED",
    ("RAW_ONLY", "RECLASSIFIED"): "RAW_ONLY",
}


def can_transition(
    from_status: Optional[RawObjectStatus],
    event_type: LineageEventType,
) -> bool:
    """Return True if (from_status, event_type) is a known transition."""
    return (from_status, event_type) in _TRANSITIONS


def next_status_after_event(
    from_status: Optional[RawObjectStatus],
    event_type: LineageEventType,
) -> Optional[RawObjectStatus]:
    """Return the new status after applying this event.

    Returns None for non-transitional events (DETECTED, VALIDATED_*, PROMOTION_REQUESTED).
    Raises InvalidTransition if the pair is not allowed.
    """
    if not can_transition(from_status, event_type):
        raise InvalidTransition(
            f"Cannot apply {event_type!r} from status {from_status!r}"
        )
    return _TRANSITIONS[(from_status, event_type)]
