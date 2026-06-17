---
name: add-new-vertical
description: Orchestratore per creare un NUOVO vertical hotelops end-to-end — un dominio dati nuovo che entra come dati→BigQuery→viste→app→vetrina. Usa questa skill OGNI volta che Stefano vuole portare in hotelops una fonte/sistema nuovo come vertical, o chiede "facciamo un vertical per X", "nuovo vertical", "crea/aggiungi un vertical", "come si crea un vertical", "portiamo X dentro hotelops", oppure quando un nuovo flusso dati merita una sua app/superficie (spiaggia, F&B, prenotazioni, un nuovo gestionale). NON per ingerire un file in un vertical che esiste già (→ hotelops-ingest) né per agganciare una singola vista a una app esistente (→ hub-bind). Questa skill OVERRIDE l'istinto di costruire i pezzi ad-hoc, saltare il lineage, scrivere BQ a mano o dimenticare il mount in vetrina: un vertical ha un arco completo e delle invarianti, e questa skill li tiene insieme delegando ai pezzi (hotelops-ingest per i dati, hub-bind per la vetrina, save-game per la doc).
---

# Add New Vertical — l'arco completo di un vertical hotelops

Un **vertical** è un'app di dominio che consuma `core/` + `ingest/` e serve un'audience (es. `condges`, `reviews`, `spiaggia`). Crearne uno non è "scrivere uno script": è un arco che attraversa 4 strati, ognuno con le sue regole. Questa skill è la mappa e il direttore d'orchestra — i pezzi di dettaglio li fanno le sub-skill, qui c'è il filo che li lega e le cose che si dimenticano.

**Perché esiste:** ogni volta che si fa un vertical a mano si riscopre lo stesso pattern (e si dimentica lo stesso pezzo — di solito il mount in vetrina o la validazione su dati veri). Codificarlo evita di re-derivarlo e di rompere le invarianti.

## Il workflow (processo, non solo file)

Un vertical si costruisce così, in quest'ordine — non saltare le fasi di pensiero:

1. **brainstorming** → spec in `docs/superpowers/specs/YYYY-MM-DD-<x>-design.md`. Qui si decide: fonte/i, audience, lifecycle, lente società, cosa è in scope vs fase-next. *La maggior parte degli errori di un vertical sono decisioni di modello prese male qui, non bug di codice.*
2. **writing-plans** → plan in `docs/superpowers/plans/`. Task TDD bite-sized.
3. **subagent-driven-development** → esecuzione: un subagent per task, review tra l'uno e l'altro.
4. **Validazione su DATI VERI** (vedi sotto — è la fase che becca i bug che gli unit test non vedono).
5. **finishing-a-development-branch** → PR/merge.
6. **save-game** → CLAUDE.md (tabella/vista/source/modulo) + `hotelops manifest`.

> Lo spec e il plan si committano **separati** dall'implementazione.

## I 4 strati (mappa file + a chi delegare)

### Strato 1 — DATI (lineage: ingest → canonical → viste) → **delega a `hotelops-ingest`**

Il cuore. Non scrivere mai BQ fuori dal gate. I pezzi:

| Pezzo | Dove | Note |
|---|---|---|
| Source registry | `core/source_registry.yaml` | nome **4-part** `<SYSTEM>_<DATASET>_<SOCIETA>_<LIFECYCLE>`; `loop_targets`, `promotion_policy` (MANUAL/AUTO/RAW_ONLY), `raw_storage`, `parser_module`. Invariante hard: `loop_targets==[] ⇔ RAW_ONLY`. |
| Schema | `core/schemas.py` | Pydantic con le **5 dimensioni** + audit (`raw_object_id, file_sorgente, hash_riga, data_caricamento`). |
| Table id | `core/config.py` | `F_*` via `_t()`. |
| DDL | `core/bq/load/create_<x>_tables.py` | `CREATE TABLE IF NOT EXISTS`, partition/cluster sensati. |
| Parser | `ingest/flussi/` (o `ingest/banca/`) | invocato da `promote` come `python -m … --file --raw-object-id`; scrive **solo** via `validate_batch` + `bq_write_validated(mode=…, natural_key=…)`. Lifecycle SNAPSHOT (full-replace per chiave) o APPEND (dedup `hash_riga`). |
| Fetcher (se la fonte è su Drive) | `ingest/drive_fetch.py` | pull live via **service account** (`drive-audit@…`, key in `~/.config/hotelops/`); `--source-name` legge `drive_file_id` dal registry, `--file-id` per override ad-hoc. Evita i download statici che si congelano. |
| Viste | `core/bq/views/v_<x>_*.sql` | deploy con `hotelops deploy-views`. |
| Dimensioni | `core/bq/dimensioni/*.csv` + loader | solo se servono mapping/anagrafiche. |

La meccanica intake→promote→verify (e la definizione di una source nuova) è esattamente il dominio di **`hotelops-ingest`**: invocala per questo strato invece di reinventare il flusso.

### Strato 2 — VETRINA (app + hub) → **delega a `hub-bind`**

Un vertical senza superficie raggiungibile è metà lavoro.

| Pezzo | Dove | Note |
|---|---|---|
| App vertical | `verticals/<x>/app.py` | espone **`render()`** (NIENTE `set_page_config` dentro render — lo fa l'hub una volta sola); standalone `streamlit run …` per dev. |
| Mount in vetrina | `verticals/hub/app.py` (+ `app_viewer.py` se pubblico) | `st.Page(<x>.render, title=…, icon=…, url_path="<x>")`; eventuale wrapper in `verticals/hub/pages_/`. |
| Tema | `verticals/hub/theme.py` | usa il brand Panorama, non hardcodare colori. |

Agganciare alla vetrina è il dominio di **`hub-bind`**: invocala. *È il pezzo che si dimentica più spesso* (la spiaggia ha avuto `render()` pronto per giorni senza essere montata).

### Strato 3 — TEST & CLI

- Test in `tests/test_*.py` — TDD, fixture **reali** (es. workbook openpyxl veri, non mock).
- CLI in `cli.py` / `verticals/<x>/cli_commands.py` solo se il vertical ha comandi propri (come `hotelops reviews`).

### Strato 4 — INVARIANTI (non negoziabili — vedi `docs/architecture/INVARIANTS.md`)

- **5 dimensioni** su ogni riga fact (`societa_id, business_unit_id, funzione_id, location_id, oggetto_id`).
- **3 dimensioni temporali** (COMPETENZA / CASSA / IMPEGNO) dove il dato è finanziario.
- **Mai** scrivere BQ fuori da `bq_write_validated` (I1/I9). Mai parser diretto con `--file` in produzione: sempre intake→promote (altrimenti righe FK-void).
- Nome source **4-part**, e l'invariante `loop_targets/RAW_ONLY`.
- **BigQuery = source of truth**; il vault può essere stale.

## Validazione su DATI VERI (la fase che salva)

Gli unit test girano su fixture sintetiche e passano felici mentre il parser sbaglia tutto sui dati veri. **Prima di dichiarare fatto, fai girare l'intake→promote sul file reale e interroga BQ.** Lezione dalla spiaggia: solo sui dati veri sono emersi (a) l'anno preso dall'header stale invece che dal filename, (b) le celle-data congelate a un anno vecchio, (c) i giorni-zero che gonfiavano le righe, (d) il "Totale mese" del registro raddoppiato. Nessuno di questi si vedeva nei test sintetici.

Pattern: `hotelops intake <file> --source-name X` → `hotelops promote --raw-object-id <id>` → `bq query` che confronta valori attesi su giorni/righe noti.

## Definition of Done (checklist)

- [ ] spec + plan committati (separati dall'implementazione)
- [ ] source registry (4-part, invariante rispettata) — via `hotelops-ingest`
- [ ] schema (5 dim + audit) + table id + DDL
- [ ] parser (gate-only) + fetcher se Drive
- [ ] viste deployate (`hotelops deploy-views`)
- [ ] **validato su dati veri** (intake→promote→verify in BQ), non solo unit test
- [ ] app `render()` + **montata in vetrina** — via `hub-bind`
- [ ] test verdi
- [ ] PR/merge
- [ ] **`save-game`** (CLAUDE.md + manifest)

## Reference worked: vertical spiaggia / corrispettivi (2026-06-17)

Esempio completo end-to-end da copiare come template:
- Source `RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT` (4-part) · tabella `f_spiaggia_corrispettivi` · vista `v_spiaggia_giornaliero` (cross-società INTUR+ORTI) · parser `ingest/flussi/ingest_spiaggia_corrispettivi.py` · fetcher Drive `ingest/drive_fetch.py` · app tab in `verticals/spiaggia/app.py`.
- Spec/plan: `docs/superpowers/{specs,plans}/2026-06-17-spiaggia-*`.
- Mostra: lente società (additivo, no doppio conteggio), lifecycle SNAPSHOT per-anno, pull live dal Drive via SA, e i 4 bug emersi solo sui dati veri.
- **TODO ancora aperto su quel vertical**: montarlo in vetrina (`hub-bind`) — esempio vivo di "lo strato 2 si dimentica".
