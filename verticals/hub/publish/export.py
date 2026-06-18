"""Export read-only BQ → JSON per il viewer static-edge.

NON scrive in BQ, non tocca lineage: solo freshness da BQ. Il JSON è
output di presentazione derivato (rigenerabile), non una fonte. Contratto versionato
(`schema`) così il frontend non si rompe quando l'output evolve.
"""

from __future__ import annotations

import json
from pathlib import Path

from verticals.hub.freshness import semaforo

# Soglie freshness coerenti con la home Streamlit (grain mensile per F&B).
_FB_ATT, _FB_ALL = 35, 70
_REV_ATT, _REV_ALL = 7, 14


def shape_meta(generated_at: str, fresh: dict) -> dict:
    """Freshness per superficie → _meta.json (semaforo precomputato lato export)."""
    fb_g = fresh["fb"]["giorni"]
    rev_g = fresh["reviews"]["giorni"]
    return {
        "schema": 1,
        "generated_at": generated_at,
        "surfaces": {
            "fb": {"giorni": fb_g, "semaforo": semaforo(fb_g, _FB_ATT, _FB_ALL)},
            "reviews": {
                "giorni": rev_g,
                "semaforo": semaforo(rev_g, _REV_ATT, _REV_ALL),
                "media_mese": fresh["reviews"].get("media_mese"),
            },
        },
    }


def export_all(out_dir: str, generated_at: str, dry_run: bool = False) -> dict:
    """Genera _meta.json. Ritorna {nome: dict} per ispezione/dry-run."""
    from verticals.hub.freshness import carica_freshness

    fresh = carica_freshness()
    payloads = {
        "_meta": shape_meta(generated_at, fresh),
    }
    if not dry_run:
        data_dir = Path(out_dir) / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        for name, payload in payloads.items():
            (data_dir / f"{name}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    return payloads
