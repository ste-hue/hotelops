# CEO Cockpit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Una pagina su `ceo.panorama-host.com` che risponde a "cosa devo fare, firmare o rispondere, per società?" leggendo le PEC da vedere degli ultimi 30 giorni, rigenerata ogni notte da hotelops.

**Architecture:** hotelops produce l'artefatto (`verticals/ceo/build_cockpit.py`: query su tre viste/tabelle PEC → `data.json` + HTML self-contained) e lo spinge su un KV Cloudflare in coda al job `pec-fetch`. Il repo edge `panorama_apps/ceo/` è un Worker che serve il KV dietro Cloudflare Access con verifica JWT in-Worker (copia della forma di `panorama_apps/bilancini`). Nessuna data-API, nessun D1, sola lettura.

**Tech Stack:** Python 3.11 (google-cloud-bigquery, requests, pytest) lato hotelops; Cloudflare Workers JS module syntax, jose, vitest + @cloudflare/vitest-pool-workers, wrangler 4 lato edge.

**Spec:** `docs/superpowers/specs/2026-09-11-ceo-cockpit-design.md`

## Global Constraints

- Repo edge separato in `panorama_apps/ceo/`: **nessun codice condiviso** con hotelops (regola `panorama_apps/STATUS.md`).
- Il builder è una **copia** della forma di `verticals/condges/build_bilancini_artifact.py`, non un'astrazione condivisa (spec D6).
- `data_evento` in `f_pec_messages` è **DATETIME**: confronti con `DATETIME_SUB(CURRENT_DATETIME(), …)`, mai con TIMESTAMP.
- Finestra **30 giorni** (spec D4). Entità sempre e solo `PANEL_ENTITIES` = INTUR, ORTI, VIGNA, in quest'ordine, presenti anche a zero righe.
- "Da vedere" = `importance = 'ALTA'` **oppure** uno dei tre flag di novità **oppure** `stato = 'NON_CLASSIFICATO'` (messaggio senza classificazione corrente incluso).
- Il payload **non contiene `body_text`**.
- Staleness in evidenza sopra le **36 ore**.
- Access policy nominativa: solo `stefano@panoramagroup.it` (più le caselle personali già usate su HPAN26 se servono da telefono).
- Ogni write della pagina passa da `--push` sul KV; il Worker non ha contenuto baked.
- Commit atomici, stage per nome (mai `git add .`); il working tree di hotelops ha modifiche non correlate da non toccare.
- Regola hub: la pagina non è "fatta" senza il gate di lettura con dati reali (Task 7).

---

## File structure

**hotelops** (produttore):
- `core/config.py` — aggiunge `PANEL_DRIVE_FOLDER_IDS` accanto a `PANEL_ENTITIES` (id cartella Drive per società).
- `verticals/ceo/__init__.py` — package vuoto.
- `verticals/ceo/build_cockpit.py` — un file: `fetch_items`, `build_payload`, `render_html`, `load_push_env`, `push_to_kv`, `main`.
- `tests/test_ceo_cockpit.py` — test delle funzioni pure e del push mockato.
- `docs/superpowers/plans/2026-09-12-ceo-cockpit.md` (questo file) — riceve i comandi di deploy del job.

**panorama_apps/ceo** (edge, repo git nuovo):
- `package.json`, `.gitignore`, `wrangler.jsonc`, `vitest.config.js`
- `src/index.js` — router: `/` e `/data.json` da KV, 403/405/404/503.
- `src/access.js` — verifica JWT Access (copia identica di bilancini).
- `test/access.test.js`, `test/routes.test.js`
- `README.md`, `STATUS.md`, `docs/SPEC.md` (punta alla spec in hotelops)

**panorama_apps/STATUS.md** — registra `ceo/` e corregge il punto 7 del pattern.

---

### Task 1: Config — id cartelle Drive per società

**Files:**
- Modify: `core/config.py` (dopo `PANEL_ENTITIES`, riga ~95)
- Test: `tests/test_ceo_cockpit.py` (nuovo)

**Interfaces:**
- Produces: `PANEL_DRIVE_FOLDER_IDS: dict[str, str]` con esattamente le chiavi di `PANEL_ENTITIES`.

- [ ] **Step 1: Write the failing test**

Crea `tests/test_ceo_cockpit.py`:

```python
"""Tests del builder CEO Cockpit (verticals/ceo/build_cockpit.py) — funzioni pure + push mockato."""

from core.config import PANEL_DRIVE_FOLDER_IDS, PANEL_ENTITIES


def test_panel_drive_folder_ids_cover_panel_entities():
    # Una entity nel pannello senza cartella Drive = link rotto in pagina.
    assert set(PANEL_DRIVE_FOLDER_IDS) == set(PANEL_ENTITIES)
    for v in PANEL_DRIVE_FOLDER_IDS.values():
        assert v and " " not in v
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_ceo_cockpit.py -v`
Expected: FAIL con `ImportError: cannot import name 'PANEL_DRIVE_FOLDER_IDS'`

- [ ] **Step 3: Add the mapping**

In `core/config.py`, subito dopo la riga `PANEL_ENTITIES = ["INTUR", "ORTI", "VIGNA"]`:

```python
# Cartelle Drive di AMM_CEO/<ENTITY> (id letti dal Drive il 2026-09-11). Servono
# al CEO Cockpit per il link "apri su Drive": hotelops non conosce i file id dei
# documenti proiettati (sync-panel scrive sul mirror locale), quindi il link è
# alla cartella della società.
PANEL_DRIVE_FOLDER_IDS = {
    "INTUR": "1I-Mn2s8o58m4urWVZioTF9MoUE8o1GN3",
    "ORTI": "1wb_43_BnvzBACDUvREKSTW_RO1eGyxgY",
    "VIGNA": "1jDb8X8CJS0RaMAps7B7SmqPW1qInsK7C",
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_ceo_cockpit.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add core/config.py tests/test_ceo_cockpit.py
git commit -m "feat(ceo): id cartelle Drive AMM_CEO per società (PANEL_DRIVE_FOLDER_IDS)"
```

---

### Task 2: Builder — `build_payload` (funzione pura)

**Files:**
- Create: `verticals/ceo/__init__.py` (vuoto)
- Create: `verticals/ceo/build_cockpit.py`
- Test: `tests/test_ceo_cockpit.py`

**Interfaces:**
- Consumes: `PANEL_ENTITIES`, `PANEL_DRIVE_FOLDER_IDS` da `core.config`.
- Produces:
  - `FINESTRA_GIORNI = 30`
  - `build_payload(rows: list[dict], generato_il: datetime) -> dict` — `rows` sono le righe della query di Task 3 (una per messaggio): chiavi `msgid, entity_id, data_evento (datetime), mittente, subject, primary_category, document_type, importance, stato, mittente_nuovo, oggetto_nuovo, allegati_nuovi, allegati (list[str]), documenti_pannello (list[str])`. Ritorna il contratto `data.json` della spec §4.2.
  - `motivi(row: dict) -> list[str]` — sottoinsieme ordinato di `["ALTA", "MITTENTE_NUOVO", "OGGETTO_NUOVO", "ALLEGATI_NUOVI", "NON_CLASSIFICATO"]`; lista vuota = routine.

- [ ] **Step 1: Write the failing tests**

Appendi a `tests/test_ceo_cockpit.py`:

```python
from datetime import datetime

from verticals.ceo.build_cockpit import FINESTRA_GIORNI, build_payload, motivi

GEN = datetime(2026, 9, 12, 4, 12, 0)


def _row(**over):
    base = {
        "msgid": "<m1@pec>", "entity_id": "INTUR",
        "data_evento": datetime(2026, 9, 9, 12, 21, 30),
        "mittente": "certpec.camcom.it", "subject": "Pratica M26716Q2609 evasa",
        "primary_category": "REGISTRO_IMPRESE", "document_type": "ALTRO",
        "importance": "NORMALE", "stato": "CLASSIFICATO",
        "mittente_nuovo": False, "oggetto_nuovo": False, "allegati_nuovi": False,
        "allegati": ["RicevutaRi.pdf"],
        "documenti_pannello": ["INTUR/PEC/Registro Imprese/2026-09 - RicevutaRi.pdf"],
    }
    base.update(over)
    return base


def test_motivi_each_criterion():
    assert motivi(_row()) == []
    assert motivi(_row(importance="ALTA")) == ["ALTA"]
    assert motivi(_row(mittente_nuovo=True)) == ["MITTENTE_NUOVO"]
    assert motivi(_row(oggetto_nuovo=True)) == ["OGGETTO_NUOVO"]
    assert motivi(_row(allegati_nuovi=True)) == ["ALLEGATI_NUOVI"]
    assert motivi(_row(stato="NON_CLASSIFICATO")) == ["NON_CLASSIFICATO"]
    # messaggio mai classificato (LEFT JOIN vuoto): stato/importance None → non classificato
    assert motivi(_row(stato=None, importance=None)) == ["NON_CLASSIFICATO"]
    assert motivi(_row(importance="ALTA", oggetto_nuovo=True)) == ["ALTA", "OGGETTO_NUOVO"]


def test_build_payload_three_entities_always_present():
    payload = build_payload([], GEN)
    assert payload["generato_il"] == "2026-09-12T04:12:00"
    assert payload["finestra_giorni"] == FINESTRA_GIORNI == 30
    assert [e["entity_id"] for e in payload["entita"]] == ["INTUR", "ORTI", "VIGNA"]
    for e in payload["entita"]:
        assert e["da_vedere"] == [] and e["routine"] == 0
        assert e["drive_folder_url"].startswith("https://drive.google.com/drive/folders/")


def test_build_payload_splits_da_vedere_and_routine_ordered_desc():
    rows = [
        _row(msgid="a", data_evento=datetime(2026, 9, 1, 10, 0), importance="ALTA"),
        _row(msgid="b", data_evento=datetime(2026, 9, 9, 10, 0), oggetto_nuovo=True),
        _row(msgid="c", data_evento=datetime(2026, 9, 5, 10, 0)),  # routine
        _row(msgid="d", entity_id="ORTI", data_evento=datetime(2026, 9, 3, 18, 31), stato="NON_CLASSIFICATO",
             primary_category=None, document_type=None, importance="DA_RIVEDERE"),
    ]
    payload = build_payload(rows, GEN)
    by_id = {e["entity_id"]: e for e in payload["entita"]}
    intur = by_id["INTUR"]
    assert [m["msgid"] for m in intur["da_vedere"]] == ["b", "a"]  # più recente prima
    assert intur["routine"] == 1
    assert intur["da_vedere"][0]["motivi"] == ["OGGETTO_NUOVO"]
    assert intur["da_vedere"][0]["data_evento"] == "2026-09-09T10:00:00"
    orti = by_id["ORTI"]
    assert orti["da_vedere"][0]["msgid"] == "d"
    assert orti["da_vedere"][0]["categoria"] is None
    assert orti["da_vedere"][0]["motivi"] == ["NON_CLASSIFICATO"]
    assert by_id["VIGNA"]["da_vedere"] == []


def test_build_payload_has_no_body_text_and_ignores_unknown_entity():
    rows = [_row(body_text="testo riservato"), _row(msgid="x", entity_id="STEFANO_PERSONALE", importance="ALTA")]
    payload = build_payload(rows, GEN)
    import json
    dumped = json.dumps(payload)
    assert "body_text" not in dumped and "testo riservato" not in dumped
    assert [e["entity_id"] for e in payload["entita"]] == ["INTUR", "ORTI", "VIGNA"]
    assert "x" not in dumped
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_ceo_cockpit.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'verticals.ceo'`

- [ ] **Step 3: Write the implementation**

`verticals/ceo/__init__.py`: file vuoto.

`verticals/ceo/build_cockpit.py`:

```python
#!/usr/bin/env python3
"""Builder del CEO Cockpit — "cosa devo fare, firmare o rispondere, per società?".

Legge le PEC in arrivo degli ultimi FINESTRA_GIORNI (v_pec_novita +
v_pec_classificazione_corrente + f_pec_panel_projections), produce data.json
+ HTML self-contained e, con --push, li carica nel KV del Worker
`panorama_apps/ceo`. Copia della forma di build_bilancini_artifact (spec
2026-09-11, D6): nessuna libreria condivisa.

Uso:
    python -m verticals.ceo.build_cockpit [--out PATH] [--push]
"""

import argparse
import html as html_mod
import json
import logging
from datetime import datetime
from pathlib import Path

from core.bq.client import get_client
from core.config import PANEL_DRIVE_FOLDER_IDS, PANEL_ENTITIES, PROJECT

DEFAULT_OUT = Path("docs/reports/artifacts/ceo_cockpit.html")
FINESTRA_GIORNI = 30
STALE_ORE = 36

_MOTIVI = (
    ("ALTA", lambda r: r.get("importance") == "ALTA"),
    ("MITTENTE_NUOVO", lambda r: bool(r.get("mittente_nuovo"))),
    ("OGGETTO_NUOVO", lambda r: bool(r.get("oggetto_nuovo"))),
    ("ALLEGATI_NUOVI", lambda r: bool(r.get("allegati_nuovi"))),
    ("NON_CLASSIFICATO", lambda r: r.get("stato") in (None, "NON_CLASSIFICATO")),
)


def motivi(row: dict) -> list[str]:
    """Criteri scattati, in ordine fisso. Vuoto = routine."""
    return [nome for nome, test in _MOTIVI if test(row)]


def _item(row: dict) -> dict:
    return {
        "msgid": row["msgid"],
        "data_evento": row["data_evento"].isoformat(),
        "mittente": row.get("mittente"),
        "subject": row.get("subject"),
        "categoria": row.get("primary_category"),
        "document_type": row.get("document_type"),
        "importance": row.get("importance"),
        "stato": row.get("stato") or "NON_CLASSIFICATO",
        "motivi": motivi(row),
        "allegati": list(row.get("allegati") or []),
        "documenti_pannello": list(row.get("documenti_pannello") or []),
    }


def build_payload(rows: list[dict], generato_il: datetime) -> dict:
    """Contratto data.json (spec §4.2). Entità = PANEL_ENTITIES, sempre presenti."""
    entita = []
    for entity_id in PANEL_ENTITIES:
        mine = sorted(
            (r for r in rows if r.get("entity_id") == entity_id),
            key=lambda r: r["data_evento"], reverse=True,
        )
        da_vedere = [_item(r) for r in mine if motivi(r)]
        entita.append({
            "entity_id": entity_id,
            "drive_folder_url": f"https://drive.google.com/drive/folders/{PANEL_DRIVE_FOLDER_IDS[entity_id]}",
            "da_vedere": da_vedere,
            "routine": len(mine) - len(da_vedere),
        })
    return {
        "generato_il": generato_il.replace(microsecond=0).isoformat(),
        "finestra_giorni": FINESTRA_GIORNI,
        "entita": entita,
    }
```

(`html_mod`, `logging`, `argparse`, `get_client`, `PROJECT`, `DEFAULT_OUT`, `STALE_ORE` vengono usati nei Task 3-4: lasciali, ruff segnala import inutilizzati solo se restano tali a fine Task 4.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_ceo_cockpit.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add verticals/ceo/__init__.py verticals/ceo/build_cockpit.py tests/test_ceo_cockpit.py
git commit -m "feat(ceo): build_payload del CEO Cockpit — da vedere/routine per società, motivi espliciti"
```

---

### Task 3: Builder — query BigQuery `fetch_items`

**Files:**
- Modify: `verticals/ceo/build_cockpit.py`
- Test: `tests/test_ceo_cockpit.py`

**Interfaces:**
- Produces: `SQL_ITEMS: str` (query, formattata con `PROJECT` e `FINESTRA_GIORNI`) e `fetch_items(client) -> list[dict]` con le chiavi elencate in Task 2.

Nota: il test non tocca BigQuery — verifica il testo della query (le trappole note: DATETIME, filtro finestra, LEFT JOIN) e il mapping delle righe con un client finto.

- [ ] **Step 1: Write the failing tests**

Appendi a `tests/test_ceo_cockpit.py`:

```python
from verticals.ceo.build_cockpit import SQL_ITEMS, fetch_items


def test_sql_items_uses_datetime_window_and_left_joins():
    # data_evento è DATETIME: un confronto con TIMESTAMP esplode in BQ (visto in design).
    assert "DATETIME_SUB(CURRENT_DATETIME(), INTERVAL 30 DAY)" in SQL_ITEMS
    assert "TIMESTAMP_SUB" not in SQL_ITEMS
    assert "v_pec_novita" in SQL_ITEMS
    assert "LEFT JOIN" in SQL_ITEMS and "v_pec_classificazione_corrente" in SQL_ITEMS
    assert "f_pec_panel_projections" in SQL_ITEMS and "'COPIED'" in SQL_ITEMS
    assert "body_text" not in SQL_ITEMS


class _FakeRow(dict):
    pass


class _FakeClient:
    def __init__(self, rows):
        self._rows = rows
        self.sql = None

    def query(self, sql):
        self.sql = sql
        rows = self._rows

        class _Job:
            def result(self_inner):
                return iter(rows)

        return _Job()


def test_fetch_items_maps_rows_to_dicts():
    client = _FakeClient([_FakeRow(msgid="m", entity_id="INTUR", allegati=["a.pdf"], documenti_pannello=[])])
    out = fetch_items(client)
    assert client.sql == SQL_ITEMS
    assert out == [{"msgid": "m", "entity_id": "INTUR", "allegati": ["a.pdf"], "documenti_pannello": []}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_ceo_cockpit.py -v`
Expected: FAIL con `ImportError: cannot import name 'SQL_ITEMS'`

- [ ] **Step 3: Write the query and fetch**

Aggiungi a `verticals/ceo/build_cockpit.py`, dopo `STALE_ORE`:

```python
# Base: v_pec_novita (già solo POSTA_CERTIFICATA in RECEIVED, con i tre flag di
# novità relativi al mittente). LEFT JOIN sulla classificazione corrente (un
# messaggio senza riga = non classificato) e sui documenti proiettati sul
# pannello (status COPIED, aggregati). Nessun body_text: la pagina è un indice.
SQL_ITEMS = f"""
WITH pannello AS (
  SELECT msgid, ARRAY_AGG(destination_path ORDER BY destination_path) AS documenti_pannello
  FROM `{PROJECT}.hotelops.f_pec_panel_projections`
  WHERE status = 'COPIED'
  GROUP BY msgid
)
SELECT
  n.msgid, n.entity_id, n.data_evento, n.mittente, n.subject,
  k.primary_category, k.document_type, k.importance, k.stato,
  n.mittente_nuovo, n.oggetto_nuovo, n.allegati_nuovi,
  n.allegati,
  IFNULL(p.documenti_pannello, []) AS documenti_pannello
FROM `{PROJECT}.hotelops.v_pec_novita` n
LEFT JOIN `{PROJECT}.hotelops.v_pec_classificazione_corrente` k USING (msgid)
LEFT JOIN pannello p USING (msgid)
WHERE n.data_evento >= DATETIME_SUB(CURRENT_DATETIME(), INTERVAL {FINESTRA_GIORNI} DAY)
"""


def fetch_items(client) -> list[dict]:
    return [dict(r) for r in client.query(SQL_ITEMS).result()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_ceo_cockpit.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Smoke reale della query (solo lettura, BigQuery)**

Run:
```bash
.venv/bin/python -c "
from core.bq.client import get_client
from verticals.ceo.build_cockpit import fetch_items, build_payload, motivi
from datetime import datetime
rows = fetch_items(get_client())
p = build_payload(rows, datetime.now())
for e in p['entita']: print(e['entity_id'], 'in arrivo', len(e['da_vedere'])+e['routine'], 'da vedere', len(e['da_vedere']))
"
```
Expected: tre righe, una per società, numeri ≥ 0 e nessun errore. Il 2026-09-11 la stessa logica dava INTUR 5/5, ORTI 2/1, VIGNA 1/1: i numeri scorrono con la finestra, conta che la query giri e che le tre società compaiano.

- [ ] **Step 6: Commit**

```bash
git add verticals/ceo/build_cockpit.py tests/test_ceo_cockpit.py
git commit -m "feat(ceo): query PEC da vedere (novità + classificazione corrente + pannello) su finestra 30 giorni"
```

---

### Task 4: Builder — `render_html`, push KV, `main`

**Files:**
- Modify: `verticals/ceo/build_cockpit.py`
- Test: `tests/test_ceo_cockpit.py`

**Interfaces:**
- Produces:
  - `render_html(payload: dict, adesso: datetime | None = None) -> str` — HTML self-contained, nessuna richiesta esterna.
  - `PUSH_ENV_VARS = ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "CEO_KV_NAMESPACE_ID")`
  - `load_push_env() -> dict[str, str]` (RuntimeError se manca una variabile)
  - `push_to_kv(html: str, payload: dict, env: dict[str, str]) -> None` — PUT bulk, chiavi `html` e `data.json`; RuntimeError se la risposta non è `success`.
  - `main()` con `--out` e `--push`.

- [ ] **Step 1: Write the failing tests**

Appendi a `tests/test_ceo_cockpit.py`:

```python
import pytest

from verticals.ceo.build_cockpit import (
    PUSH_ENV_VARS,
    load_push_env,
    push_to_kv,
    render_html,
)

PUSH_ENV = {
    "CLOUDFLARE_API_TOKEN": "tok-test",
    "CLOUDFLARE_ACCOUNT_ID": "acc-123",
    "CEO_KV_NAMESPACE_ID": "ns-456",
}


def test_render_html_empty_payload_says_niente_da_vedere_three_times():
    html = render_html(build_payload([], GEN), adesso=GEN)
    assert html.count("niente da vedere") == 3
    for name in ("INTUR", "ORTI", "VIGNA"):
        assert name in html
    assert "<script src=" not in html and "https://cdn" not in html


def test_render_html_lists_items_with_motivi_and_no_body_text():
    rows = [_row(importance="ALTA", oggetto_nuovo=True, body_text="riservato")]
    html = render_html(build_payload(rows, GEN), adesso=GEN)
    assert "Pratica M26716Q2609 evasa" in html
    assert "certpec.camcom.it" in html
    assert "REGISTRO_IMPRESE" in html
    assert "ALTA" in html and "oggetto nuovo" in html
    assert "RicevutaRi.pdf" in html
    assert "riservato" not in html
    assert "https://drive.google.com/drive/folders/1I-Mn2s8o58m4urWVZioTF9MoUE8o1GN3" in html


def test_render_html_escapes_subject():
    rows = [_row(subject="<script>alert(1)</script>", importance="ALTA")]
    html = render_html(build_payload(rows, GEN), adesso=GEN)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_html_staleness_flag_over_36_hours():
    fresh = render_html(build_payload([], GEN), adesso=datetime(2026, 9, 12, 9, 0))
    stale = render_html(build_payload([], GEN), adesso=datetime(2026, 9, 14, 9, 0))
    assert 'class="testata stale"' not in fresh
    assert 'class="testata stale"' in stale
    assert "2 giorni fa" in stale
    # la pagina è statica: lo script inline ricalcola la staleness all'apertura
    assert 'data-generato="2026-09-12T04:12:00"' in stale
    assert "classList.toggle('stale',ore>36)" in stale


def test_render_html_shows_missing_panel_document():
    rows = [_row(importance="ALTA", documenti_pannello=[])]
    html = render_html(build_payload(rows, GEN), adesso=GEN)
    assert "non ancora sul pannello" in html


def test_load_push_env_missing_raises(monkeypatch):
    for k in PUSH_ENV_VARS:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(RuntimeError, match="CLOUDFLARE_API_TOKEN"):
        load_push_env()


def test_load_push_env_complete(monkeypatch):
    for k, v in PUSH_ENV.items():
        monkeypatch.setenv(k, v)
    assert load_push_env() == PUSH_ENV


class _FakeResp:
    def __init__(self, ok=True, success=True, status_code=200, text=""):
        self.ok = ok
        self.status_code = status_code
        self.text = text
        self._success = success

    def json(self):
        return {"success": self._success}


def test_push_to_kv_bulk_payload(monkeypatch):
    import requests

    calls = {}

    def fake_put(url, json=None, headers=None, timeout=None):
        calls.update(url=url, body=json, headers=headers, timeout=timeout)
        return _FakeResp()

    monkeypatch.setattr(requests, "put", fake_put)
    payload = build_payload([], GEN)
    html = render_html(payload, adesso=GEN)
    push_to_kv(html, payload, PUSH_ENV)

    assert calls["url"] == (
        "https://api.cloudflare.com/client/v4/accounts/acc-123"
        "/storage/kv/namespaces/ns-456/bulk"
    )
    assert calls["headers"]["Authorization"] == "Bearer tok-test"
    by_key = {e["key"]: e["value"] for e in calls["body"]}
    assert set(by_key) == {"html", "data.json"}
    assert by_key["html"] == html
    assert json.loads(by_key["data.json"]) == payload


def test_push_to_kv_api_error_raises(monkeypatch):
    import requests

    monkeypatch.setattr(
        requests, "put",
        lambda *a, **kw: _FakeResp(ok=False, success=False, status_code=403, text="forbidden"),
    )
    with pytest.raises(RuntimeError, match="403"):
        push_to_kv("<html>", build_payload([], GEN), PUSH_ENV)
```

Aggiungi `import json` in testa al file di test se non c'è già (Task 2 lo importava localmente: spostalo in testa).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_ceo_cockpit.py -v`
Expected: FAIL con `ImportError: cannot import name 'PUSH_ENV_VARS'`

- [ ] **Step 3: Write render, push, main**

Aggiungi a `verticals/ceo/build_cockpit.py`, dopo `fetch_items`:

```python
# ---------- render ----------

_LABEL_MOTIVO = {
    "ALTA": "ALTA",
    "MITTENTE_NUOVO": "mittente nuovo",
    "OGGETTO_NUOVO": "oggetto nuovo",
    "ALLEGATI_NUOVI": "allegati nuovi",
    "NON_CLASSIFICATO": "non classificato",
}

_CSS = """
:root{--ink:#1c1c1c;--muted:#6b6b6b;--line:#e3e0d8;--bg:#faf8f3;--card:#fff;--alta:#b3261e;--chip:#eeebe3;--stale:#fff3cd}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,Segoe UI,Helvetica,Arial,sans-serif}
main{max-width:1200px;margin:0 auto;padding:24px 16px}
.testata{display:flex;justify-content:space-between;align-items:baseline;gap:16px;flex-wrap:wrap;margin-bottom:20px;padding:8px 12px;border-radius:8px}
.testata h1{font-size:22px;margin:0;font-weight:600}.testata .quando{color:var(--muted)}
.testata.stale{background:var(--stale)}.testata.stale .quando{color:var(--alta);font-weight:600}
.colonne{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
.colonna{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
.colonna header{display:flex;justify-content:space-between;align-items:baseline;border-bottom:1px solid var(--line);padding-bottom:8px;margin-bottom:8px}
.colonna h2{font-size:17px;margin:0}.colonna header a{font-size:13px;color:var(--muted)}
.conteggio{font-size:13px;color:var(--muted)}
.riga{padding:10px 0;border-bottom:1px solid var(--line)}.riga:last-of-type{border-bottom:0}
.riga .meta{font-size:12px;color:var(--muted);display:flex;gap:8px;flex-wrap:wrap}
.riga .oggetto{font-weight:600;margin:2px 0}.riga .mittente{font-size:13px;color:var(--muted)}
.chip{display:inline-block;font-size:11px;padding:1px 7px;border-radius:10px;background:var(--chip);margin-right:4px}
.chip.alta{background:var(--alta);color:#fff}.cat{font-weight:600;letter-spacing:.02em}
.allegati{font-size:12px;margin-top:4px}.allegati .manca{color:var(--alta)}
.vuoto{color:var(--muted);font-style:italic;padding:12px 0}.routine{font-size:12px;color:var(--muted);margin-top:8px}
"""


def _quando(generato_il: datetime, adesso: datetime) -> tuple[str, bool]:
    ore = (adesso - generato_il).total_seconds() / 3600
    if ore < 24:
        return f"aggiornato oggi {generato_il:%H:%M}", ore > STALE_ORE
    giorni = int(ore // 24)
    return f"aggiornato {giorni} giorn{'o' if giorni == 1 else 'i'} fa", ore > STALE_ORE


def _riga(item: dict) -> str:
    e = html_mod.escape
    chips = "".join(
        f'<span class="chip{" alta" if m == "ALTA" else ""}">{e(_LABEL_MOTIVO[m])}</span>'
        for m in item["motivi"]
    )
    data = datetime.fromisoformat(item["data_evento"]).strftime("%d/%m %H:%M")
    cat = e(item["categoria"] or "—")
    allegati = ", ".join(e(a) for a in item["allegati"]) or "nessun allegato"
    if item["allegati"] and not item["documenti_pannello"]:
        allegati += ' <span class="manca">· non ancora sul pannello</span>'
    return (
        '<div class="riga">'
        f'<div class="meta"><span>{data}</span><span class="cat">{cat}</span>{chips}</div>'
        f'<div class="oggetto">{e(item["subject"] or "(senza oggetto)")}</div>'
        f'<div class="mittente">{e(item["mittente"] or "mittente sconosciuto")}</div>'
        f'<div class="allegati">{allegati}</div>'
        "</div>"
    )


def _colonna(ent: dict) -> str:
    e = html_mod.escape
    n = len(ent["da_vedere"])
    corpo = "".join(_riga(i) for i in ent["da_vedere"]) or '<div class="vuoto">niente da vedere</div>'
    return (
        '<section class="colonna">'
        f'<header><h2>{e(ent["entity_id"])} <span class="conteggio">{n} da vedere</span></h2>'
        f'<a href="{e(ent["drive_folder_url"])}" target="_blank" rel="noopener">apri su Drive ↗</a></header>'
        f"{corpo}"
        f'<div class="routine">+{ent["routine"]} di routine negli ultimi {FINESTRA_GIORNI} giorni</div>'
        "</section>"
    )


# La pagina è statica e viene renderizzata al momento del push: la staleness
# calcolata in Python vale solo come fallback senza JS. Lo script inline (nessuna
# richiesta esterna) la ricalcola all'apertura, così "3 giorni fa" resta vero
# anche se il job notturno smette di spingere.
_STALE_JS = """
(function(){var t=document.querySelector('.testata');if(!t)return;
var g=new Date(t.getAttribute('data-generato'));var ore=(Date.now()-g.getTime())/36e5;
var q=t.querySelector('.quando');var hh=String(g.getHours()).padStart(2,'0')+':'+String(g.getMinutes()).padStart(2,'0');
if(ore<24){q.textContent='aggiornato oggi '+hh;}else{var d=Math.floor(ore/24);q.textContent='aggiornato '+d+(d===1?' giorno':' giorni')+' fa';}
t.classList.toggle('stale',ore>%d);})();
""" % STALE_ORE


def render_html(payload: dict, adesso: datetime | None = None) -> str:
    """HTML self-contained: niente script esterni, niente fetch a runtime."""
    generato_il = datetime.fromisoformat(payload["generato_il"])
    quando, stale = _quando(generato_il, adesso or datetime.now())
    colonne = "".join(_colonna(ent) for ent in payload["entita"])
    return (
        "<!doctype html><html lang=\"it\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>Ufficio CEO · Gruppo Panorama</title>"
        f"<style>{_CSS}</style></head><body><main>"
        f'<div class="testata{" stale" if stale else ""}" data-generato="{payload["generato_il"]}">'
        "<h1>Ufficio CEO — cosa devo fare, firmare o rispondere</h1>"
        f'<span class="quando">{html_mod.escape(quando)}</span></div>'
        f'<div class="colonne">{colonne}</div>'
        f"</main><script>{_STALE_JS}</script></body></html>"
    )


# ---------- push KV (Cloudflare Worker "ceo", repo panorama_apps) ----------

PUSH_ENV_VARS = ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "CEO_KV_NAMESPACE_ID")


def load_push_env() -> dict[str, str]:
    """Credenziali push da os.environ (il chiamante carica il .env). Mancanti → RuntimeError."""
    import os

    env = {k: os.environ.get(k, "") for k in PUSH_ENV_VARS}
    missing = [k for k, v in env.items() if not v]
    if missing:
        raise RuntimeError(f"--push richiede variabili d'ambiente mancanti: {', '.join(missing)}")
    return env


def push_to_kv(html: str, payload: dict, env: dict[str, str]) -> None:
    """Carica html e data.json nel KV del Worker ceo (una PUT bulk)."""
    import requests

    url = (
        f"https://api.cloudflare.com/client/v4/accounts/{env['CLOUDFLARE_ACCOUNT_ID']}"
        f"/storage/kv/namespaces/{env['CEO_KV_NAMESPACE_ID']}/bulk"
    )
    body = [
        {"key": "html", "value": html},
        {"key": "data.json", "value": json.dumps(payload, ensure_ascii=False)},
    ]
    r = requests.put(
        url, json=body,
        headers={"Authorization": f"Bearer {env['CLOUDFLARE_API_TOKEN']}"},
        timeout=60,
    )
    if not (r.ok and r.json().get("success")):
        raise RuntimeError(f"Push KV fallito: HTTP {r.status_code} — {r.text[:500]}")


def main():
    ap = argparse.ArgumentParser(description="Build CEO Cockpit (PEC da vedere per società)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--push", action="store_true",
                    help="dopo il build, carica html/data.json nel KV del Worker ceo")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log = logging.getLogger("ceo_cockpit")

    push_env = None
    if args.push:
        from core.env import load_dotenv_file

        load_dotenv_file()
        push_env = load_push_env()  # fail-fast: env incompleta → errore PRIMA di toccare BQ

    rows = fetch_items(get_client())
    payload = build_payload(rows, datetime.now())
    html = render_html(payload)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")
    tot = sum(len(e["da_vedere"]) for e in payload["entita"])
    log.info(f"OK → {args.out} ({len(rows)} in arrivo, {tot} da vedere)")

    if push_env is not None:
        push_to_kv(html, payload, push_env)
        log.info("Push KV OK → chiavi html, data.json (ceo-content)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests + ruff**

Run: `.venv/bin/pytest tests/test_ceo_cockpit.py -v && .venv/bin/ruff check verticals/ceo tests/test_ceo_cockpit.py`
Expected: PASS (16 passed), ruff `All checks passed!` (se ruff segnala `E501` su `_CSS` o la SQL, aggiungi `# noqa: E501` sulla riga: non spezzare CSS/SQL).

- [ ] **Step 5: Build locale con dati reali e apri il file**

Run: `.venv/bin/python -m verticals.ceo.build_cockpit --out /tmp/ceo_cockpit.html && open /tmp/ceo_cockpit.html`
Expected: log `OK → /tmp/ceo_cockpit.html (N in arrivo, M da vedere)`; nel browser tre colonne, testata "aggiornato oggi HH:MM" non evidenziata. **Incolla uno screenshot in chat**: è la prima metà del gate di lettura (Task 7 chiude con l'URL pubblicato).

- [ ] **Step 6: Commit**

```bash
git add verticals/ceo/build_cockpit.py tests/test_ceo_cockpit.py
git commit -m "feat(ceo): render HTML self-contained + push KV + CLI del CEO Cockpit"
```

---

### Task 5: Repo edge `panorama_apps/ceo/` — Worker + test

> Repo git **nuovo** e separato. Tutto in `/Users/stefanodellapietra/dev/Projects/panorama_apps/ceo/`. I valori `REPLACE_AT_PROVISIONING` sono output del Task 6, non placeholder del piano: i test locali girano con quei valori fittizi (come fu per bilancini).

**Files:**
- Create: `package.json`, `.gitignore`, `wrangler.jsonc`, `vitest.config.js`, `src/index.js`, `src/access.js`, `test/access.test.js`, `test/routes.test.js`, `README.md`, `STATUS.md`, `docs/SPEC.md`

**Interfaces:**
- Consumes: chiavi KV `html`, `data.json` scritte da `push_to_kv` (Task 4).
- Produces: Worker `ceo` con route `GET /` (html) e `GET /data.json`.

- [ ] **Step 1: Scaffold**

```bash
mkdir -p /Users/stefanodellapietra/dev/Projects/panorama_apps/ceo/{src,test,docs}
cd /Users/stefanodellapietra/dev/Projects/panorama_apps/ceo && git init -b main
```

`package.json`:
```json
{
  "name": "ceo",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "wrangler dev",
    "deploy": "wrangler deploy",
    "test": "vitest run"
  },
  "dependencies": {
    "jose": "^6.2.3"
  },
  "devDependencies": {
    "@cloudflare/vitest-pool-workers": "^0.12.21",
    "vitest": "^3.2.6",
    "wrangler": "^4.107.0"
  }
}
```

`.gitignore`:
```
node_modules/
.wrangler/
.dev.vars
```

`wrangler.jsonc`:
```jsonc
{
  "name": "ceo",
  "main": "src/index.js",
  "compatibility_date": "2026-07-01",
  "compatibility_flags": ["nodejs_compat"],
  "workers_dev": false,
  "preview_urls": false,
  "routes": [
    { "pattern": "ceo.panorama-host.com", "custom_domain": true }
  ],
  "kv_namespaces": [
    { "binding": "CONTENT", "id": "REPLACE_AT_PROVISIONING" }
  ],
  "vars": {
    "ACCESS_TEAM_DOMAIN": "panoramagroup.cloudflareaccess.com",
    "ACCESS_AUD": "REPLACE_AT_PROVISIONING"
  }
}
```

`vitest.config.js`:
```js
import { defineWorkersConfig } from "@cloudflare/vitest-pool-workers/config";

export default defineWorkersConfig({
  test: {
    poolOptions: {
      workers: {
        wrangler: { configPath: "./wrangler.jsonc" },
      },
    },
  },
});
```

`src/access.js` (identico a bilancini):
```js
// Verifica indipendente del JWT di Cloudflare Access (defense in depth:
// il contenuto non deve essere raggiungibile aggirando Access all'edge).
import { createRemoteJWKSet, jwtVerify } from "jose";

let remoteJwks = null;

export async function verifyAccess(request, env, jwks) {
  if (env.DEV === "1") return { ok: true, email: "dev@local" };

  const token = request.headers.get("Cf-Access-Jwt-Assertion");
  if (!token) return { ok: false };
  // Config mancante = fail closed: jose SALTA il check audience se undefined.
  if (!env.ACCESS_TEAM_DOMAIN || !env.ACCESS_AUD) return { ok: false };

  const issuer = `https://${env.ACCESS_TEAM_DOMAIN}`;
  try {
    const keySet =
      jwks ?? (remoteJwks ??= createRemoteJWKSet(new URL(`${issuer}/cdn-cgi/access/certs`)));
    const { payload } = await jwtVerify(token, keySet, {
      issuer,
      audience: env.ACCESS_AUD,
    });
    return { ok: true, email: payload.email };
  } catch {
    return { ok: false };
  }
}
```

Run: `npm install`
Expected: `node_modules/` creato, nessun errore.

- [ ] **Step 2: Write the failing tests**

`test/access.test.js`:
```js
import { describe, it, expect } from "vitest";
import { generateKeyPair, exportJWK, SignJWT, createLocalJWKSet } from "jose";
import { verifyAccess } from "../src/access.js";

const TEAM = "panoramagroup.cloudflareaccess.com";
const AUD = "aud-test-123";
const envBase = { ACCESS_TEAM_DOMAIN: TEAM, ACCESS_AUD: AUD };

async function makeKeys() {
  const { publicKey, privateKey } = await generateKeyPair("RS256", { extractable: true });
  const jwk = await exportJWK(publicKey);
  jwk.alg = "RS256";
  jwk.kid = "test-key";
  return { jwks: createLocalJWKSet({ keys: [jwk] }), privateKey };
}

function reqWithToken(token) {
  return new Request("https://ceo.panorama-host.com/", {
    headers: token ? { "Cf-Access-Jwt-Assertion": token } : {},
  });
}

async function sign(privateKey, { iss = `https://${TEAM}`, aud = AUD, exp = "5m" } = {}) {
  return new SignJWT({ email: "stefano@panoramagroup.it" })
    .setProtectedHeader({ alg: "RS256", kid: "test-key" })
    .setIssuer(iss)
    .setAudience(aud)
    .setIssuedAt()
    .setExpirationTime(exp)
    .sign(privateKey);
}

describe("verifyAccess", () => {
  it("DEV=1 bypassa la verifica", async () => {
    const r = await verifyAccess(reqWithToken(null), { ...envBase, DEV: "1" });
    expect(r.ok).toBe(true);
  });

  it("senza header → ko", async () => {
    const { jwks } = await makeKeys();
    const r = await verifyAccess(reqWithToken(null), envBase, jwks);
    expect(r.ok).toBe(false);
  });

  it("token valido → ok con email", async () => {
    const { jwks, privateKey } = await makeKeys();
    const r = await verifyAccess(reqWithToken(await sign(privateKey)), envBase, jwks);
    expect(r.ok).toBe(true);
    expect(r.email).toBe("stefano@panoramagroup.it");
  });

  it("audience sbagliata → ko", async () => {
    const { jwks, privateKey } = await makeKeys();
    const token = await sign(privateKey, { aud: "altro-aud" });
    const r = await verifyAccess(reqWithToken(token), envBase, jwks);
    expect(r.ok).toBe(false);
  });

  it("issuer sbagliato → ko", async () => {
    const { jwks, privateKey } = await makeKeys();
    const token = await sign(privateKey, { iss: "https://malicious.example.com" });
    const r = await verifyAccess(reqWithToken(token), envBase, jwks);
    expect(r.ok).toBe(false);
  });

  it("token scaduto → ko", async () => {
    const { jwks, privateKey } = await makeKeys();
    const token = await sign(privateKey, { exp: "-1m" });
    const r = await verifyAccess(reqWithToken(token), envBase, jwks);
    expect(r.ok).toBe(false);
  });

  it("config mancante (ACCESS_AUD vuoto) → ko anche con token valido", async () => {
    const { jwks, privateKey } = await makeKeys();
    const r = await verifyAccess(
      reqWithToken(await sign(privateKey)),
      { ACCESS_TEAM_DOMAIN: TEAM, ACCESS_AUD: "" },
      jwks
    );
    expect(r.ok).toBe(false);
  });
});
```

`test/routes.test.js`:
```js
import { describe, it, expect, beforeEach } from "vitest";
import { env } from "cloudflare:test";
import worker from "../src/index.js";

// DEV=1 → verifyAccess bypassata: qui si testa il ROUTER.
const DEV_ENV = { ...env, DEV: "1" };

const HTML = "<!doctype html><html><body>ufficio ceo test</body></html>";
const JSON_DATA = '{"generato_il":"2026-09-12T04:12:00","finestra_giorni":30,"entita":[]}';

function fetchPath(path, e = DEV_ENV, init = {}) {
  return worker.fetch(new Request(`https://ceo.panorama-host.com${path}`, init), e);
}

async function seedKv() {
  await env.CONTENT.put("html", HTML);
  await env.CONTENT.put("data.json", JSON_DATA);
}

describe("router", () => {
  beforeEach(seedKv);

  it("senza JWT (no DEV) → 403 senza contenuto, no-store", async () => {
    const r = await fetchPath("/", { ...env, DEV: "0" });
    expect(r.status).toBe(403);
    expect(await r.text()).not.toContain("ufficio ceo test");
    expect(r.headers.get("Cache-Control")).toBe("private, no-store");
  });

  it("/ → 200 html", async () => {
    const r = await fetchPath("/");
    expect(r.status).toBe(200);
    expect(r.headers.get("Content-Type")).toBe("text/html; charset=utf-8");
    expect(await r.text()).toBe(HTML);
  });

  it("/data.json → 200 json", async () => {
    const r = await fetchPath("/data.json");
    expect(r.status).toBe(200);
    expect(r.headers.get("Content-Type")).toBe("application/json; charset=utf-8");
    expect(await r.text()).toBe(JSON_DATA);
  });

  it("ogni risposta 200 è no-store", async () => {
    for (const p of ["/", "/data.json"]) {
      const r = await fetchPath(p);
      expect(r.headers.get("Cache-Control")).toBe("private, no-store");
    }
  });

  it("path sconosciuto → 404", async () => {
    const r = await fetchPath("/altro");
    expect(r.status).toBe(404);
  });

  it("POST → 405", async () => {
    const r = await fetchPath("/", DEV_ENV, { method: "POST" });
    expect(r.status).toBe(405);
  });

  it("KV vuoto → 503 con istruzione di push", async () => {
    await env.CONTENT.delete("html");
    const r = await fetchPath("/");
    expect(r.status).toBe(503);
    expect(await r.text()).toContain("push");
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `npm test`
Expected: `access.test.js` PASS (7), `routes.test.js` FAIL con `Failed to resolve import "../src/index.js"`.

- [ ] **Step 4: Write the Worker**

`src/index.js`:
```js
// Worker ceo: serve da KV l'HTML/JSON generati dal builder hotelops
// (verticals/ceo/build_cockpit --push). Dati riservati: Access verificato
// in-Worker su ogni richiesta, nessuna risposta cacheabile.
import { verifyAccess } from "./access.js";

const ROUTES = {
  "/": { key: "html", type: "text/html; charset=utf-8" },
  "/data.json": { key: "data.json", type: "application/json; charset=utf-8" },
};

function resp(body, status, headers = {}) {
  return new Response(body, {
    status,
    headers: { "Cache-Control": "private, no-store", ...headers },
  });
}

export default {
  async fetch(request, env) {
    const auth = await verifyAccess(request, env);
    if (!auth.ok) return resp(null, 403);

    if (request.method !== "GET" && request.method !== "HEAD") return resp(null, 405);

    const route = ROUTES[new URL(request.url).pathname];
    if (!route) return resp("Not found", 404);

    const value = await env.CONTENT.get(route.key);
    if (value === null) {
      return resp(
        "Contenuto non ancora pubblicato: esegui il push dal builder hotelops (verticals.ceo.build_cockpit --push).",
        503,
        { "Content-Type": "text/plain; charset=utf-8" }
      );
    }

    return resp(value, 200, { "Content-Type": route.type });
  },
};
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `npm test`
Expected: 14 passed (7 access + 7 routes).

- [ ] **Step 6: Docs del repo**

`README.md`:
```markdown
# Ufficio CEO — edge app

Worker Cloudflare che serve "Ufficio CEO · Gruppo Panorama" (HTML self-contained
generato dal builder hotelops) dietro Cloudflare Access. **Dati riservati**: nessun
URL pubblico, policy nominativa (OTP email: Stefano).

Risponde a una sola domanda: *cosa devo fare, firmare o rispondere, per società?*
PEC in arrivo degli ultimi 30 giorni che sono ALTA, nuove rispetto al mittente o
non classificate, per INTUR / ORTI / VIGNA, con link alla cartella AMM_CEO su Drive.

- **URL**: https://ceo.panorama-host.com
- **Route**: `/` (pagina) · `/data.json`
- **Contenuto**: KV `ceo-content` (chiavi `html`, `data.json`) — aggiornato ogni notte
  dal job `pec-fetch` di hotelops (04:00), MAI baked nel deploy.
- **Difesa in profondità**: oltre ad Access all'edge, il Worker verifica in proprio
  il JWT `Cf-Access-Jwt-Assertion` (fail-closed: senza token valido → 403).

## Push manuale (da hotelops)

    .venv/bin/python -m verticals.ceo.build_cockpit --push

Env nel `.env` di hotelops: `CLOUDFLARE_API_TOKEN` (token scoped alla sola permission
"Workers KV Storage: Edit"), `CLOUDFLARE_ACCOUNT_ID`, `CEO_KV_NAMESPACE_ID`.

## Dev

    npm install
    npm test              # vitest: access (7) + router (7)
    npx wrangler deploy   # SOLO per modifiche al Worker (il contenuto va via push)

Il renderer vive in hotelops (`verticals/ceo/build_cockpit.py`): questo repo non lo
riscrive, lo serve. Spec: `docs/SPEC.md`.
```

`docs/SPEC.md`:
```markdown
# Spec

La spec di design vive nel repo produttore:
`hotelops/docs/superpowers/specs/2026-09-11-ceo-cockpit-design.md`.
Questo Worker implementa la §5 (pagina) lato serving; la pagina stessa è generata
da `hotelops/verticals/ceo/build_cockpit.py` (§4).
```

`STATUS.md`:
```markdown
# ceo — STATUS

**Last update:** 2026-09-12

## In corso
- v1: Worker + KV + Access; primo push dal builder hotelops.

## Completato di recente
- (vuoto)

## Decisioni aperte
- Stato "evasa" persistente (D1): dopo il gate di lettura, non prima.

## Rotto
- (vuoto)

## Prossimi passi
- Provisioning (KV, Access app, token) e primo push.
- Gate di lettura: pagina vista da Stefano con dati reali.
```

- [ ] **Step 7: Commit**

```bash
git add package.json package-lock.json .gitignore wrangler.jsonc vitest.config.js src/index.js src/access.js test/access.test.js test/routes.test.js README.md STATUS.md docs/SPEC.md
git commit -m "feat: Worker Ufficio CEO — serve html/data.json da KV dietro Access (pattern bilancini)"
```

---

### Task 6: Provisioning Cloudflare, secret nel job, primo push

> Task interattivo: richiede `wrangler` autenticato sull'account Cloudflare di Stefano, passi in dashboard Zero Trust, e `gcloud auth login` (al 2026-09-12 la CLI gcloud NON è autenticata su questa macchina). Niente TDD: la verifica è il comportamento in produzione.

**Files:**
- Modify: `panorama_apps/ceo/wrangler.jsonc` (id KV reale + ACCESS_AUD reale)
- Modify: `hotelops/.env` (non versionato) — `CEO_KV_NAMESPACE_ID`
- Modify (cloud): Cloud Run Job `pec-fetch` (command + secrets)

- [ ] **Step 1: KV namespace**

```bash
cd /Users/stefanodellapietra/dev/Projects/panorama_apps/ceo
npx wrangler kv namespace create ceo-content
```
Expected: output con l'id del namespace. Sostituisci `REPLACE_AT_PROVISIONING` in `wrangler.jsonc` → `kv_namespaces[0].id`.

- [ ] **Step 2: Primo deploy (senza AUD)**

Run: `npx wrangler deploy`
Expected: Worker `ceo` pubblicato su `ceo.panorama-host.com` (il dominio custom si crea da solo se la zona `panorama-host.com` è nell'account, come per bilancini). Aprendo l'URL ora si ottiene 403 (nessun JWT): corretto.

- [ ] **Step 3: Access application (dashboard Zero Trust, team panoramagroup)**

Zero Trust → Access → Applications → Add → Self-hosted:
- Name: `Ufficio CEO`, domain `ceo.panorama-host.com`
- Policy `ceo-nominativa`, action Allow, include **Emails**: `stefano@panoramagroup.it` (aggiungi `ste.dellapietra@gmail.com` / `stedepi@gmail.com` solo se servono da telefono, come su HPAN26). Identity provider: One-time PIN.
- Salva e copia l'**Application Audience (AUD) Tag** dalla pagina Overview dell'app.

- [ ] **Step 4: AUD nel wrangler.jsonc + redeploy**

Sostituisci `REPLACE_AT_PROVISIONING` di `vars.ACCESS_AUD` con l'AUD copiato.
Run: `npx wrangler deploy`
Expected: aprendo `https://ceo.panorama-host.com` → login OTP → **503 "Contenuto non ancora pubblicato"** (Access passa, KV vuoto). Un altro account → schermata Access negata.

- [ ] **Step 5: Token push + .env hotelops + primo push manuale**

Il token `CLOUDFLARE_API_TOKEN` già in `.env` di hotelops è scoped "Workers KV Storage: Edit" sull'account: vale anche per il namespace nuovo (la permission è a livello account). Aggiungi in `hotelops/.env`:
```
CEO_KV_NAMESPACE_ID=<id del passo 1>
```
Run (da hotelops):
```bash
.venv/bin/python -m verticals.ceo.build_cockpit --push
```
Expected: `Push KV OK → chiavi html, data.json (ceo-content)`. Ricarica `https://ceo.panorama-host.com` → la pagina con tre colonne. `https://ceo.panorama-host.com/data.json` → il JSON.

- [ ] **Step 6: Secret in GCP e aggancio al job `pec-fetch`**

```bash
gcloud auth login   # se non già fatto
P=hotelops-suite; R=europe-west1
printf '%s' "<CLOUDFLARE_API_TOKEN>" | gcloud secrets create cloudflare-kv-token --project=$P --data-file=- --replication-policy=automatic
printf '%s' "<CLOUDFLARE_ACCOUNT_ID>" | gcloud secrets create cloudflare-account-id --project=$P --data-file=- --replication-policy=automatic
printf '%s' "<CEO_KV_NAMESPACE_ID>" | gcloud secrets create ceo-kv-namespace-id --project=$P --data-file=- --replication-policy=automatic
# la SA del job deve poterli leggere: recupera la SA con
gcloud run jobs describe pec-fetch --project=$P --region=$R --format="value(spec.template.spec.template.spec.serviceAccountName)"
for s in cloudflare-kv-token cloudflare-account-id ceo-kv-namespace-id; do
  gcloud secrets add-iam-policy-binding $s --project=$P --member="serviceAccount:<SA>" --role=roles/secretmanager.secretAccessor
done
```

Poi il job: il comando attuale è `python -m ingest.pec_fetch --all && python -m cli pec classify` (plan 2026-08-04). Si ridistribuisce dall'immagine aggiornata (il builder nuovo deve essere nell'immagine `Dockerfile.jobs`):

```bash
gcloud run jobs deploy pec-fetch --project=$P --region=$R --source . \
  --command=/bin/sh \
  --args=-c,'python -m ingest.pec_fetch --all && python -m cli pec classify && python -m verticals.ceo.build_cockpit --push' \
  --update-secrets=CLOUDFLARE_API_TOKEN=cloudflare-kv-token:latest,CLOUDFLARE_ACCOUNT_ID=cloudflare-account-id:latest,CEO_KV_NAMESPACE_ID=ceo-kv-namespace-id:latest
```

Prima di lanciarlo, **conferma che `--source .` con `Dockerfile.jobs` sia il modo con cui il job è stato costruito finora** (`gcloud run jobs describe pec-fetch --format="value(spec.template.spec.template.spec.containers[0].image)"`): se l'immagine viene da un build separato (`gcloud builds submit -f Dockerfile.jobs`), ripeti quel build e usa `gcloud run jobs update pec-fetch --image=<img> --command=... --args=... --update-secrets=...`. Non cambiare i secret PEC esistenti (`--update-secrets` aggiunge, non sostituisce).

- [ ] **Step 7: Esecuzione di prova del job**

```bash
gcloud run jobs execute pec-fetch --project=$P --region=$R --wait
```
Expected: exit 0; nei log l'ultima riga `Push KV OK → chiavi html, data.json (ceo-content)`. Ricarica la pagina: la testata mostra l'orario del run.

- [ ] **Step 8: Commit (repo edge) e nota nel piano (hotelops)**

```bash
cd /Users/stefanodellapietra/dev/Projects/panorama_apps/ceo
git add wrangler.jsonc STATUS.md
git commit -m "chore: provisioning KV ceo-content + Access AUD; v1 live"
```
In `STATUS.md` di `ceo/` sposta "v1" in "Completato di recente" con URL e data.

Nel repo hotelops annota in questo piano (sezione sotto) i comandi eseguiti davvero, se diversi da quelli scritti:

```bash
cd /Users/stefanodellapietra/dev/Projects/hotelops
git add docs/superpowers/plans/2026-09-12-ceo-cockpit.md
git commit -m "docs(ceo): comandi di provisioning e deploy job eseguiti"
```

---

### Task 7: Registry `panorama_apps` e gate di lettura

**Files:**
- Modify: `panorama_apps/STATUS.md` (sezione "Progetti attivi" + punto 7 del pattern)
- Modify: `hotelops/STATUS.md` (riga di diario)

- [ ] **Step 1: Registra `ceo/` e correggi il pattern**

In `panorama_apps/STATUS.md`, dopo il blocco `bilancini/`, aggiungi:

```markdown
### `ceo/` 🟢 live
- **Stato**: v1 live — Ufficio CEO: PEC da vedere (ALTA / novità / non classificate) per INTUR·ORTI·VIGNA, ultimi 30 giorni
- **URL**: https://ceo.panorama-host.com (Access: solo Stefano, OTP nominativo)
- **Stack**: Cloudflare Worker + KV `ceo-content`; renderer in hotelops (`verticals/ceo/build_cockpit.py --push`), push automatico in coda al job `pec-fetch` (04:00)
- **Anti-pattern rispettato**: parla con hotelops solo via push KV (nessun codice condiviso)
- **Spec**: `hotelops/docs/superpowers/specs/2026-09-11-ceo-cockpit-design.md` · **Detail**: `panorama_apps/ceo/STATUS.md`
```

Sostituisci il punto 7 del pattern:
```markdown
7. Code = JS Worker senza framework + Cloudflare Access per le superfici edge (bilancini, HPAN26, reception, ceo — tutte le app live al 2026-09); Python/NiceGUI/Streamlit solo dove serve un runtime Python (reception v0). Il contenuto riservato arriva via push da hotelops, mai baked nel deploy.
```

Aggiorna `**Last update:**` a `2026-09-12`.

```bash
cd /Users/stefanodellapietra/dev/Projects/panorama_apps
git add STATUS.md
git commit -m "docs(status): registra ceo/ (Ufficio CEO) e corregge il pattern edge (Worker JS, non NiceGUI/Streamlit)"
```

(Se `panorama_apps/` non è un repo git ma una cartella di repo, salta il commit e lascia il file modificato.)

- [ ] **Step 2: Gate di lettura (Stefano, bloccante)**

Apri `https://ceo.panorama-host.com` con dati reali e rispondi in chat alla domanda della spec §8:

> *Tra le righe da vedere c'è qualcosa che avrei voluto sapere e non sapevo?*

- **Sì** → v1 chiusa; apri il thread v2 (stato "evasa" su D1) in `ceo/STATUS.md` → Decisioni aperte.
- **No, sono tutte cose già note da WhatsApp o dalla casella** → il cockpit è un duplicato: si ferma qui, si annota in `ceo/STATUS.md` e in `hotelops/STATUS.md`, il job continua a girare senza costo ma non si investe oltre.

- [ ] **Step 3: Diario hotelops**

In `hotelops/STATUS.md`, in testa al diario, una riga con: URL, esito del gate di lettura, i tre numeri del primo push (in arrivo / da vedere per società), e il fatto che il job `pec-fetch` ora spinge il cockpit. Poi:

```bash
cd /Users/stefanodellapietra/dev/Projects/hotelops
git add STATUS.md
git commit -m "docs(status): CEO Cockpit v1 live su ceo.panorama-host.com, esito gate di lettura"
```

(`STATUS.md` ha già modifiche locali non correlate: se il diff contiene altro, committa solo il hunk del cockpit con `git add -p STATUS.md`.)
