# Hub Registry Audit — Architettura e Tassonomia

**Data**: 2026-07-09
**Scope**: `verticals/hub/` — registry, roles, pages_, home, theme
**Tipo**: Audit read-only. Nessuna modifica al codice.

---

## 1. Stato corrente — Registry APPS

| id | Titolo | Gruppo | Kind | Sensitive | Target | Subtitle | Status operativo |
|---|---|---|---|---|---|---|---|
| `cashflow` | Cashflow | Finanza | `page` | ✅ | `cashflow.render` → `condges/app_cashflow.py` | PF & proiezione cassa | **LIVE** |
| `accodamenti` | Accodamenti | Finanza | `page` | ✅ | `accodamenti.render` → `condges/app_accodamenti.py` | raccolta cassa → Gaia | **LIVE** |
| `banche` | Banche | Finanza | `bind` | ❌ | Looker Studio URL | movimenti & saldi (Looker) | **LIVE** (esterno) |
| `mutui` | Mutui | Finanza | `page` | ❌ | `mutui.render` → iframe Cloudflare Worker | ammortamenti & simulatore | **LIVE** |
| `cdg` | CdG | Finanza | `soon` | ❌ | `None` | controllo di gestione (in redesign) | **PLACEHOLDER** (spento 2026-07-05) |
| `fb` | Food & Beverage | Operations | `page` | ❌ | `fb.render` → `condges/fb_dashboard.py` | food cost & coperti | **LIVE** (import graceful) |
| `spiaggia` | Spiaggia | Operations | `page` | ❌ | `spiaggia.render` → `spiaggia/app.py` | ricavo stabilimento & quadratura | **LIVE** |
| `reviews` | Reviews | Operations | `page` | ❌ | `reviews.render` → `reviews/app.py` | reputation & sentiment | **LIVE** |

**Totale**: 8 app registrate — 5 live pages, 1 bind esterno, 1 placeholder `soon`, 2 sensitive (scrittura BQ).

---

## 2. File in `pages_/` — stato di ogni file

| File | Importato in registry? | Registrato in APPS? | Status | Note |
|---|---|---|---|---|
| `cashflow.py` | ✅ | ✅ `kind=page` | MONTATO | Guard S1 re-check interno |
| `accodamenti.py` | ✅ | ✅ `kind=page` | MONTATO | Guard S1 re-check interno |
| `mutui.py` | ✅ | ✅ `kind=page` | MONTATO | Iframe Cloudflare Worker |
| `fb.py` | ✅ | ✅ `kind=page` | MONTATO | Import graceful se `fb_dashboard.py` assente |
| `spiaggia.py` | ✅ | ✅ `kind=page` | MONTATO | Import graceful |
| `reviews.py` | ✅ | ✅ `kind=page` | MONTATO | |
| `cdg.py` | ❌ | ✅ `kind=soon` | **ORFANO PARZIALE** | File pronto per il relaunch; non importato finché `kind=soon` |
| `ingest.py` | ❌ | ❌ | **ORFANO COMPLETO** | Rimosso dalla nav (decisione README §Ingest). Contiene UI intake/promote funzionante. Guard `if "ingest" not in current_apps()` è morta (`ingest` non è un id noto in nessun grant). |

---

## 3. Modello accessi — Grant attuali

### Costanti gruppo (da `_group_safe`, esclude `sensitive=True` e `kind="soon"`)

| Costante | App incluse | Calcolo |
|---|---|---|
| `FINANZA` | `{banche, mutui}` | apps Finanza non-sensitive, non-soon |
| `OPERATIONS` | `{fb, spiaggia, reviews}` | apps Operations non-sensitive, non-soon |
| `ALL` | tutte e 8 | nessun filtro |

### _GRANTS nominativi

| Email | Grant esplicito | App concesse (espanse) |
|---|---|---|
| `stefano@panoramagroup.it` | `ALL` | tutte |
| `ste.dellapietra@gmail.com` | `ALL` | tutte |
| `amministrazione@panoramagroup.it` (Rosa) | `FINANZA \| {cashflow, accodamenti, spiaggia}` | banche, mutui, cashflow, accodamenti, spiaggia |
| `fom@panoramagroup.it` (Anna) | `OPERATIONS` | fb, spiaggia, reviews |
| `fb@panoramagroup.it` (S. Amato) | `OPERATIONS` | fb, spiaggia, reviews |
| `gm@panoramagroup.it` (Direttore) | `FINANZA \| OPERATIONS \| {cashflow, cdg}` | banche, mutui, fb, spiaggia, reviews, cashflow, cdg |
| `stedepi@gmail.com` (padre) | `FINANZA \| OPERATIONS \| {cashflow}` | banche, mutui, fb, spiaggia, reviews, cashflow |
| `magazzino@panoramagroup.it` (Mario) | `{fb, spiaggia}` | fb, spiaggia |

---

## 4. Problemi e osservazioni

### 4.1 Gruppo "Sistema" dichiarato ma vuoto

```python
# registry.py
GROUPS = ["Finanza", "Operations", "Sistema"]
```

`Sistema` è in `GROUPS` ma **nessuna app usa `group="Sistema"`**. `home.py` salta silenziosamente i gruppi vuoti (`if not apps: continue`), ma:

- `by_group()` restituisce sempre `{"Finanza": [...], "Operations": [...], "Sistema": []}` — la chiave esiste con lista vuota.
- Il test lo fissa esplicitamente: `assert g["Sistema"] == []`.
- Non c'è nessun guard in `validate()` che avverta dei gruppi inutilizzati.

**Impatto**: basso. È un reserved slot dichiarato, ma privo di occupanti da mesi. Crea aspettative non soddisfatte per chi legge il codice.

---

### 4.2 Nessun gruppo strutturale per il CEO Cockpit

L'evoluzione verso un **CEO Cockpit** (issue futuro: Capital Snapshot card) richiede un punto d'ancoraggio in `GROUPS`. Oggi non esiste. Aggiungere una card KPI richiederebbe o:

- riutilizzare "Sistema" (semanticamente improprio), oppure
- aggiungere `"Cockpit"` a `GROUPS` (rompe i test di ordine).

Il design corrente non ha slot esplicito per superfici cross-cutting o riassuntive.

---

### 4.3 Grant `cdg` per `gm@panoramagroup.it` è forward-looking silente

```python
"gm@panoramagroup.it": FINANZA | OPERATIONS | {"cashflow", "cdg"},
```

`cdg` è `kind=soon` → non appare in nessuna costante gruppo → è escluso da tutti gli utenti tranne chi lo ha nel grant esplicito. **Quando CdG tornerà come `kind=page`, il Direttore lo vedrà automaticamente** senza ulteriori modifiche ai grant. Questo è presumibilmente intenzionale, ma non è documentato come policy decision nel file.

---

### 4.4 Guard morta in `ingest.py`

```python
# pages_/ingest.py
def render():
    if "ingest" not in current_apps():
        st.error("Non hai accesso a questa sezione.")
        st.stop()
```

`ingest` non è un id di nessuna `HubApp` in `APPS`, quindi non compare in nessun `_GRANTS`. La guard nega sempre, ma la pagina non è mai montata, quindi il codice non viene mai eseguito. È dead code a doppio livello.

---

### 4.5 Nessun segnale visivo per `sensitive=True` nei tile

`home.py::_tile()` rende tutti i tile con lo stesso layout, indipendentemente da `sensitive`. Cashflow (scrive su BQ) e Mutui (read-only) sono visualmente identici per l'utente. Non ci sono badge, icone di lock o caption differenziate.

---

### 4.6 Espansione silenziosa delle costanti-gruppo

`FINANZA` e `OPERATIONS` sono calcolate a import-time da `_group_safe()`. Se si aggiunge una nuova app non-sensitive a "Finanza", **tutti gli utenti con grant `FINANZA` la vedranno automaticamente** senza che nessuno abbia fatto una decisione esplicita di concessione. Il meccanismo è by-design per le app di sola lettura, ma potrebbe sorprendere.

**Esempio**: aggiungere un'app `kpi` non-sensitive al gruppo Finanza → Rosa la vede subito senza nessuna riga in `_GRANTS`.

---

### 4.7 `cdg.py` è un file semi-orfano

Il file `pages_/cdg.py` esiste e ha il guard S1, ma non è importato da `registry.py` (l'import list in `registry.py` è `from verticals.hub.pages_ import accodamenti, cashflow, fb, mutui, reviews, spiaggia` — `cdg` non è nell'elenco). Quando CdG tornerà come `kind=page`, sarà necessario:

1. Aggiungere `cdg` all'import in `registry.py`
2. Cambiare `kind` da `soon` a `page` e impostare `target=cdg.render`
3. Decidere `sensitive=True` (ha il bottone "Salva in BQ")

---

## 5. Proposta target registry

### 5.1 Nuova tassonomia dei gruppi

```python
# Ordine proposto
GROUPS = ["Cockpit", "Finanza", "Operations", "Sistema"]
```

- **Cockpit** (nuovo) — card KPI riassuntive per il CEO/Direttore: Capital Snapshot, data freshness, alert. App read-only, mai sensitive.
- **Finanza** — invariato: cashflow (write), accodamenti (write), banche (bind), mutui (read).
- **Operations** — invariato: fb, spiaggia, reviews.
- **Sistema** — mantenuto vuoto come reserved slot per strumenti di sistema (lineage, ingest diagnostics). Non appare nella home finché vuoto.

### 5.2 Proposta registry target

| id | Gruppo | Kind | Sensitive | Note |
|---|---|---|---|---|
| `cockpit` | Cockpit | `page` | ❌ | **NUOVO** — Capital Snapshot CEO card (issue separato) |
| `cashflow` | Finanza | `page` | ✅ | invariato |
| `accodamenti` | Finanza | `page` | ✅ | invariato |
| `banche` | Finanza | `bind` | ❌ | invariato |
| `mutui` | Finanza | `page` | ❌ | invariato |
| `cdg` | Finanza | `soon` → `page` | ✅ | quando il redesign è pronto; aggiungere import + sensitive |
| `fb` | Operations | `page` | ❌ | invariato |
| `spiaggia` | Operations | `page` | ❌ | invariato |
| `reviews` | Operations | `page` | ❌ | invariato |

### 5.3 Segnale visivo sensitive nei tile

Aggiungere in `home.py::_tile()` una caption discreta quando `app.sensitive is True`:

```python
if app.sensitive:
    st.caption("✏️ scrive dati")
```

Nessun impatto funzionale. Migliora la comprensione del modello per utenti nuovi.

---

## 6. Lista modifiche sicure

Modifiche che non toccano logica applicativa e non rompono il comportamento per nessun utente:

| # | Modifica | File | Impatto test |
|---|---|---|---|
| M1 | Aggiungere `"Cockpit"` a `GROUPS` (prima di "Finanza") | `registry.py` | `test_by_group_ordine_e_contenuto` → aggiornare asserzione ordine; `test_by_group_for_filtra_e_mantiene_ordine` → idem |
| M2 | Rimuovere la guard morta da `ingest.py` (o aggiungere commento `# NOTA: questa pagina non è montata`) | `pages_/ingest.py` | nessuno |
| M3 | Documentare il grant `cdg` per `gm` come policy forward-looking in `roles.py` (commento) | `roles.py` | nessuno |
| M4 | Aggiungere badge `✏️ scrive dati` per `sensitive=True` in `_tile()` | `home.py` | nessuno (visivo) |
| M5 | Aggiungere `cdg` all'import list di `registry.py` (come import inattivo, per documentarne la dipendenza) | `registry.py` | nessuno — ma attenzione: l'import andrebbe in posizione commentata finché `kind=soon` |

> **M1 richiede update test**: `test_hub_registry.py` riga 38 (`assert list(g.keys()) == GROUPS`) e riga 42 (`assert g["Sistema"] == []`). Il test rimane corretto ma deve adattarsi al nuovo ordine.

---

## 7. Lista rischi

| # | Rischio | Probabilità | Impatto | Mitigazione |
|---|---|---|---|---|
| R1 | Aggiungere app non-sensitive a Finanza/Operations espande silenziosamente i grant di tutti gli utenti nel gruppo | Media | Basso (read-only) → Alto se accidentalmente sensitive | Aggiungere commento avviso sopra `_group_safe` + review sistematica dei grant a ogni nuova app |
| R2 | Rimuovere `ingest.py` cancella uno strumento di debug lineage funzionante | Bassa | Medio — il CLI copre lo stesso path, ma la UI era utile per operatori non tecnici | Non rimuovere; spostare in `Sistema` se si vuole riesporla in modo controllato |
| R3 | CdG ritorna come `kind=page` senza che `sensitive=True` venga settato | Bassa | Alto — CdG ha bottone "Salva in BQ fonte=APP_BUDGET"; senza `sensitive`, i grant di FINANZA/OPERATIONS lo vedono | Il file `cdg.py` ha già il guard S1 (`if "cdg" not in current_apps()`), ma il meccanismo S1 dipende da `sensitive=True` in registry |
| R4 | Cockpit card con query BQ lente blocca il caricamento della home | Media | Alto — la home è il landing page di tutti | Usare `@st.cache_data(ttl=300)` e fallback graceful se BQ non risponde; non esporre metriche sulla home root |
| R5 | Mutui iframe embedda contenuto esterno (Cloudflare Worker) non sotto I1 | Bassa | Basso — è read-only, non scrive su BQ | Conforme: il dato vive nel Worker (snapshot JSON), non in BQ; documentato in `mutui.py` |
| R6 | `gm@panoramagroup.it` ha `cdg` nel grant ma `cdg` è kind=soon: se il relaunch avviene con una nuova logica write-path, il Direttore potrebbe avere accesso non revisionato | Bassa | Medio | Revisare il grant `gm` al momento del relaunch CdG |

---

## 8. Checklist pre-Cockpit (Issue 3/4 sequenza)

Prima di aggiungere la Capital Snapshot card:

- [ ] **M1**: aggiungere `"Cockpit"` a `GROUPS` + aggiornare test
- [ ] Decidere: cockpit è visibile a tutti o solo a `gm`/`stefano`? (non sensitive → ereditato da FINANZA? o grant esplicito?)
- [ ] Decidere: cockpit come app `kind=page` standard, o sezione speciale nella home senza app separata?
- [ ] Verificare che le query BQ per la card abbiano fallback graceful (BQ down → card grayed out, non errore bloccante)
- [ ] Il cockpit NON deve essere `sensitive=True` — è read-only

---

## 9. Riferimenti

| File | Ruolo |
|---|---|
| `verticals/hub/registry.py` | Unica fonte di verità del catalogo app |
| `verticals/hub/roles.py` | Risoluzione identità → app concesse |
| `verticals/hub/home.py` | Rendering home gateway (tile grid) |
| `verticals/hub/pages_/` | Una `render()` per ogni superficie montata |
| `verticals/hub/freshness.py` | Query BQ freshness (fb, reviews, ingest queue) |
| `tests/test_hub_registry.py` | Contratti registry (id, kind, gruppo, sensibili) |
| `tests/test_hub_roles.py` | Contratti accessi (S1, fail-closed, grant per email) |
| `docs/superpowers/specs/2026-06-20-hub-gateway-presentation-design.md` | Spec design gateway |
| `docs/superpowers/specs/2026-06-21-hub-roles-access-design.md` | Spec ruoli e accessi |
| `verticals/hub/README.md` | Doc viva: superfici, modello accessi, deploy |
