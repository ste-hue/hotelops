# HotelOps Hub Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold del hub (layer di presentazione Streamlit): home con card+freshness, pagine F&B/Reviews montate, pagina Ingest lineage-first. **Senza pagina Cassa** (bloccata dal P1 lotteria budget, vedi STATUS.md).

**Architecture:** App multipage `st.navigation` in `verticals/hub/`; zero logica di dominio nel hub; pagine sottili che montano i vertical. Ingest = unica superficie di scrittura (eccezione dichiarata in spec), chiama `classify`/`intake_file`/`promote_raw_object` direttamente.

**Tech Stack:** Streamlit 1.55, BigQuery, pytest. Spec: `docs/superpowers/specs/2026-06-12-hub-app-store-design.md`.

**Fatti verificati 2026-06-12:**
- `verticals/reviews/app.py`: corpo già in `main()` (set_page_config dentro, riga 51), `if __name__ == "__main__": main()` — import-safe.
- `verticals/condges/fb_dashboard.py` NON ancora su main (worktree fb-looker): `fb.py` degrada con messaggio.
- API: `classify(path) -> ClassificationResult` (`.category`, `.societa`, `.confidence`); `intake_file(path, source_name, actor) -> IntakeResult` (`.raw_object_id`, `.deduped`); `promote_raw_object(raw_object_id, actor) -> PromotionResult` (`.status`, `.rows_written`, `.reason`); `load_registry().resolve(detector_category, societa)`; `v_raw_objects_current` (`current_status`, `last_event_at`) JOIN `f_raw_objects` (`file_name_original`, `source_name`, `intake_at`).

---

### Task 1: render() importabile in verticals/reviews/app.py

**Files:**
- Modify: `verticals/reviews/app.py:50-51` (split main → render)
- Test: `tests/test_hub_mounts.py` (nuovo)

- [ ] **Step 1: Write the failing test**

```python
"""Hub — contratti di montaggio delle pagine."""


def test_reviews_render_importabile():
    from verticals.reviews.app import render, main

    assert callable(render)
    assert callable(main)


def test_reviews_render_non_chiama_set_page_config():
    # set_page_config deve stare SOLO in main() (contratto fb_dashboard):
    # render() montata dal hub non può richiamarlo (Streamlit lo vieta 2 volte).
    import inspect

    from verticals.reviews import app

    src = inspect.getsource(app.render)
    assert "set_page_config" not in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hub_mounts.py -v`
Expected: FAIL — `ImportError: cannot import name 'render'`

- [ ] **Step 3: Split main() in app.py**

In `verticals/reviews/app.py`, `def main():` (riga 50) diventa:

```python
def render():
    # <-- qui TUTTO il corpo attuale di main() TRANNE st.set_page_config(...)


def main():
    st.set_page_config(
        # <-- blocco set_page_config attuale, invariato
    )
    render()
```

(`if __name__ == "__main__": main()` a fondo file resta invariato; lo standalone
`streamlit run verticals/reviews/app.py` continua a funzionare identico.)

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_hub_mounts.py tests/test_reviews_schema.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add verticals/reviews/app.py tests/test_hub_mounts.py
git commit -m "refactor(reviews): estrae render() importabile dal hub (contratto fb_dashboard)"
```

---

### Task 2: freshness.py — semaforo puro + query

**Files:**
- Create: `verticals/hub/__init__.py` (vuoto), `verticals/hub/freshness.py`
- Test: `tests/test_hub_freshness.py` (nuovo)

- [ ] **Step 1: Write the failing tests**

```python
"""Hub — semaforo freshness."""

from verticals.hub.freshness import semaforo


def test_semaforo_verde_entro_soglia():
    assert semaforo(0) == "🟢"
    assert semaforo(3) == "🟢"


def test_semaforo_giallo_tra_soglie():
    assert semaforo(4) == "🟡"
    assert semaforo(7) == "🟡"


def test_semaforo_rosso_oltre_o_ignoto():
    assert semaforo(8) == "🔴"
    assert semaforo(None) == "🔴"


def test_semaforo_soglie_custom():
    assert semaforo(10, soglia_attenzione=15, soglia_allarme=30) == "🟢"
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_hub_freshness.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'verticals.hub'`

- [ ] **Step 3: Implement `verticals/hub/freshness.py`** (+ `__init__.py` vuoto)

```python
"""Freshness dei dati per le card della home (riusa le query di `hotelops health`)."""

from __future__ import annotations


def semaforo(
    giorni: int | None,
    soglia_attenzione: int = 3,
    soglia_allarme: int = 7,
) -> str:
    """Semaforo staleness: 🟢 entro attenzione, 🟡 entro allarme, 🔴 oltre o ignoto."""
    if giorni is None:
        return "🔴"
    if giorni <= soglia_attenzione:
        return "🟢"
    if giorni <= soglia_allarme:
        return "🟡"
    return "🔴"


def carica_freshness() -> dict:
    """Una riga per card: giorni dall'ultimo dato + numero chiave. Query BQ live."""
    from core.bq.client import get_client

    client = get_client()
    out: dict = {}

    q_fb = """
    SELECT DATE_DIFF(CURRENT_DATE('Europe/Rome'), MAX(data), DAY) AS giorni
    FROM `hotelops-suite.hotelops.f_consumi_economato`
    """
    out["fb"] = {"giorni": next(iter(client.query(q_fb).result())).giorni}

    q_rev = """
    SELECT
      DATE_DIFF(CURRENT_DATE('Europe/Rome'),
                MAX(PARSE_DATE('%Y-%m-%d', data_review)), DAY) AS giorni,
      ROUND(AVG(IF(PARSE_DATE('%Y-%m-%d', data_review) >=
                   DATE_TRUNC(CURRENT_DATE('Europe/Rome'), MONTH),
                   punteggio_norm, NULL)), 1) AS media_mese
    FROM `hotelops-suite.hotelops.f_reviews`
    """
    r = next(iter(client.query(q_rev).result()))
    out["reviews"] = {"giorni": r.giorni, "media_mese": r.media_mese}

    q_ing = """
    SELECT COUNTIF(current_status != 'PROMOTED') AS in_coda
    FROM `hotelops-suite.hotelops.v_raw_objects_current`
    """
    out["ingest"] = {"in_coda": next(iter(client.query(q_ing).result())).in_coda}

    return out
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_hub_freshness.py -v`
Expected: 4 PASS (i test toccano solo `semaforo`, niente BQ)

- [ ] **Step 5: Commit**

```bash
git add verticals/hub/__init__.py verticals/hub/freshness.py tests/test_hub_freshness.py
git commit -m "feat(hub): freshness — semaforo puro + query per card"
```

---

### Task 3: scaffold app.py + home.py + pagine fb/reviews

**Files:**
- Create: `verticals/hub/app.py`, `verticals/hub/home.py`,
  `verticals/hub/pages_/__init__.py` (vuoto), `verticals/hub/pages_/fb.py`,
  `verticals/hub/pages_/reviews.py`
- Test: `tests/test_hub_mounts.py` (append)

- [ ] **Step 1: Write the failing tests** (append a `tests/test_hub_mounts.py`)

```python
def test_pagine_hub_importabili():
    from verticals.hub import home
    from verticals.hub.pages_ import fb, reviews

    assert callable(home.render)
    assert callable(fb.render)
    assert callable(reviews.render)


def test_fb_degrada_senza_fb_dashboard():
    # fb_dashboard non è ancora su main: l'import della PAGINA non deve esplodere
    # (il fallback vive dentro render(), non a import-time).
    import importlib

    from verticals.hub.pages_ import fb

    importlib.reload(fb)
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_hub_mounts.py -v`
Expected: FAIL — `ModuleNotFoundError` sui nuovi moduli

- [ ] **Step 3: Implement**

`verticals/hub/pages_/fb.py`:

```python
"""Pagina F&B — monta verticals.condges.fb_dashboard.render() (worktree fb-looker)."""

import streamlit as st


def render():
    try:
        from verticals.condges.fb_dashboard import render as fb_render
    except ImportError:
        st.title("🍽 F&B")
        st.info(
            "Dashboard F&B in arrivo: `verticals/condges/fb_dashboard.py` "
            "non è ancora su main (in costruzione nel worktree fb-looker)."
        )
        return
    fb_render()
```

`verticals/hub/pages_/reviews.py`:

```python
"""Pagina Reviews — monta verticals.reviews.app.render()."""


def render():
    from verticals.reviews.app import render as reviews_render

    reviews_render()
```

`verticals/hub/home.py`:

```python
"""Home-store: card per app con semaforo freshness (layout A, 2026-06-12)."""

import streamlit as st

from verticals.hub.freshness import carica_freshness, semaforo


@st.cache_data(ttl=300, show_spinner="Carico freshness…")
def _freshness():
    return carica_freshness()


def render():
    st.title("🏨 HotelOps Hub")
    try:
        fresh = _freshness()
        errore = None
    except Exception as e:  # BQ giù: dichiarare, mai cache silente
        fresh, errore = {}, str(e)

    if errore:
        st.error(f"Dati non disponibili (BigQuery): {errore}")
        return

    peggiore = max(
        (v.get("giorni") if v.get("giorni") is not None else 99)
        for k, v in fresh.items()
        if "giorni" in v
    )
    st.caption(f"Stato dati: {semaforo(peggiore)} · refresh ogni 5 min")

    col_fb, col_rev, col_ing = st.columns(3)
    with col_fb:
        g = fresh["fb"]["giorni"]
        st.subheader(f"🍽 F&B {semaforo(g)}")
        st.metric("Ultimo consumo", f"{g} gg fa" if g is not None else "n/d")
        st.page_link("pages_/fb.py", label="Apri →") if False else None
    with col_rev:
        g = fresh["reviews"]["giorni"]
        st.subheader(f"⭐ Reviews {semaforo(g, 7, 14)}")
        st.metric("Media mese", fresh["reviews"]["media_mese"] or "n/d")
    with col_ing:
        n = fresh["ingest"]["in_coda"]
        st.subheader(f"📥 Ingest {'🟢' if n == 0 else '🟡'}")
        st.metric("Raw objects in coda", n)

    st.caption(
        "💶 Cassa/PF arriva con la migrazione PF generazionale "
        "(in pausa: P1 lotteria budget, vedi STATUS.md)."
    )
```

(Nota: la navigazione tra pagine la fa `st.navigation` in `app.py` — le card sono
informative; il link è la sidebar. Niente `st.page_link` su `st.Page`-functions.)

`verticals/hub/app.py`:

```python
"""HotelOps Hub — layer di presentazione sopra i vertical (NON un vertical).

Lancio: streamlit run verticals/hub/app.py
Spec: docs/superpowers/specs/2026-06-12-hub-app-store-design.md
"""

import streamlit as st

from verticals.hub import home
from verticals.hub.pages_ import fb, ingest, reviews

st.set_page_config(page_title="HotelOps Hub", page_icon="🏨", layout="wide")

pg = st.navigation(
    [
        st.Page(home.render, title="Home", icon="🏨", default=True),
        st.Page(fb.render, title="F&B", icon="🍽"),
        st.Page(reviews.render, title="Reviews", icon="⭐"),
        st.Page(ingest.render, title="Ingest", icon="📥"),
    ]
)
pg.run()
```

(`pages_/ingest.py` arriva nel Task 4 — per far girare i test del Task 3 creare
prima il Task 4, oppure eseguire i due task in sequenza e testare alla fine del 4.
Ordine consigliato: implementare Task 3 e 4 back-to-back, poi un'unica verifica.)

- [ ] **Step 4: Run tests** (dopo Task 4 se si segue l'ordine consigliato)

Run: `python -m pytest tests/test_hub_mounts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add verticals/hub/ tests/test_hub_mounts.py
git commit -m "feat(hub): scaffold — app st.navigation, home card+freshness, mount fb/reviews"
```

---

### Task 4: pagina Ingest — il layer di ingestione

**Files:**
- Create: `verticals/hub/pages_/ingest.py`
- Test: `tests/test_hub_mounts.py` (append)

- [ ] **Step 1: Write the failing test** (append)

```python
def test_ingest_page_importabile():
    from verticals.hub.pages_ import ingest

    assert callable(ingest.render)
```

- [ ] **Step 2: Implement `verticals/hub/pages_/ingest.py`**

```python
"""Pagina Ingest — drop → classifica → intake → promote → inbox.

Unica superficie di scrittura del hub (eccezione dichiarata in spec §regole).
Lineage-first: stesse funzioni del CLI, mai parser diretti.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st


def _classifica(tmp_path: Path):
    from core.lineage.source_resolver import load_registry
    from ingest.classify import classify

    res = classify(tmp_path)
    reg = load_registry()
    proposta = None
    if res.category and res.societa:
        sd = reg.resolve(res.category, res.societa)
        proposta = sd.source_name if sd else None
    return res, proposta, sorted(reg.sources)


def _inbox_df():
    import pandas as pd

    from core.bq.client import get_client

    q = """
    SELECT r.file_name_original, r.source_name, v.current_status,
           v.last_event_at, r.raw_object_id
    FROM `hotelops-suite.hotelops.v_raw_objects_current` v
    JOIN `hotelops-suite.hotelops.f_raw_objects` r USING (raw_object_id)
    WHERE v.current_status != 'PROMOTED'
    ORDER BY v.last_event_at DESC
    LIMIT 50
    """
    return get_client().query(q).result().to_dataframe(create_bqstorage_client=False)


def render():
    st.title("📥 Ingest")
    st.caption("File → classifica → intake (GCS + f_raw_objects) → promote. Lineage-first.")

    files = st.file_uploader(
        "Trascina i file (xlsx, csv, txt)",
        accept_multiple_files=True,
        type=["xlsx", "csv", "txt"],
    )

    for up in files or []:
        st.divider()
        st.subheader(up.name)
        tmp_dir = Path(tempfile.mkdtemp(prefix="hub_ingest_"))
        tmp_path = tmp_dir / up.name  # nome originale: serve a detection e GCS
        tmp_path.write_bytes(up.getbuffer())

        res, proposta, tutti = _classifica(tmp_path)
        st.write(
            f"Rilevato: `{res.file_type}` (categoria `{res.category}`, "
            f"società `{res.societa}`, confidenza {res.confidence:.0%})"
        )
        if proposta is None:
            st.warning(
                "Nessun source nel registry per questa detection — se è un tipo "
                "nuovo va definito prima (skill hotelops-ingest). "
                "Puoi comunque forzare un source esistente qui sotto."
            )
        source = st.selectbox(
            "Source",
            options=tutti,
            index=tutti.index(proposta) if proposta in tutti else None,
            key=f"src_{up.name}",
        )

        if st.button("Intake", key=f"intake_{up.name}", disabled=source is None):
            from ingest.intake import intake_file

            risultato = intake_file(tmp_path, source_name=source, actor="hub")
            if risultato.deduped:
                st.info(f"Già registrato (dedup): `{risultato.raw_object_id}`")
            else:
                st.success(f"Registrato: `{risultato.raw_object_id}`")
            st.session_state[f"ro_{up.name}"] = risultato.raw_object_id

        ro_id = st.session_state.get(f"ro_{up.name}")
        if ro_id and st.button("Promote", key=f"promote_{up.name}"):
            from ingest.promotion import promote_raw_object

            esito = promote_raw_object(ro_id, actor="hub")
            if esito.status == "PROMOTED":
                st.success(f"PROMOTED — {esito.rows_written} righe scritte")
            else:
                st.error(f"{esito.status}: {esito.reason}")  # VALIDATE_FAIL in chiaro

    st.divider()
    st.subheader("Inbox — raw objects non promossi")
    try:
        df = _inbox_df()
        if df.empty:
            st.success("Coda vuota: tutto promosso.")
        else:
            st.dataframe(df, hide_index=True)
    except Exception as e:
        st.error(f"Inbox non disponibile (BigQuery): {e}")
```

- [ ] **Step 3: Run all hub tests + full suite + lint**

Run: `python -m pytest tests/test_hub_mounts.py tests/test_hub_freshness.py -v && python -m pytest -q && ruff check verticals/hub/ verticals/reviews/app.py tests/`
Expected: hub test PASS, suite verde, lint pulito

- [ ] **Step 4: Commit**

```bash
git add verticals/hub/pages_/ingest.py tests/test_hub_mounts.py
git commit -m "feat(hub): pagina Ingest — drop, classifica, intake, promote, inbox"
```

---

### Task 5: smoke run + STATUS

**Files:**
- Modify: `STATUS.md` (repo principale — via path assoluto)

- [ ] **Step 1: Smoke avvio headless**

```bash
timeout 25 streamlit run verticals/hub/app.py --server.headless true --server.port 8599 &
sleep 8 && curl -s http://localhost:8599/_stcore/health
```

Expected: `ok`. Poi aprire http://localhost:8599 e verificare a occhio: home con 3 card
+ caption Cassa, pagina F&B col messaggio di attesa, Reviews funzionante, Ingest con
uploader e inbox.

- [ ] **Step 2: Verifica funzionale Ingest (facoltativa ma raccomandata)**

Trascinare un file già noto (es. un bilancino già ingerito): atteso dedup
("Già registrato"). Nessun nuovo raw_object creato — controllo: il raw_object_id
mostrato coincide con quello esistente.

- [ ] **Step 3: STATUS.md** — aggiornare la voce "HotelOps Hub": scaffold fatto
(commit hash), cosa resta (cassa post-migrazione, fb quando atterra fb_dashboard,
fase 2 actions/auth).

- [ ] **Step 4: Commit** (STATUS nel repo principale, codice già committato)

```bash
cd /Users/stefanodellapietra/dev/Projects/hotelops && git add STATUS.md && git commit -m "docs(status): hub scaffold completato nel worktree app-store"
```

---

## Self-review (eseguita 2026-06-12)

- Spec coverage: home layout A senza BVA/azioni ✓, fb mount con degrado ✓, reviews
  render() ✓, ingest 5 passi (drop/classifica/intake/promote/inbox) ✓, error handling
  esplicito (BQ giù, VALIDATE_FAIL in chiaro) ✓, cassa esclusa e motivata ✓.
- Tipi coerenti: `render()` senza argomenti ovunque (contratto fb_dashboard);
  `semaforo(giorni, soglia_attenzione, soglia_allarme)` uguale in test e impl. ✓
- Niente placeholder. L'unico riferimento esterno non ancora esistente
  (`fb_dashboard`) è gestito a runtime con fallback, per design. ✓
- Nota onesta: il Task 1 sposta il corpo di `main()` — il diff esatto dipende dal
  contenuto attuale (185 righe): l'esecutore deve spostare il blocco, non riscriverlo.
