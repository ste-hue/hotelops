# Hub — accesso per-utente (mappa email→app) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Filtrare nav e tile del hub per utente loggato (mappa `email → app-id`), così che Anna veda solo le sue app e le superfici di scrittura restino protette.

**Architecture:** Una sola app Streamlit (`app.py`) dietro IAP. `roles.py` legge l'email autenticata dall'header edge e risolve il set di app concesse; `app.py`/`home.py` filtrano il registry su quel set; le superfici di scrittura (`cashflow`, `ingest`) ri-controllano dentro `render()`. Le app sensibili sono escluse per costruzione dalle costanti-gruppo (Invariante S1) e si concedono solo via grant esplicito.

**Tech Stack:** Python 3.11+, Streamlit, pytest. Nessuna dipendenza nuova.

**Spec:** `docs/superpowers/specs/2026-06-21-hub-roles-access-design.md`

## Global Constraints

- **Branch:** lavorare su `feat/hub-roles` (già creato; spec già committata). Mai su `main`.
- **Invariante S1:** un'app che scrive/muta stato/è irreversibile/espone dati riservati NON eredita audience da una costante-gruppo. Marcata `sensitive=True` → esclusa dalle costanti-gruppo → concessa solo per grant esplicito.
- **Invariante S2:** l'assenza di header NON prova "dev". Qualsiasi bypass autorizzativo è abilitato SOLO esplicitamente via env `HUB_DEV_ALLOW_ALL=1`. Default = fail-closed (`frozenset()`). La var non va MAI in un deploy.
- **`HubApp` si costruisce posizionalmente** in tutto il codice (7 arg, `subtitle` ultimo). Nuovi campi vanno aggiunti DOPO `subtitle` con default, per non rompere le costruzioni esistenti.
- **Stile test del repo:** logica pura → unit test; file Streamlit-runtime (`app.py`, `home.py`, `*.render`) → assertion su sorgente/`ast` (vedi `test_hub_cashflow_mount.py`, `test_hub_mounts.py`). Non introdurre `AppTest` (nessun precedente, mocking di `st.context` fragile).
- **Dev locale:** per vedere tutto in locale serve `export HUB_DEV_ALLOW_ALL=1` (altrimenti la home è vuota — è il comportamento S2 voluto). Eseguire i test con la var NON impostata, tranne dove indicato.
- Comandi: `pytest <path> -v`, `ruff check verticals/hub`, `ruff format verticals/hub`.

---

## File Structure

- **Modify** `verticals/hub/registry.py` — campo `sensitive`, mark `cashflow`/`ingest`, helper `pages_for()`/`by_group_for()`.
- **Create** `verticals/hub/roles.py` — risoluzione identità → app concesse.
- **Modify** `verticals/hub/app.py` — filtra `_page_objs` su `current_apps()`; passa `allowed` a `home.render`.
- **Modify** `verticals/hub/home.py` — `render(page_objs, allowed)`; filtra tile + landing "nessun accesso".
- **Modify** `verticals/hub/pages_/cashflow.py` + `verticals/hub/pages_/ingest.py` — re-check in testa a `render()`.
- **Delete** `verticals/hub/app_viewer.py` — entrypoint unico `app.py`.
- **Modify/Create** tests: `tests/test_hub_registry.py`, `tests/test_hub_roles.py` (nuovo), `tests/test_hub_mounts.py`, `tests/test_hub_cashflow_mount.py`.
- **Modify** skill `meta/skills/hub-bind/SKILL.md` + `meta/skills/add-new-vertical/SKILL.md` — audience = grant, S1, write re-check.

---

### Task 1: registry — campo `sensitive` + mark + helper di filtro

**Files:**
- Modify: `verticals/hub/registry.py`
- Test: `tests/test_hub_registry.py`

**Interfaces:**
- Produces: `HubApp.sensitive: bool` (default `False`); `pages_for(allowed: frozenset[str]) -> list[HubApp]`; `by_group_for(allowed: frozenset[str]) -> dict[str, list[HubApp]]`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_hub_registry.py`, appendi:

```python
def test_cashflow_e_ingest_sono_sensibili():
    from verticals.hub.registry import APPS

    sens = {a.id for a in APPS if a.sensitive}
    assert sens == {"cashflow", "ingest"}


def test_pages_for_filtra_su_allowed():
    from verticals.hub.registry import pages_for

    got = {a.id for a in pages_for(frozenset({"reviews", "fb"}))}
    assert got == {"reviews", "fb"}
    assert {a.id for a in pages_for(frozenset())} == set()


def test_by_group_for_filtra_e_mantiene_ordine():
    from verticals.hub.registry import GROUPS, by_group_for

    g = by_group_for(frozenset({"reviews"}))
    assert list(g.keys()) == GROUPS  # tutti i gruppi presenti (anche vuoti)
    assert {a.id for a in g["Operations"]} == {"reviews"}
    assert g["Finanza"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_hub_registry.py -v`
Expected: FAIL — `AttributeError: 'HubApp' object has no attribute 'sensitive'` / `ImportError: cannot import name 'pages_for'`.

- [ ] **Step 3: Add the `sensitive` field**

In `verticals/hub/registry.py`, nella dataclass `HubApp`, dopo `subtitle`:

```python
    subtitle: str = ""
    sensitive: bool = False  # scrive/muta stato/azioni irreversibili/dati riservati (S1)
```

- [ ] **Step 4: Mark cashflow + ingest sensibili**

Sostituisci le due righe in `APPS`:

```python
    HubApp("cashflow", "Cashflow", "💸", "Finanza", "page", cashflow.render, "PF & proiezione cassa", sensitive=True),
```

```python
    HubApp("ingest", "Ingest", "📥", "Sistema", "page", ingest.render, "lineage: intake → promote", sensitive=True),
```

- [ ] **Step 5: Add the filter helpers**

In fondo a `registry.py` (dopo `by_group`):

```python
def pages_for(allowed: frozenset[str]) -> list[HubApp]:
    """Le pagine montabili (kind=page) concesse a ``allowed``."""
    return [a for a in pages() if a.id in allowed]


def by_group_for(allowed: frozenset[str]) -> dict[str, list[HubApp]]:
    """Le app per gruppo, filtrate su ``allowed`` (gruppi vuoti restano chiavi)."""
    return {g: [a for a in apps if a.id in allowed] for g, apps in by_group().items()}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_hub_registry.py -v`
Expected: PASS (tutti, inclusi i preesistenti).

- [ ] **Step 7: Commit**

```bash
git add verticals/hub/registry.py tests/test_hub_registry.py
git commit -m "feat(hub): HubApp.sensitive + pages_for/by_group_for (S1 seam)"
```

---

### Task 2: roles.py — risoluzione identità → app concesse

**Files:**
- Create: `verticals/hub/roles.py`
- Test: `tests/test_hub_roles.py`

**Interfaces:**
- Consumes: `verticals.hub.registry.APPS`.
- Produces: `current_apps() -> frozenset[str]`; `FINANZA`, `OPERATIONS`, `ALL` (frozenset); `_resolve(email: str | None, allow_all: bool) -> frozenset[str]`; `_parse_email(raw: str | None) -> str | None`; `_email_from_headers(headers) -> str | None`.

- [ ] **Step 1: Write the failing tests**

Crea `tests/test_hub_roles.py`:

```python
"""Hub roles — risoluzione identità → app concesse."""

from verticals.hub.roles import (
    ALL,
    FINANZA,
    OPERATIONS,
    _email_from_headers,
    _parse_email,
    _resolve,
)


def test_parse_email_strip_prefisso_iap():
    assert _parse_email("accounts.google.com:foo@bar.it") == "foo@bar.it"
    assert _parse_email("foo@bar.it") == "foo@bar.it"
    assert _parse_email(None) is None
    assert _parse_email("") is None


def test_email_from_headers_case_insensitive():
    h = {"x-goog-authenticated-user-email": "accounts.google.com:fom@panoramagroup.it"}
    assert _email_from_headers(h) == "fom@panoramagroup.it"
    assert _email_from_headers({}) is None
    assert _email_from_headers(None) is None


def test_costanti_gruppo_escludono_sensibili_S1():
    from verticals.hub.registry import APPS

    sens = {a.id for a in APPS if a.sensitive}
    assert sens  # esistono app sensibili
    assert not (FINANZA & sens)
    assert not (OPERATIONS & sens)
    assert "cashflow" not in FINANZA
    assert "banche" in FINANZA and "mutui" in FINANZA


def test_anna_solo_operations():
    apps = _resolve("fom@panoramagroup.it", allow_all=False)
    assert apps == frozenset({"fb", "spiaggia", "reviews"})
    assert "cashflow" not in apps and "ingest" not in apps


def test_rosa_finanza_con_cashflow_senza_ingest():
    apps = _resolve("amministrazione@panoramagroup.it", allow_all=False)
    assert {"cashflow", "mutui", "banche", "cdg"} <= apps
    assert "ingest" not in apps
    assert "fb" not in apps


def test_antonio_e_padre_tutto_tranne_ingest():
    for email in ("gm@panoramagroup.it", "stedepi@gmail.com"):
        apps = _resolve(email, allow_all=False)
        assert "ingest" not in apps
        assert {"cashflow", "reviews", "fb", "spiaggia", "mutui"} <= apps


def test_mario_solo_fb_e_spiaggia():
    apps = _resolve("magazzino@panoramagroup.it", allow_all=False)
    assert apps == frozenset({"fb", "spiaggia"})


def test_admin_vede_tutto():
    apps = _resolve("stefano@panoramagroup.it", allow_all=False)
    assert apps == ALL
    assert "ingest" in apps and "cashflow" in apps


def test_email_ignota_deny():
    assert _resolve("chiunque@panoramagroup.it", allow_all=False) == frozenset()


def test_no_header_fail_closed_di_default():
    assert _resolve(None, allow_all=False) == frozenset()


def test_no_header_bypass_solo_esplicito():
    assert _resolve(None, allow_all=True) == ALL


def test_header_presente_vince_sul_bypass():
    apps = _resolve("fom@panoramagroup.it", allow_all=True)
    assert apps == frozenset({"fb", "spiaggia", "reviews"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_hub_roles.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'verticals.hub.roles'`.

- [ ] **Step 3: Write `roles.py`**

Crea `verticals/hub/roles.py`:

```python
"""Risoluzione identità → app concesse per il hub.

L'auth "chi entra" è all'edge (IAP). Qui si legge l'email autenticata e si
risolve il set di app-id concesse. Le app SENSIBILI (scrittura/stato) non
ereditano dalle costanti-gruppo: vanno concesse a mano (Invariante S1).
Il bypass dev è SOLO esplicito (HUB_DEV_ALLOW_ALL=1); default fail-closed (S2).
"""

from __future__ import annotations

import os
from collections.abc import Mapping

import streamlit as st

from verticals.hub.registry import APPS

# Header con cui l'edge espone l'email autenticata (IAP oggi; Cloudflare Access domani).
_EDGE_HEADERS = (
    "X-Goog-Authenticated-User-Email",
    "Cf-Access-Authenticated-User-Email",
)
_DEV_BYPASS_ENV = "HUB_DEV_ALLOW_ALL"


def _group_safe(group: str) -> frozenset[str]:
    """App del gruppo NON sensibili — le sensibili non si ereditano (S1)."""
    return frozenset(a.id for a in APPS if a.group == group and not a.sensitive)


FINANZA = _group_safe("Finanza")        # {banche, mutui, cdg} — cashflow escluso (sensitive)
OPERATIONS = _group_safe("Operations")  # {fb, spiaggia, reviews}
ALL = frozenset(a.id for a in APPS)     # admin: tutto, sensibili incluse

# Mappa email → app concesse. Versionata in git; sensibili nominate a mano (S1).
_GRANTS: dict[str, frozenset[str]] = {
    "stefano@panoramagroup.it": ALL,                              # Stefano (Workspace/IAP) — admin
    "ste.dellapietra@gmail.com": ALL,                             # Stefano (gmail) — ridondanza
    "amministrazione@panoramagroup.it": FINANZA | {"cashflow"},   # Rosa
    "fom@panoramagroup.it": OPERATIONS,                           # Anna (room division)
    "fb@panoramagroup.it": OPERATIONS,                            # Stefano Amato (F&B)
    "gm@panoramagroup.it": FINANZA | OPERATIONS | {"cashflow"},   # Antonio Russo (direttore)
    "stedepi@gmail.com": FINANZA | OPERATIONS | {"cashflow"},     # padre
    "magazzino@panoramagroup.it": frozenset({"fb", "spiaggia"}),  # Mario (economato)
}


def _parse_email(raw: str | None) -> str | None:
    """`accounts.google.com:foo@bar` → `foo@bar`; None/'' → None."""
    if not raw:
        return None
    return raw.split(":", 1)[1] if ":" in raw else raw


def _email_from_headers(headers: Mapping | None) -> str | None:
    if not headers:
        return None
    lower = {str(k).lower(): v for k, v in dict(headers).items()}
    for h in _EDGE_HEADERS:
        if h.lower() in lower:
            return _parse_email(lower[h.lower()])
    return None


def _resolve(email: str | None, allow_all: bool) -> frozenset[str]:
    if email is not None:
        return _GRANTS.get(email, frozenset())  # nota → grant; ignota → deny
    # Nessuna identità: l'assenza di header NON prova "dev" → fail-closed (S2).
    return ALL if allow_all else frozenset()


def current_apps() -> frozenset[str]:
    """App-id concesse all'utente del run corrente. Non eccepisce mai."""
    try:
        headers = st.context.headers
    except Exception:
        headers = None
    email = _email_from_headers(headers)
    allow_all = os.environ.get(_DEV_BYPASS_ENV) == "1"
    return _resolve(email, allow_all)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_hub_roles.py -v`
Expected: PASS (12 test verdi).

- [ ] **Step 5: Lint + commit**

```bash
ruff check verticals/hub/roles.py && ruff format verticals/hub/roles.py
git add verticals/hub/roles.py tests/test_hub_roles.py
git commit -m "feat(hub): roles.py — current_apps() (grant per email, S1+S2)"
```

---

### Task 3: app.py — nav filtrata su `current_apps()`

**Files:**
- Modify: `verticals/hub/app.py`
- Test: `tests/test_hub_cashflow_mount.py`

**Interfaces:**
- Consumes: `registry.pages_for`, `roles.current_apps`.
- Produces: `app.py` costruisce `_page_objs` solo dalle pagine concesse; chiama `home.render(_page_objs, allowed)`.

- [ ] **Step 1: Write the failing test**

In `tests/test_hub_cashflow_mount.py`, appendi:

```python
def test_app_filtra_la_nav_su_current_apps():
    from pathlib import Path

    src = Path("verticals/hub/app.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))
    assert "current_apps" in code
    assert "pages_for" in code
    # la Home riceve anche le app concesse, non solo page_objs
    assert "home.render(_page_objs, allowed)" in code
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_hub_cashflow_mount.py::test_app_filtra_la_nav_su_current_apps -v`
Expected: FAIL (`current_apps` non presente in `app.py`).

- [ ] **Step 3: Edit `app.py`**

Sostituisci gli import e il blocco `_page_objs`/`home_page`. Nuovi import (dopo `from verticals.hub import home`):

```python
from verticals.hub.registry import pages_for  # noqa: E402
from verticals.hub.roles import current_apps  # noqa: E402
from verticals.hub.theme import inject_brand  # noqa: E402
```

(rimuovi la riga `from verticals.hub.registry import pages as registry_pages`).

Sostituisci il blocco da `_page_objs = {` fino a `home_page = st.Page(`…`)` con:

```python
allowed = current_apps()

# Una st.Page per ogni pagina CONCESSA; mappa id→Page per i link dalla Home.
_page_objs = {
    a.id: st.Page(a.target, title=a.title, icon=a.icon, url_path=a.id)
    for a in pages_for(allowed)
}

home_page = st.Page(
    lambda: home.render(_page_objs, allowed),
    title="Home",
    icon="🏨",
    default=True,
    url_path="home",
)
```

(la riga `pg = st.navigation([home_page, *_page_objs.values()], position="top")` resta invariata.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_hub_cashflow_mount.py -v`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
ruff check verticals/hub/app.py && ruff format verticals/hub/app.py
git add verticals/hub/app.py tests/test_hub_cashflow_mount.py
git commit -m "feat(hub): app.py filtra la nav sulle app concesse"
```

---

### Task 4: home.py — tile filtrate + landing "nessun accesso"

**Files:**
- Modify: `verticals/hub/home.py`
- Test: `tests/test_hub_mounts.py`

**Interfaces:**
- Consumes: `registry.by_group_for`.
- Produces: `home.render(page_objs=None, allowed=None)` — filtra le tile su `allowed`; se vuoto → messaggio landing, niente tile.

- [ ] **Step 1: Write the failing test**

In `tests/test_hub_mounts.py`, sostituisci `test_home_render_riceve_page_objs` con:

```python
def test_home_render_riceve_page_objs_e_allowed():
    import inspect

    from verticals.hub import home

    sig = inspect.signature(home.render)
    assert "page_objs" in sig.parameters
    assert "allowed" in sig.parameters


def test_home_usa_by_group_for_e_landing():
    from pathlib import Path

    src = Path("verticals/hub/home.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))
    assert "by_group_for" in code
    # landing quando non c'è nessuna app concessa
    assert "allowed" in code
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_hub_mounts.py -k home -v`
Expected: FAIL (`allowed` non in signature; `by_group_for` non in `home.py`).

- [ ] **Step 3: Edit `home.py`**

Sostituisci l'import `from verticals.hub.registry import HubApp, by_group` con:

```python
from verticals.hub.registry import HubApp, by_group_for
```

Sostituisci la funzione `render` con:

```python
def render(page_objs: dict | None = None, allowed: frozenset[str] | None = None) -> None:
    """page_objs = {app_id: st.Page} montate; allowed = app concesse all'utente."""
    page_objs = page_objs or {}
    allowed = frozenset() if allowed is None else allowed
    brand_header("HotelOps", "Amalfi Coast · Maiori")

    groups = by_group_for(allowed)
    if not any(groups.values()):
        st.warning(
            "Non hai ancora accesso a nessuna sezione. "
            "Contatta l'amministratore per i permessi."
        )
        return

    st.caption("Punto d'ingresso · apri un'app per i dati col loro contesto")
    for group, apps in groups.items():
        if not apps:
            continue
        st.subheader(group)
        cols = st.columns(3)
        for i, app in enumerate(apps):
            with cols[i % 3]:
                _tile(app, page_objs.get(app.id))
```

(`_tile` resta invariata.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_hub_mounts.py -v`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
ruff check verticals/hub/home.py && ruff format verticals/hub/home.py
git add verticals/hub/home.py tests/test_hub_mounts.py
git commit -m "feat(hub): home filtra le tile e mostra landing senza accesso"
```

---

### Task 5: re-check server-side su cashflow + ingest

**Files:**
- Modify: `verticals/hub/pages_/cashflow.py`
- Modify: `verticals/hub/pages_/ingest.py`
- Test: `tests/test_hub_cashflow_mount.py`

**Interfaces:**
- Consumes: `roles.current_apps`.
- Produces: `cashflow.render`/`ingest.render` chiamano `st.stop()` in testa se l'app non è concessa.

- [ ] **Step 1: Write the failing test**

In `tests/test_hub_cashflow_mount.py`, appendi:

```python
def test_superfici_scrittura_ricontrollano_il_grant():
    import inspect

    from verticals.hub.pages_ import cashflow, ingest

    for mod, app_id in ((cashflow, "cashflow"), (ingest, "ingest")):
        src = inspect.getsource(mod.render)
        assert "current_apps()" in src, f"{app_id}: manca il re-check"
        assert f'"{app_id}"' in src
        assert "st.stop()" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_hub_cashflow_mount.py::test_superfici_scrittura_ricontrollano_il_grant -v`
Expected: FAIL (re-check assente).

- [ ] **Step 3: Edit `cashflow.py`**

In `verticals/hub/pages_/cashflow.py`, inserisci in testa al corpo di `render()` (prima del `try:`):

```python
def render():
    from verticals.hub.roles import current_apps

    if "cashflow" not in current_apps():
        st.error("Non hai accesso a questa sezione.")
        st.stop()
    try:
        from verticals.condges.app_cashflow import render as _render
```

- [ ] **Step 4: Edit `ingest.py`**

In `verticals/hub/pages_/ingest.py`, inserisci in testa al corpo di `render()` (prima riga della funzione):

```python
    from verticals.hub.roles import current_apps

    if "ingest" not in current_apps():
        st.error("Non hai accesso a questa sezione.")
        st.stop()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_hub_cashflow_mount.py tests/test_hub_mounts.py -v`
Expected: PASS (il re-check non viene invocato dai test di import — nessuno chiama `render()`).

- [ ] **Step 6: Lint + commit**

```bash
ruff check verticals/hub/pages_/cashflow.py verticals/hub/pages_/ingest.py
ruff format verticals/hub/pages_/cashflow.py verticals/hub/pages_/ingest.py
git add verticals/hub/pages_/cashflow.py verticals/hub/pages_/ingest.py tests/test_hub_cashflow_mount.py
git commit -m "feat(hub): re-check grant in cashflow/ingest render (difesa in profondità)"
```

---

### Task 6: ritiro `app_viewer.py` + test viewer→role-based

**Files:**
- Delete: `verticals/hub/app_viewer.py`
- Modify: `tests/test_hub_mounts.py`

**Interfaces:**
- Consumes: `roles._resolve` (per il nuovo test).

- [ ] **Step 1: Replace the viewer test**

In `tests/test_hub_mounts.py`, sostituisci `test_viewer_app_no_ingest_page` con (il "viewer" è ora un grant, non un file):

```python
def test_audience_non_admin_non_riceve_ingest():
    # Il "viewer" non è più un file: è un grant. Chi non è admin non vede ingest.
    from verticals.hub.roles import _resolve

    for email in ("gm@panoramagroup.it", "fom@panoramagroup.it", "amministrazione@panoramagroup.it"):
        assert "ingest" not in _resolve(email, allow_all=False)
```

- [ ] **Step 2: Run test to verify it passes (viewer file ancora presente)**

Run: `pytest tests/test_hub_mounts.py::test_audience_non_admin_non_riceve_ingest -v`
Expected: PASS (il nuovo test non dipende da `app_viewer.py`).

- [ ] **Step 3: Delete `app_viewer.py`**

```bash
git rm verticals/hub/app_viewer.py
```

- [ ] **Step 4: Verify no dangling reference in code/tests**

Run: `grep -rn "app_viewer" verticals/ tests/`
Expected: nessun match (le occorrenze restano solo in `docs/` e `meta/skills/`, sistemate al Task 7).

- [ ] **Step 5: Run the full hub suite**

Run: `pytest tests/ -k hub -v`
Expected: PASS (nessun test legge più `app_viewer.py`).

- [ ] **Step 6: Commit**

```bash
git add tests/test_hub_mounts.py
git commit -m "refactor(hub): ritira app_viewer.py — il viewer è un grant, non un file"
```

---

### Task 7: aggiorna le skill al nuovo contratto

**Files:**
- Modify: `meta/skills/hub-bind/SKILL.md`
- Modify: `meta/skills/add-new-vertical/SKILL.md`

**Interfaces:** nessuna (documentazione).

- [ ] **Step 1: Aggiorna `hub-bind/SKILL.md`**

Trova ogni riferimento a registrare in `app.py` **e** `app_viewer.py` (righe ~30, 71, 78, 98, 159) e riscrivilo al contratto unico. Sostituzioni:

- "registrala in **entrambe** `app.py` (admin) e `app_viewer.py` (viewer)" → "registrala in `app.py` (entrypoint unico) e concedi l'audience aggiungendo l'`id` al grant giusto in `verticals/hub/roles.py::_GRANTS`".
- Ogni "`app.py` e/o `app_viewer.py`" / "`app.py`, `app_viewer.py`" → "`app.py`".
- Aggiungi un capoverso **Superfici di scrittura / dati riservati**:

```markdown
### Superfici di scrittura o dati riservati

Un'app che **scrive, muta stato, è irreversibile o espone dati riservati**:
1. va marcata `sensitive=True` nella riga di `registry.py` → è **esclusa dalle costanti-gruppo** (Invariante S1): NON la si concede per ereditarietà di gruppo, solo nominandola esplicitamente in un grant di `roles.py::_GRANTS`;
2. **ri-controlla `current_apps()`** in testa al suo `render()` e fa `st.stop()` se l'`id` non è concesso. "Card nascosta" ≠ "dato protetto".
```

- [ ] **Step 2: Aggiorna `add-new-vertical/SKILL.md`**

Riga ~51: sostituisci la cella "Mount in vetrina | `verticals/hub/app.py` (+ `app_viewer.py` se pubblico)" con:

```markdown
| Mount nel hub | `verticals/hub/registry.py` (appendi una `HubApp`) + audience in `verticals/hub/roles.py::_GRANTS` | `HubApp("<x>", "<Titolo>", "<icona>", "<gruppo>", "page", <x>.render, "<sottotitolo>")`; se scrive dati → `sensitive=True` + grant esplicito + re-check in `render()`. |
```

- [ ] **Step 3: Verify**

Run: `grep -rn "app_viewer" meta/skills/`
Expected: nessun match.

- [ ] **Step 4: Commit**

```bash
git add meta/skills/hub-bind/SKILL.md meta/skills/add-new-vertical/SKILL.md
git commit -m "docs(skills): hub-bind/add-vertical al contratto grant + S1 + write re-check"
```

---

### Task 8: verifica finale full-suite + nota IAP

**Files:** nessuna modifica codice.

- [ ] **Step 1: Full suite**

Run: `pytest tests/ -q` (con `HUB_DEV_ALLOW_ALL` NON impostata)
Expected: PASS — nessuna regressione. (Se qualche test del hub assume di "vedere" pagine via `render()`, è un falso positivo da indagare: in suite l'header manca e il default è deny — i test devono usare `_resolve`/source-assertions, non invocare `render()`.)

- [ ] **Step 2: Smoke locale con bypass dev**

Run: `HUB_DEV_ALLOW_ALL=1 streamlit run verticals/hub/app.py` → verifica che la Home mostri tutti i gruppi (sei admin via bypass). Poi senza la var → landing "nessun accesso" (fail-closed). Ctrl-C.

- [ ] **Step 3: Nota operativa IAP (NON in questo branch — handoff)**

Prima del deploy: enumerare in Console l'allowlist IAP del servizio `hotelops-hub` e restringerla alle identità previste; assicurarsi che i due gmail esterni (`stedepi@gmail.com`, opz. `ste.dellapietra@gmail.com`) siano allowlisted come account Google esterni, altrimenti non entrano. Confermare che l'header IAP sia `accounts.google.com:<email>` (smoke: stampare temporaneamente `st.context.headers` da un'identità non-admin). Questo è lavoro infra/Console, fuori dal codice — segnalarlo come issue separata.

- [ ] **Step 4: (opzionale) PR**

Quando il branch è verde, aprire la PR `feat/hub-roles` → `main` solo su richiesta di Stefano.

---

## Self-Review

**Spec coverage:** Modello email→app (Task 2) · costanti-gruppo derivate + S1 (Task 1+2) · `_GRANTS` 8 chiavi (Task 2) · nav filtrata (Task 3) · tile + landing (Task 4) · re-check write-surface (Task 5) · ritiro `app_viewer.py` (Task 6) · S2 bypass esplicito (Task 2) · skill update (Task 7) · punti di verifica IAP (Task 8). Tutte le sezioni della spec hanno un task.

**Placeholder scan:** nessun TBD/TODO; ogni step di codice mostra il codice completo.

**Type consistency:** `current_apps() -> frozenset[str]`, `_resolve(email, allow_all)`, `pages_for(allowed)`, `by_group_for(allowed)`, `home.render(page_objs, allowed)` coerenti tra i task che le consumano (Task 3/4/5). `sensitive` aggiunto dopo `subtitle` (campo posizionale-safe).
