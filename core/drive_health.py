"""Sezione DRIVE di `hotelops health`: le quattro viste v_drive_* lette e rese.
Spec: docs/superpowers/specs/2026-10-17-drive-agent-friendly-design.md.

Stesso disegno di core/freshness.py: una `query` iniettata (sql → list[dict]),
funzioni pure sopra. Nessun client BigQuery qui dentro.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from core.config import DATASET, PROJECT

_V = f"`{PROJECT}.{DATASET}`"

CHECKS: dict[str, dict[str, str]] = {
    "duplicati": {
        "sql": (
            f"SELECT md5, copie, path, name, e_la_prima FROM {_V}.v_drive_duplicati "
            "ORDER BY copie DESC, md5, created_time"
        ),
        "label": "copie dello stesso contenuto",
        "item": "{path}  (×{copie})",
        "key": "md5",
    },
    "permessi": {
        "sql": f"SELECT path, esposizione, perm_outside_domain FROM {_V}.v_drive_permessi ORDER BY path",
        "label": "esposizioni esterne o permessi non osservati",
        "item": "{path}  [{esposizione}]",
        "key": "path",
    },
    "radice": {
        "sql": f"SELECT name, giorni_in_radice FROM {_V}.v_drive_radice ORDER BY created_time",
        "label": "file fermi in radice da più di 7 giorni",
        "item": "{name}  ({giorni_in_radice} gg)",
        "key": "name",
    },
    "lineage": {
        "sql": (
            f"SELECT stato, source_name, name, path, raw_uri FROM {_V}.v_drive_lineage "
            "ORDER BY stato, created_time"
        ),
        "label": "file in attesa o raw fuori da gs://",
        "item": "{stato} {source_name} {name}",
        "key": "name",
    },
}

SNAPSHOT_SQL = (
    f"SELECT MAX(snapshot_date) AS d, COUNT(*) AS n FROM {_V}.v_drive_inventory_current"
)
COVERAGE_SQL = f"SELECT * FROM {_V}.v_drive_coverage ORDER BY root_key"


def _error_summary(error: Exception) -> str:
    return str(error).splitlines()[0] if str(error) else type(error).__name__


@dataclass
class DriveCheck:
    name: str
    label: str
    count: int  # per i duplicati: gruppi distinti, non righe
    rows: list[dict] = field(default_factory=list)


@dataclass
class DriveHealth:
    snapshot_date: str | None
    objects: int
    checks: list[DriveCheck]
    error: str | None = None
    coverage: list[dict] = field(default_factory=list)
    age_days: int | None = None
    warnings: list[str] = field(default_factory=list)


def compute(
    query: Callable[[str], list[dict]],
    *,
    today: date | None = None,
    expected_roots: dict[str, str] | None = None,
) -> DriveHealth:
    try:
        meta = query(SNAPSHOT_SQL)
    except Exception as e:  # noqa: BLE001 — tabella assente = job mai girato: si dice, non si esplode
        return DriveHealth(
            snapshot_date=None, objects=0, checks=[], error=_error_summary(e)
        )
    d = meta[0]["d"] if meta else None
    if d is None:
        return DriveHealth(snapshot_date=None, objects=0, checks=[])
    from core.freshness import today_rome

    age = ((today or today_rome()) - date.fromisoformat(str(d))).days
    checks: list[DriveCheck] = []
    errors = []
    warnings = []
    coverage = []
    if expected_roots is None:
        from core.drive_map import load_drive_map

        try:
            expected_roots = {k: r.id for k, r in load_drive_map().roots.items()}
        except (OSError, ValueError):
            warnings.append(
                "mappa corrente non disponibile: copertura configurata non verificabile"
            )
    try:
        coverage = query(COVERAGE_SQL)
        if not coverage:
            warnings.append("copertura per radice non disponibile")
        for root in coverage:
            if not root.get("observer_email"):
                warnings.append(
                    f"{root.get('root_key')}: identità osservatrice non disponibile"
                )
            if not root.get("permissions_observed") or root.get(
                "permissions_unknown", 0
            ):
                warnings.append(
                    f"{root.get('root_key')}: permessi non osservati, audit incompleto"
                )
        if expected_roots is not None:
            observed = {r.get("root_key"): r.get("root_file_id") for r in coverage}
            for key, root_id in expected_roots.items():
                if key not in observed or (
                    root_id != "root" and observed[key] != root_id
                ):
                    warnings.append(
                        f"{key}: radice configurata non coperta dalla fotografia"
                    )
            for key in observed.keys() - expected_roots.keys():
                warnings.append(
                    f"{key}: radice della fotografia non presente nella mappa corrente"
                )
    except Exception as e:  # noqa: BLE001 — unavailable state must stay explicit
        errors.append(f"copertura: {_error_summary(e)}")
    if age > 0:
        warnings.append(
            f"fotografia di {age} giorni fa; la data non è rinnovata dalla lettura"
        )
    for name, spec in CHECKS.items():
        try:
            rows = query(spec["sql"])
        except Exception as e:  # noqa: BLE001 — unavailable is not a zero
            errors.append(f"{name}: {_error_summary(e)}")
            continue
        distinct = len({r.get(spec["key"]) for r in rows})
        checks.append(
            DriveCheck(name=name, label=spec["label"], count=distinct, rows=rows)
        )
    return DriveHealth(
        snapshot_date=str(d),
        objects=int(meta[0]["n"]),
        checks=checks,
        error="; ".join(errors) or None,
        coverage=coverage,
        age_days=age,
        warnings=warnings,
    )


def render_text(h: DriveHealth, top: int = 3) -> str:
    out = ["  DRIVE"]
    if h.error:
        out.append(f"    ? inventario non disponibile — {h.error}")
        out.append("      esegui: python -m ingest.drive_inventory (job drive-audit)")
        return "\n".join(out)
    if h.snapshot_date is None:
        out.append(
            "    ? nessuna fotografia completa con copertura e provenienza disponibili"
        )
        return "\n".join(out)
    out.append(f"    fotografia {h.snapshot_date} · {h.objects} oggetti")
    for root in h.coverage:
        out.append(
            f"      radice {root.get('root_key')} ({root.get('root_file_id')}) · "
            f"{root.get('objects')} oggetti · osservatore {root.get('observer_email') or '?'}"
        )
    for warning in h.warnings:
        out.append(f"    ? {warning}")
    for c in h.checks:
        icon = "✓ " if c.count == 0 else ("🔴" if c.name == "permessi" else "! ")
        out.append(f"    {icon} {c.count:>3} {c.label}")
        if c.count:
            tmpl = CHECKS[c.name]["item"]
            seen = 0
            shown: set = set()
            for r in c.rows:
                k = r.get(CHECKS[c.name]["key"])
                if c.name == "duplicati" and k in shown:
                    continue
                shown.add(k)
                out.append(
                    "         "
                    + tmpl.format(
                        **{k2: (v if v is not None else "-") for k2, v in r.items()}
                    )
                )
                seen += 1
                if seen >= top:
                    break
            if c.count > seen:
                out.append(f"         … altri {c.count - seen}")
    return "\n".join(out)


def to_json(h: DriveHealth) -> dict:
    return {
        "snapshot_date": h.snapshot_date,
        "objects": h.objects,
        "error": h.error,
        "coverage": h.coverage,
        "age_days": h.age_days,
        "warnings": h.warnings,
        "checks": [
            {"name": c.name, "label": c.label, "count": c.count, "rows": c.rows}
            for c in h.checks
        ],
    }
