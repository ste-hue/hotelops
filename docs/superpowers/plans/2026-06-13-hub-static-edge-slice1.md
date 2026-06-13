# Hub static-edge — Slice 1 (front-door + F&B) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use `- [ ]`.

**Goal:** Sito statico Cloudflare (landing brandizzata + freshness + card Mutui + pagina F&B)
alimentato da un export read-only BQ→JSON. È ciò che si manda al direttore.

**Architecture:** `hotelops publish-export` legge le viste BQ (read-only) e scrive
`verticals/hub/publish/site/data/{_meta,fb}.json`. Il sito statico (`site/`, modello
`app-mutui`: index.html + css + js + data) li fetcha e disegna con i token Panorama +
Chart.js. Deploy manuale via `wrangler pages deploy` (Stefano, login interattivo).

**Tech Stack:** Python (google-cloud-bigquery via `core.bq.client`), HTML/CSS/JS vanilla,
Chart.js (CDN), Cloudflare Pages.

---

## File Structure

- `verticals/hub/publish/__init__.py` — package
- `verticals/hub/publish/export.py` — shapers puri (`shape_fb`, `shape_meta`) + wrapper BQ (`export_all`)
- `verticals/hub/publish/site/index.html` — landing + sezione F&B
- `verticals/hub/publish/site/css/panorama.css` — token brand (mirror di theme.py)
- `verticals/hub/publish/site/js/app.js` — fetch JSON + render card/grafici
- `verticals/hub/publish/site/data/.gitkeep` — dir output (JSON generati, gitignored)
- `cli.py` — registra `publish-export`
- `tests/test_hub_publish.py` — shape contracts (offline, righe sintetiche)
- `.gitignore` — ignora `verticals/hub/publish/site/data/*.json`

---

### Task 1: Exporter — shapers puri + wrapper BQ

**Files:**
- Create: `verticals/hub/publish/__init__.py` (vuoto)
- Create: `verticals/hub/publish/export.py`
- Test: `tests/test_hub_publish.py`

- [ ] **Step 1: Test dei shaper (righe sintetiche, no BQ)**

```python
# tests/test_hub_publish.py
from verticals.hub.publish.export import shape_fb, shape_meta


def test_shape_fb_contract():
    rows = [
        {"anno": 2026, "mese": 5, "periodo": "2026-05-01",
         "ricavi_fb_totali": 100.0, "costo_fb_totale": 30.0,
         "food_cost_pct_ristorante": 0.28, "food_cost_pct_bar": 0.22,
         "euro_per_pasto": 4.5, "coperti_hotel": 600},
    ]
    out = shape_fb(rows)
    assert out["schema"] == 1
    assert out["serie"][0]["periodo"] == "2026-05-01"
    assert out["serie"][0]["food_cost_pct_ristorante"] == 0.28
    import json
    json.dumps(out)  # dev'essere JSON-serializzabile


def test_shape_meta_contract():
    out = shape_meta(
        generated_at="2026-06-13T03:00:00Z",
        fresh={"fb": {"giorni": 12}, "reviews": {"giorni": 2, "media_mese": 8.0}},
    )
    assert out["schema"] == 1
    assert out["generated_at"] == "2026-06-13T03:00:00Z"
    assert out["surfaces"]["fb"]["semaforo"] in ("🟢", "🟡", "🔴")
    assert out["surfaces"]["reviews"]["media_mese"] == 8.0
```

- [ ] **Step 2: Run → FAIL** `pytest tests/test_hub_publish.py -q` → ImportError.

- [ ] **Step 3: Implementa `export.py`**

```python
"""Export read-only BQ → JSON per il viewer static-edge (slice 1).

NON scrive in BQ, non tocca lineage: solo SELECT sulle viste canoniche. I JSON sono
output di presentazione derivati (rigenerabili), non una fonte. Contratto versionato
(`schema`) così il frontend non si rompe quando l'output evolve.
"""

from __future__ import annotations

import json
from pathlib import Path

from verticals.hub.freshness import semaforo

# Soglie freshness coerenti con la home Streamlit (grain mensile per F&B).
_FB_ATT, _FB_ALL = 35, 70
_REV_ATT, _REV_ALL = 7, 14

_FB_FIELDS = (
    "anno", "mese", "periodo",
    "ricavi_breakfast", "ricavi_food", "ricavi_beverage", "ricavi_fb_totali",
    "costo_breakfast", "costo_ristorante", "costo_bar", "costo_fb_totale",
    "pax_breakfast", "pax_lunch", "pax_dinner", "coperti_hotel",
    "food_cost_pct_breakfast", "food_cost_pct_ristorante", "food_cost_pct_bar",
    "food_cost_pct", "euro_per_pasto",
    "ricavi_fb_totali_ap", "costo_fb_totale_ap", "coperti_hotel_ap",
)


def shape_fb(rows: list[dict]) -> dict:
    """Righe v_fb_kpi → contratto JSON F&B. Tollera campi mancanti (None)."""
    serie = [{k: r.get(k) for k in _FB_FIELDS} for r in rows]
    return {"schema": 1, "serie": serie}


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


def _fb_rows_from_bq(client) -> list[dict]:
    q = """
    SELECT * FROM `hotelops-suite.hotelops.v_fb_kpi`
    WHERE anno >= 2025 ORDER BY anno, mese
    """
    out = []
    for r in client.query(q).result():
        d = dict(r.items())
        # date/Decimal → JSON-safe
        if d.get("periodo") is not None:
            d["periodo"] = d["periodo"].isoformat()
        out.append({k: (float(v) if hasattr(v, "is_integer") or _is_decimal(v) else v)
                    for k, v in d.items()})
    return out


def _is_decimal(v) -> bool:
    import decimal
    return isinstance(v, decimal.Decimal)


def export_all(out_dir: str, generated_at: str, dry_run: bool = False) -> dict:
    """Genera tutti i JSON. Ritorna {nome: dict} per ispezione/dry-run."""
    from core.bq.client import get_client
    from verticals.hub.freshness import carica_freshness

    client = get_client()
    fresh = carica_freshness()  # riusa le query provate; usiamo solo fb+reviews
    payloads = {
        "_meta": shape_meta(generated_at, fresh),
        "fb": shape_fb(_fb_rows_from_bq(client)),
    }
    if not dry_run:
        data_dir = Path(out_dir) / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        for name, payload in payloads.items():
            (data_dir / f"{name}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    return payloads
```

- [ ] **Step 4: Run → PASS** `pytest tests/test_hub_publish.py -q`.

- [ ] **Step 5: Commit** `feat(hub): exporter read-only BQ→JSON per viewer static-edge`

---

### Task 2: CLI `publish-export`

**Files:**
- Modify: `cli.py` (aggiungi subcommand)

- [ ] **Step 1: Aggiungi handler + parser**

Nel punto dove gli altri subcommand sono registrati, aggiungi:

```python
def cmd_publish_export(args):
    from datetime import datetime, timezone
    from verticals.hub.publish.export import export_all

    site = args.out or "verticals/hub/publish/site"
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payloads = export_all(site, gen, dry_run=args.dry_run)
    for name, p in payloads.items():
        n = len(p.get("serie", [])) if "serie" in p else "-"
        print(f"{name}.json  ({'serie '+str(n) if n != '-' else 'meta'})")
    print("DRY-RUN (nessun file scritto)" if args.dry_run else f"scritti in {site}/data/")
```

Registrazione parser (mirror dello stile esistente):

```python
p_pub = sub.add_parser("publish-export", help="Export read-only BQ→JSON per viewer static-edge")
p_pub.add_argument("--out", default=None, help="Dir del sito (default verticals/hub/publish/site)")
p_pub.add_argument("--dry-run", action="store_true")
p_pub.set_defaults(func=cmd_publish_export)
```

- [ ] **Step 2: Verifica live (success criterion)** — `hotelops publish-export --dry-run`
  stampa `_meta.json (meta)` e `fb.json (serie N)` con N>0. Conferma accesso BQ reale.

- [ ] **Step 3: Genera per davvero** `hotelops publish-export` → scrive i 2 JSON in `site/data/`.

- [ ] **Step 4: Commit** `feat(hub): cli publish-export`

---

### Task 3: Sito statico (landing + F&B)

**Files:**
- Create: `verticals/hub/publish/site/index.html`
- Create: `verticals/hub/publish/site/css/panorama.css`
- Create: `verticals/hub/publish/site/js/app.js`
- Create: `verticals/hub/publish/site/data/.gitkeep`
- Modify: `.gitignore`

- [ ] **Step 1: `.gitignore`** — aggiungi `verticals/hub/publish/site/data/*.json`

- [ ] **Step 2: `panorama.css`** — token brand (mirror di `theme.py`): variabili
  `--pg-navy:#003764; --pg-sky:#57c1e8; --pg-azure:#00a8e1; --pg-teal:#00bfd6;
  --pg-gold:#ffd13f; --pg-coral:#ff7f2f; --pg-ivory:#fbf9f5; --pg-sand:#f3eee6;
  --pg-slate:#3a4750`, @import font Cinzel/Cormorant Garamond/Jost, eyebrow maiuscolo
  tracciato, header navy wordmark, card morbide bordo sabbia ombra calda, radii 16/24px.

- [ ] **Step 3: `index.html`** — `<head>` con CSS + Chart.js CDN; header
  `PANORAMA · Direzione`; riga semaforo (`#stato-dati`); griglia card
  (F&B con semaforo, Reviews con media, Mutui che linka
  `https://mutui-tracker.ste-dellapietra.workers.dev/`); sezione F&B con 2 `<canvas>`
  (food cost % ristorante/bar nel tempo; ricavi vs costi F&B mensili) + tabella ultimo mese.

- [ ] **Step 4: `app.js`** — `fetch('data/_meta.json')` → popola semaforo + card;
  `fetch('data/fb.json')` → 2 chart Chart.js coi colori token (navy/azure/coral) e
  tabella ultimo mese. Formattazione € e % italiana. Gestione errore esplicita se un
  fetch fallisce (`#stato-dati` → "dati non disponibili").

- [ ] **Step 5: Verifica locale** — `python -m http.server` nella dir `site/` e apri:
  semaforo popolato, 2 grafici disegnati, card Mutui clickabile. (Stefano verifica visivo.)

- [ ] **Step 6: Commit** `feat(hub): sito statico viewer — landing + F&B (slice 1)`

---

### Task 4: Deploy manuale (Stefano) + verifica

**Files:** nessuno (operazione, non codice)

- [ ] **Step 1: Login Cloudflare** (interattivo, Stefano):
  `! npx wrangler login`
- [ ] **Step 2: Deploy Pages:**
  `! npx wrangler pages deploy verticals/hub/publish/site --project-name hotelops-hub`
- [ ] **Step 3: Verifica** — apri l'URL `*.pages.dev` restituito: landing + F&B + Mutui ok.
- [ ] **Step 4: Annota** l'URL in STATUS.md e nelle domande aperte della spec (dominio/Access
  restano slice 2).

---

## Self-review

- **Spec coverage**: exporter read-only ✓, contratto JSON versionato ✓, sito modello app-mutui
  + token Panorama ✓, card Mutui linkata ✓, deploy manuale slice 1 ✓, Access/automazione
  rinviati a slice 2 (coerente con la spec) ✓.
- **Placeholder scan**: nessun TBD; codice completo nei task 1-2; task 3 è frontend descritto
  a livello di contratto (HTML/CSS/JS prodotti in esecuzione, non pseudo-codice da incollare).
- **Type consistency**: `shape_fb`/`shape_meta`/`export_all` coerenti tra test, modulo e CLI;
  i campi `_FB_FIELDS` sono un sottoinsieme reale delle colonne di `v_fb_kpi`.
- **Anti-goal**: niente logica di dominio nuova — l'export serializza viste esistenti.
```
