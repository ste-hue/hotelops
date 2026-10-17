"""Sezione DRIVE di `hotelops health`: le quattro viste v_drive_* lette e rese.
Spec: docs/superpowers/specs/2026-10-17-drive-agent-friendly-design.md.

Stesso disegno di core/freshness.py: una `query` iniettata (sql → list[dict]),
funzioni pure sopra. Nessun client BigQuery qui dentro.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

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
        "label": "oggetti visibili fuori",
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
    f"SELECT MAX(snapshot_date) AS d, COUNT(*) AS n FROM {_V}.f_drive_inventory"
)


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


def compute(query: Callable[[str], list[dict]]) -> DriveHealth:
    try:
        meta = query(SNAPSHOT_SQL)
    except Exception as e:  # noqa: BLE001 — tabella assente = job mai girato: si dice, non si esplode
        return DriveHealth(
            snapshot_date=None, objects=0, checks=[], error=str(e).splitlines()[0]
        )
    d = meta[0]["d"] if meta else None
    if d is None:
        return DriveHealth(snapshot_date=None, objects=0, checks=[])
    checks: list[DriveCheck] = []
    for name, spec in CHECKS.items():
        rows = query(spec["sql"])
        distinct = len({r.get(spec["key"]) for r in rows})
        checks.append(
            DriveCheck(name=name, label=spec["label"], count=distinct, rows=rows)
        )
    return DriveHealth(snapshot_date=str(d), objects=int(meta[0]["n"]), checks=checks)


def render_text(h: DriveHealth, top: int = 3) -> str:
    out = ["  DRIVE"]
    if h.error:
        out.append(f"    ? inventario non disponibile — {h.error}")
        out.append("      esegui: python -m ingest.drive_inventory (job drive-audit)")
        return "\n".join(out)
    if h.snapshot_date is None:
        out.append(
            "    ? nessuna fotografia in f_drive_inventory: il job drive-audit non è mai girato"
        )
        return "\n".join(out)
    out.append(f"    fotografia {h.snapshot_date} · {h.objects} oggetti")
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
        "checks": [
            {"name": c.name, "label": c.label, "count": c.count, "rows": c.rows}
            for c in h.checks
        ],
    }
