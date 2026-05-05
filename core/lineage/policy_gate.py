"""Policy gate — hard gate for 'no loop, no canonical'. (stub — Task 4 fills in)"""

from __future__ import annotations

from core.lineage.schemas import SourceDefinition


class PolicyViolation(Exception):
    def __init__(self, reason: str, source_name: str, message: str):
        self.reason = reason
        self.source_name = source_name
        super().__init__(message)


def enforce_loop_target_gate_consistency(source_def: SourceDefinition) -> None:
    """Boot-time check: loop_targets == [] ⇔ promotion_policy == RAW_ONLY."""
    has_loops = bool(source_def.loop_targets)
    is_raw_only = source_def.promotion_policy == "RAW_ONLY"
    if has_loops and is_raw_only:
        raise PolicyViolation(
            "NO_LOOP_TARGET",
            source_def.source_name,
            f"{source_def.source_name}: promotion_policy=RAW_ONLY "
            f"contraddice loop_targets={source_def.loop_targets}.",
        )
    if not has_loops and not is_raw_only:
        raise PolicyViolation(
            "NO_LOOP_TARGET",
            source_def.source_name,
            f"{source_def.source_name}: loop_targets=[] ma "
            f"promotion_policy={source_def.promotion_policy}.",
        )
