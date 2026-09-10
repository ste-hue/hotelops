"""Freshness contract: da `core/source_registry.yaml` a "cosa esportare, da dove, da quando".

Spec: docs/superpowers/specs/2026-09-09-freshness-contract-design.md.

Tre livelli, dal basso:
- funzioni pure (`expected_through`, `coverage_status`, `status_for`, `action_for`);
- `compute(registry, query, now)`: tre query BigQuery iniettate, una lista di SourceFreshness;
- `render_text` / `to_json`: le due superfici (CLI oggi, hub e nudge domani).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field  # noqa: F401
from datetime import date, datetime, timedelta, timezone  # noqa: F401
from typing import Callable, Literal, Optional  # noqa: F401
from zoneinfo import ZoneInfo

from core.lineage.schemas import AcquisitionContract, FreshnessContract, SourceDefinition

Status = Literal["OK", "DUE", "STALE", "DORMANT", "JOB_DOWN", "DATA_STUCK", "NO_CONTRACT"]

SEVERITY: dict[str, int] = {
    "STALE": 0, "JOB_DOWN": 0, "DATA_STUCK": 0,
    "DUE": 1, "OK": 2, "DORMANT": 3, "NO_CONTRACT": 4,
}
ICON: dict[str, str] = {
    "OK": "✓", "DUE": "!", "STALE": "🔴", "JOB_DOWN": "🔴", "DATA_STUCK": "🔴",
    "DORMANT": "⏸", "NO_CONTRACT": "?",
}
JOB_STALE_HOURS = 36
ROME = ZoneInfo("Europe/Rome")  # noqa: F401


# ── Date attese ─────────────────────────────────────────────────────────────


def _month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def _prev_month_end(d: date) -> date:
    return date(d.year, d.month, 1) - timedelta(days=1)


def _quarter_start(d: date) -> date:
    return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)


def expected_through(cadence: str, today: date) -> Optional[date]:
    """Ultimo giorno che una sorgente con questa cadenza deve coprire oggi."""
    if cadence == "daily":
        return today - timedelta(days=2)
    if cadence == "weekly":
        return today - timedelta(days=10)
    if cadence == "monthly":
        return _prev_month_end(today)
    if cadence == "quarterly":
        return _quarter_start(today) - timedelta(days=1)
    return None  # adhoc


def coverage_status(fc: FreshnessContract, covered: Optional[date], today: date) -> str:
    """OK / DUE / STALE dal solo confronto copertura vs atteso (spec §4)."""
    if fc.cadence == "adhoc":
        return "OK"
    atteso = expected_through(fc.cadence, today)
    if covered is None:
        return "STALE"
    if covered >= atteso:
        return "OK"
    if fc.cadence == "monthly":
        in_grazia = today.day <= fc.grace_day
        if in_grazia and covered >= _prev_month_end(atteso):
            return "DUE"
        return "STALE"
    if fc.cadence == "quarterly":
        in_grazia = (today - _quarter_start(today)).days < 30
        if in_grazia and covered >= _quarter_start(atteso) - timedelta(days=1):
            return "DUE"
        return "STALE"
    return "STALE"  # daily / weekly: età semplice, niente grazia


def status_for(
    fc: Optional[FreshnessContract],
    ac: Optional[AcquisitionContract],
    covered: Optional[date],
    today: date,
    job_ok: Optional[bool],
) -> str:
    if fc is None or ac is None:
        return "NO_CONTRACT"
    if fc.dormant:
        return "DORMANT"
    cov = coverage_status(fc, covered, today)
    if ac.mode == "AUTO":
        if not job_ok:
            return "JOB_DOWN"
        if cov == "STALE":
            return "DATA_STUCK"
    return cov


# ── Frase azione ────────────────────────────────────────────────────────────


def action_for(sd: SourceDefinition, status: str, covered: Optional[date]) -> Optional[str]:
    if status in ("OK", "DORMANT", "NO_CONTRACT"):
        return None
    fc, ac = sd.freshness, sd.acquisition
    if ac.mode == "AUTO":
        if status == "JOB_DOWN":
            return f"→ controlla il job {ac.job}"
        if status == "DATA_STUCK":
            return f"→ job {ac.job} verde, dati fermi: controlla la fonte {ac.location}"
        return None
    parts = [ac.location, ac.report]
    if ac.filters:
        parts.append(ac.filters)
    if fc.basis == "canonical" and covered is not None:
        nota = (
            "sovrapporre qualche giorno è innocuo, dedup su hash"
            if sd.lifecycle == "APPEND"
            else "fotografia a oggi, sostituisce la precedente"
        )
        parts.append(f"dal {covered + timedelta(days=1):%d/%m} ({nota})")
    elif sd.lifecycle == "SNAPSHOT":
        parts.append("fotografia a oggi")
    parts.append(ac.owner)
    if ac.mode == "SEMI":
        cmd = "hotelops capture <file>"
    else:
        cmd = (
            f"hotelops intake <file> --source-name {sd.source_name}"
            " && hotelops promote --raw-object-id <id>"
        )
    return "→ " + " › ".join(parts) + f"\n  poi: {cmd}"
