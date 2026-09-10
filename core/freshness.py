"""Freshness contract: da `core/source_registry.yaml` a "cosa esportare, da dove, da quando".

Spec: docs/superpowers/specs/2026-09-09-freshness-contract-design.md.

Tre livelli, dal basso:
- funzioni pure (`expected_through`, `coverage_status`, `status_for`, `action_for`);
- `compute(registry, query, now)`: tre query BigQuery iniettate, una lista di SourceFreshness;
- `render_text` / `to_json`: le due superfici (CLI oggi, hub e nudge domani).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Literal, Optional
from zoneinfo import ZoneInfo

from core.lineage.schemas import (
    AcquisitionContract,
    FreshnessContract,
    SourceDefinition,
)

Status = Literal[
    "OK", "DUE", "STALE", "DORMANT", "JOB_DOWN", "DATA_STUCK", "NO_CONTRACT"
]

SEVERITY: dict[str, int] = {
    "STALE": 0,
    "JOB_DOWN": 0,
    "DATA_STUCK": 0,
    "DUE": 1,
    "OK": 2,
    "DORMANT": 3,
    "NO_CONTRACT": 4,
}
ICON: dict[str, str] = {
    "OK": "✓",
    "DUE": "!",
    "STALE": "🔴",
    "JOB_DOWN": "🔴",
    "DATA_STUCK": "🔴",
    "DORMANT": "⏸",
    "NO_CONTRACT": "?",
}
JOB_STALE_HOURS = 36
ROME = ZoneInfo("Europe/Rome")


def today_rome(now: Optional[datetime] = None) -> date:
    """Data odierna in Europe/Rome, derivata da un istante UTC (default: adesso)."""
    now = now or datetime.now(timezone.utc)
    return now.astimezone(ROME).date()


# ── Date attese ─────────────────────────────────────────────────────────────


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


def action_for(
    sd: SourceDefinition, status: str, covered: Optional[date]
) -> Optional[str]:
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


# ── Risultato ───────────────────────────────────────────────────────────────


@dataclass
class SourceFreshness:
    source_name: str
    tier: Optional[str]
    mode: Optional[str]
    owner: Optional[str]
    status: str
    covered_through: Optional[date]
    expected_through: Optional[date]
    age_days: Optional[int]
    last_raw_at: Optional[date]
    per_dim: list[tuple[dict, Optional[date]]]
    blocks: list[str]
    action: Optional[str]
    raw_only: bool = False
    job: Optional[str] = None
    job_last_ok: Optional[datetime] = None
    job_age_hours: Optional[int] = None
    dormant: Optional[str] = None
    grace_day: Optional[int] = None
    basis: Optional[str] = None


# ── compute ─────────────────────────────────────────────────────────────────

_SOCIETA_FILTRABILI = ("ORTI", "INTUR")


def _as_date(v) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _as_dt(v) -> Optional[datetime]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(v)).replace(tzinfo=timezone.utc)


def _rows_for(sd: SourceDefinition, rows: list[dict]) -> list[dict]:
    fc = sd.freshness
    out = []
    for r in rows:
        if sd.societa in _SOCIETA_FILTRABILI and r.get("societa_id") != sd.societa:
            continue
        if any(r.get(dim) not in allowed for dim, allowed in fc.dim_filter.items()):
            continue
        out.append(r)
    return out


def _coverage_sql(table: str, expr: str, dims: tuple[str, ...]) -> str:
    cols = ["societa_id", *dims]
    group = ", ".join(str(i + 1) for i in range(len(cols)))
    return (
        f"SELECT {', '.join(cols)}, MAX({expr}) AS covered "
        f"FROM hotelops.{table} GROUP BY {group}"
    )


RAW_SQL = (
    "SELECT source_name, DATE(MAX(intake_at)) AS last_intake "
    "FROM hotelops.f_raw_objects GROUP BY 1"
)
JOBS_SQL = (
    "SELECT pipeline_name, MAX(ended_at) AS last_ok "
    "FROM hotelops.f_pipeline_runs WHERE status = 'OK' GROUP BY 1"
)


def compute(
    registry,
    query: Callable[[str], list[dict]],
    now: Optional[datetime] = None,
) -> list[SourceFreshness]:
    now = now or datetime.now(timezone.utc)
    today = today_rome(now)
    sources: list[SourceDefinition] = list(registry.sources.values())

    raw_last = {r["source_name"]: _as_date(r["last_intake"]) for r in query(RAW_SQL)}
    jobs_last = {r["pipeline_name"]: _as_dt(r["last_ok"]) for r in query(JOBS_SQL)}

    groups: dict[tuple[str, str, tuple[str, ...]], list[dict]] = {}
    for sd in sources:
        fc = sd.freshness
        if fc is None or fc.basis != "canonical":
            continue
        key = (sd.canonical_table, fc.coverage_column, tuple(fc.dims))
        if key not in groups:
            groups[key] = query(_coverage_sql(*key))

    items: list[SourceFreshness] = []
    for sd in sources:
        fc, ac = sd.freshness, sd.acquisition
        per_dim: list[tuple[dict, Optional[date]]] = []
        covered: Optional[date] = None
        if fc is not None and fc.basis == "canonical":
            key = (sd.canonical_table, fc.coverage_column, tuple(fc.dims))
            for r in _rows_for(sd, groups[key]):
                d = _as_date(r.get("covered"))
                per_dim.append(({k: r.get(k) for k in fc.dims}, d))
            dates = [d for _, d in per_dim if d is not None]
            covered = min(dates) if dates and len(dates) == len(per_dim) else None
            per_dim.sort(key=lambda t: tuple(str(v) for v in t[0].values()))
        elif fc is not None:
            covered = raw_last.get(sd.source_name)

        job_ok: Optional[bool] = None
        job_last = None
        job_age_hours: Optional[int] = None
        if ac is not None and ac.mode == "AUTO":
            job_last = jobs_last.get(ac.job)
            job_ok = job_last is not None and (now - job_last) <= timedelta(
                hours=JOB_STALE_HOURS
            )
            if job_last is not None:
                job_age_hours = int((now - job_last).total_seconds() // 3600)

        status = status_for(fc, ac, covered, today, job_ok)
        atteso = expected_through(fc.cadence, today) if fc else None
        items.append(
            SourceFreshness(
                source_name=sd.source_name,
                tier=fc.tier if fc else None,
                mode=ac.mode if ac else None,
                owner=ac.owner if ac else None,
                status=status,
                covered_through=covered,
                expected_through=atteso,
                age_days=(today - covered).days if covered else None,
                last_raw_at=raw_last.get(sd.source_name),
                per_dim=per_dim,
                blocks=list(sd.loop_targets),
                action=action_for(sd, status, covered) if fc and ac else None,
                raw_only=sd.promotion_policy == "RAW_ONLY",
                job=ac.job if ac else None,
                job_last_ok=job_last,
                job_age_hours=job_age_hours,
                dormant=fc.dormant if fc else None,
                grace_day=fc.grace_day if fc else None,
                basis=fc.basis if fc else None,
            )
        )

    items.sort(key=lambda i: (SEVERITY[i.status], -len(i.blocks), i.source_name))
    return items


# ── Superfici ───────────────────────────────────────────────────────────────


def _fmt(d: Optional[date]) -> str:
    return f"{d:%d/%m}" if d else "mai"


def _summary(it: SourceFreshness, now_date: date) -> str:
    if it.status == "DORMANT":
        return f"dormiente: {it.dormant}"
    if it.status == "NO_CONTRACT":
        return "senza contratto"
    cop = (
        f"ultimo raw {_fmt(it.covered_through)}"
        if it.basis == "raw"
        else f"coperto {_fmt(it.covered_through)}"
    )
    if it.mode == "AUTO":
        if it.job_last_ok is None:
            job = f"job {it.job} mai OK"
        else:
            job = f"job {it.job} OK {it.job_age_hours}h fa"
        return f"{cop} · {job}"
    if it.status == "OK":
        return cop
    if it.status == "DUE":
        return f"{cop} · atteso {_fmt(it.expected_through)} · in scadenza (grazia fino al {it.grace_day})"
    return f"{cop} · atteso {_fmt(it.expected_through)} · {it.age_days if it.age_days is not None else '?'}gg"


def render_text(
    items: list[SourceFreshness], today: date, show_all: bool = False
) -> str:
    out = [
        f"  SORGENTI — {today:%Y-%m-%d} (mensile: mese precedente pieno entro il giorno di grazia)",
        "",
    ]
    for it in items:
        if it.raw_only and not show_all:
            continue
        out.append(f"  {ICON[it.status]} {it.source_name:<40} {_summary(it, today)}")
        if len(it.per_dim) > 1:
            out.append(
                "       "
                + " · ".join(
                    f"{'/'.join(str(v) for v in dims.values())} {_fmt(d)}"
                    for dims, d in it.per_dim
                )
            )
        if it.action:
            for line in it.action.splitlines():
                out.append("     " + line)
        if it.action and it.blocks:
            out.append(f"       blocca: {', '.join(it.blocks)}")
    return "\n".join(out)


def to_json(items: list[SourceFreshness]) -> list[dict]:
    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    return [
        {
            "source_name": it.source_name,
            "tier": it.tier,
            "mode": it.mode,
            "owner": it.owner,
            "status": it.status,
            "covered_through": iso(it.covered_through),
            "expected_through": iso(it.expected_through),
            "age_days": it.age_days,
            "last_raw_at": iso(it.last_raw_at),
            "per_dim": [
                {"dims": dims, "covered_through": iso(d)} for dims, d in it.per_dim
            ],
            "blocks": it.blocks,
            "action": it.action,
            "raw_only": it.raw_only,
            "job": it.job,
            "job_last_ok": iso(it.job_last_ok),
            "job_age_hours": it.job_age_hours,
            "dormant": it.dormant,
        }
        for it in items
    ]
