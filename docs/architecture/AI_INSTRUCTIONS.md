---
type: ai_instructions
domain: HotelOps
audience: AI agents (Claude Code, NanoClaw, Cron agents, future)
last_updated: 2026-06-21
canonical: repo (was vault HotelOps/AI_INSTRUCTIONS.md)
---

# HotelOps — AI Agent Operating Instructions

> **Migrated from Obsidian vault on 2026-04-30.** Da questa data, la fonte canonica delle istruzioni AI è questo file nel repo. Si legge **dopo** `docs/architecture/INVARIANTS.md` e **prima** di toccare codice o rispondere.
> **Non contiene**: comandi CLI, schemi tabelle, pipeline internals → vivono in `CLAUDE.md` del repo (root).

## Identità

HotelOps è il sistema che mantiene **una versione unica, spiegabile e tracciabile della verità operativa** su fonti frammentate (ERP Esolver, PMS HotelCube, 4 banche, Drive, WhatsApp). Il goal di lungo termine è essere un **digital twin** delle vere operazioni del business.

Non è: query tool, BI layer, raccolta di script. Ogni azione deve rinforzare questa identità.

## Core Rules (philosophy — non negoziabili)

1. **Non assumere mai che i dati siano corretti** → check freshness, completeness, lineage.
2. **Separa rigorosamente i 4 layer** (vedi §Layer Model). Un bug appartiene a *un* layer; risolvi dove vive, non dove si manifesta.
3. **Una canonical truth per concetto** (vedi §Canonical Registry). Multipli = sistema rotto.
4. **La logica vive in un posto solo**: deduplicazione, precedenza, classificazione, mapping. Duplicazione = drift garantito.
5. **Preserva raw, risolvi upstream**: raw è immutabile. Conflitti si risolvono in canonical, con regole esplicite.
   Hard rule: nessun write diretto nel Canonical è valido senza intake Raw tracciato
   (identità + provenienza verificabile). Eccezioni solo con decisione esplicita.
6. **Ogni numero deve essere spiegabile**: fonte, regole applicate, cosa è stato escluso. Altrimenti il numero è invalido.
7. **Il significato lo definiscono gli umani, non i dati**: budget, voci PF, categorie → versionate, possedute da Rosa/Gasparotto/Mario/Antonio.
8. **Il drift si espone, non si nasconde**: pipeline stale, schema drift, fonti sovrapposte → alert visibili.
9. **Esplicito > clever**: no euristiche nascoste, no magic.
10. **Ottimizza per fiducia, non velocità**: correct > fast, traceable > elegant, auditable > automated.
11. **L'ambiguità si espone, non si risolve silenziosamente**: se la domanda ha più interpretazioni plausibili sulla **dimensione temporale** (CASSA vs COMPETENZA vs IMPEGNO), **società** (ORTI vs INTUR vs gruppo), **periodo** (YTD vs MTD vs rolling), o **fonte canonica** → enumera le opzioni e chiedi, non scegliere. Una risposta data sull'interpretazione sbagliata è peggio di una pausa.

## Layer Model — mappatura HotelOps

| Layer | Dove vive | Ruolo |
|---|---|---|
| **Raw** | `hotelops_datahub/canonical/{tipo}/{SOCIETA}/`, `ingresso/` | File originali, immutabili. Archive max 5 versioni per SNAPSHOT. |
| **Canonical** | BigQuery `F_*` / `D_*` | Fatti governati, post-Pydantic (**I1**), post-dedup / DEL-INS (**I2**). Tutti i write passano da `core.bq.write.bq_write_validated`. |
| **Semantic** | BigQuery `v_*` | Lenti di business (PF, BVA, cashflow, food cost). Una view = una lente = un'audience. |
| **Operational** | CLI (`hotelops ...`), Streamlit, NanoClaw, email cron | Qui vivono le persone. Mai logica di business. |

**Regola di localizzazione**: sintomo in Operational → indaga Semantic, poi Canonical, poi Raw. Mai fixare a valle ciò che è rotto a monte.

## Canonical Truth Registry

Una sola fonte per concetto. Tutto il resto è diagnostico o consumer-specific.

| Concept | Canonical source | Dimensione | Note |
|---|---|---|---|
| Saldo banca (corrente) | `f_saldi_banca_snapshot` + `f_banche_movimenti` | CASSA | - |
| Movimenti bancari | `f_banche_movimenti` (APPEND) | CASSA | Dedup MD5 |
| Movimenti contabili | `f_movimenti_contabili` (APPEND) | COMPETENZA | - |
| **Budget risolto** | **`v_budget_canonical`** (view) | COMPETENZA | ADR 2026-04-17 |
| Budget raw | `f_budget_mensile` (SNAPSHOT) | — | Solo ingest/debug |
| Piano Finanziario | `f_piano_finanziario_input` → `v_piano_finanziario_mensile` | CASSA | - |
| Partite aperte fornitori | `f_partite_aperte_fornitori` (SNAPSHOT) | IMPEGNO | - |
| Reviews | `f_reviews` (APPEND) | — | Watermark gate |
| Consumi economato | `f_consumi_economato` (APPEND) | — | - |
| Coperti | `f_coperti_giornalieri` (SNAPSHOT) | — | natural_key=hash_riga |
| Vendite F&B | `f_vendite_fb` (APPEND) | — | + segmento_cliente da Ristocube |
| Food cost mensile | `v_food_cost_mensile` | misto | YoY via LAG su anno |
| Food cost categoria | `v_food_cost_categoria` | misto | granulare per (sala, tipo_piatto, segmento) |

Mai calcolare saldo da movimenti contabili. Mai budget da view downstream diverse da `v_budget_canonical`. Se l'agente è tentato di "derivare al volo", **ferma** e chiedi quale canonical source applicare.

## Invarianti specifiche (ref. INVARIANTS.md)

- **I1 — Validation gate**: nessun write su BigQuery senza contratto Pydantic via `bq_write_validated`.
- **I2 — Lifecycle è legge**: APPEND o SNAPSHOT è proprietà semantica. Cambio = migration + decision esplicita.
- **I3 — Ontologia SSOT**: `<vault>/HotelOps/ontology/` è fonte di verità per nomi business (people, companies, banks). BQ si allinea al vault.
- **I4 — 3 dimensioni obbligatorie**: ogni fatto finanziario classificato su CASSA / COMPETENZA / IMPEGNO. L'agente **dichiara sempre la dimensione** nella risposta.
- **I5 — Classify deterministico**: routing file regex/content-based, mai LLM. Unica eccezione: `reviews` (testo libero).
- **I6 — Stagionalità è dominio**: forecast flat 1/12 è fuorviante. `d_coefficienti_stagionalita` obbligatorio in ogni scostamento.
- **I7 — Ogni vertical ha un nome umano**: Rosa, Gasparotto, Antonio, Mario. Senza persona → non è vertical.
- **I8 — Locality**: la row-selection (dedup, precedenza, risoluzione fonti) vive **nella canonical view**, non nel consumer (CLI, Streamlit, agente). Se un consumer filtra/deduplica, è un bug da rimandare upstream.
- **I9 — Raw boundary**: nuovi write canonical passano dal Raw Object GCS tracciato quando la source è nel regime `raw_storage.backend: gcs`; no ingest diretto senza lineage per nuove sorgenti.
- **I10 — Hub authz**: superfici operative sensibili nel hub richiedono registry, grant nominativo esplicito, re-check server-side e fail-closed. IAP autentica l'identità; non sostituisce i grant applicativi.

## Vocabolario canonico (use these names, nothing else)

- **Società**: `ORTI` (operator), `INTUR` (asset owner). Mai "Panorama" come entità legale.
- **Gruppo**: `Gruppo Panorama` (non formale, consolidato economico). DSCR e debt coverage si valutano **sempre a livello gruppo**.
- **Dimensioni**: `CASSA` (💰), `COMPETENZA` (📊), `IMPEGNO` (📅).
- **Lifecycle**: `APPEND` (♻️), `SNAPSHOT` (📸).
- **Personas**: Rosa (amministrazione + tesoreria), Roberto Romita (consulente CdG), Antonio Russo (GM/reputation), Mario (economato), Stefano Della Pietra Jr (owner platform — distinto da Stefano Sr, AU ORTI).
- **File ≠ persona**: "Gasparotto" è il **nome del file Master Excel di Roberto Romita** (legacy come label di persona — da retire nel parlato; resta valido come nome di file/fonte, es. `f_budget_mensile.fonte=GASPAROTTO`, `ingest_gasparotto.py`). Rosa ha invece il suo file scadenziario fornitori in Drive (letto da `condges/scadenzario_excel.py`). I due Excel convergono in `app_cdg.py` via codici Esolver + mapping fornitori.
- **Verticals attivi**: `CONDGES`, `REVIEWS`. `ECONOMATO` è **dati-only** (in arrivo, owner: Mario) — oggi non è vertical per **I7**, è infrastruttura in attesa di audience.
- **Gotcha conti**: `codice_conto` ha doppio formato (`570913` vs `57.09.13`). Sempre `REPLACE(codice_conto, '.', '')` in JOIN cross-fonte.

## Loop operativo — prima di ogni risposta

Ogni domanda passa da questo loop. Nessuna scorciatoia.

0. **Disambiguazione**: la richiesta è univoca su dimensione/società/periodo/fonte? Se no → ferma, enumera le letture plausibili, chiedi quale. Non procedere con un'assunzione implicita.
1. **Identifica il concept** (budget? saldo? review? consumo?)
2. **Individua la canonical source** (vedi Registry sopra).
3. **Scegli la dimensione temporale** corretta (CASSA / COMPETENZA / IMPEGNO).
4. **Verifica**: freshness (ingestion_ts recente?), completeness (gap di periodo?), lineage (quale pipeline?).
5. **Se fonti multiple contribuiscono**: NON mediare. Esponi il conflitto e la regola di precedenza.
6. **Rispondi dichiarando**: (a) fonte canonical, (b) dimensione, (c) incertezze/assunzioni, (d) cosa è stato escluso.

Esempio: *"💰 CASSA — saldo ORTI MPS €134.2K al 2026-04-16 (fonte: f_saldi_banca_snapshot, ultimo import 2026-04-17 08:00). Non include 2 movimenti pending (€-8.5K) visibili in homebanking ma non ancora in f_banche_movimenti."*

## Loop di verifica — dopo ogni azione

Il Loop operativo copre *prima* di rispondere. Questo copre *dopo* aver scritto/modificato. Un'azione non è "completa" finché non è **verificata**, e la verifica non è "il comando non ha fallito" — è una query che conferma il risultato atteso.

Regola: **output-based, non exit-code-based**. Success criteria verificabili prima di dichiarare done.

| Azione | Verifica richiesta (minima) |
|---|---|
| Write a `F_*` (ingest) | `SELECT MAX(ingestion_ts), COUNT(*) FROM <tabella>` → avanzato? match atteso? |
| Modifica `v_*` (canonical o semantic) | Query di spot-check su chiavi note pre/post → output cambia solo dove deve |
| Modifica `D_*` o CSV in `core/bq/dimensioni/` | Ontology alignment: valori in `D_*` ⊆ vault `ontology/` (I3) — nessun orfano |
| SNAPSHOT write (DEL-INS) | Row count post-write match atteso, no periodo orfano. Idempotency check (re-run = stesso risultato). |
| Dedup / row-selection change in canonical view | Count duplicati su chiave prima/dopo → zero residui |
| Pipeline change (ingest o classify) | Dry-run + sample verificato, contract Pydantic green, pipeline_runs OK |
| Forecast / proiezione | Stagionalità applicata? (`d_coefficienti_stagionalita` presente in query) |
| Commit git (sessioni concorrenti) | `git branch --show-current` == branch atteso **prima** di ogni commit — lo snapshot gitStatus di harness è statico, non riflette switch fatti da altre sessioni |

Se non posso eseguire la verifica (credenziali, environment), **lo dichiaro esplicitamente** invece di claim di successo: *"Script eseguito senza errori; non verificato MAX(ingestion_ts) perché fuori ambiente."* Evidence before assertion.

Anti-pattern: *"Ho ingerito le partite aperte"* senza aver interrogato la tabella. *"Ho fixato il dedup"* senza un count-by-key. *"Ho allineato D_fornitori"* senza aver letto sia il vault `ontology/` sia il CSV.

**Multi-sessione (worktree isolation)**: più sessioni Claude sullo stesso working dir condividono **un solo HEAD** — uno `checkout` in una sposta il branch sotto le altre, in silenzio, e un commit atterra sul branch sbagliato. Mitigazione: **un git worktree per sessione concorrente** (`git worktree add ../hotelops-<scope> <branch>`). Recovery se il commit è già finito sul branch sbagliato: worktree del branch giusto → `cherry-pick <commit>` → `reset --hard HEAD~1` sull'altro (pulito se i commit non hanno overlap di file). Vedi `vault/sessions/2026-06-08_produzione_pms_backfill_and_worktree_fix`.

## Drift detectors obbligatori

Il sistema espone (non nasconde) allarmi su:
- **Freshness**: `MAX(ingestion_ts)` per fact table → stale = alert.
- **Watermark reviews**: `MAX(data_review)` per piattaforma/BU → gap detection.
- **KPI di invariante**: `rent_coverage_ratio < 1.5` (warning) / `< 1.2` (critical); `beach_attribution_pct < 90%`.
- **Schema drift**: Pydantic contract fail = pipeline **stop**, non log-and-continue.
- **Ontology drift**: valori in `D_*` non presenti nel vault `ontology/` → flag.
- **Boundary drift**: row che supera Pydantic ma fallisce `json.dumps` → `SerializationBoundaryError` (vedi gate I1).
- **Authz drift hub**: app sensibile senza `sensitive=True`, grant implicito tramite gruppo, pagina senza re-check `current_apps()` o fallback non fail-closed.

## Anti-goals (specifici HotelOps)

L'agente **non deve mai**:
- Inventare dati o stime non esplicite.
- Mediare/sommare silenziosamente fonti incompatibili.
- Bypassare la canonical view "per rispondere più in fretta".
- Calcolare DSCR standalone ORTI (sempre gruppo).
- JOIN su `codice_conto` senza normalizzare i punti.
- Usare LLM in `classify.py` (eccetto reviews).
- Creare nuove entità (società, banca, categoria, fornitore strategico) in codice/CSV senza prima una nota nel vault `ontology/` (**I3**).
- Duplicare logica di row-selection/dedup nei consumer (**I8**).
- Produrre numeri che non sa giustificare.

## Lineage eras

HotelOps has two archaeological layers in `f_raw_objects`. Understanding which era a raw object belongs to is critical before making provenance claims.

| Era | `lineage_era` | `raw_backend` | `intake_at` | Provenance trust |
|---|---|---|---|---|
| **Pre-Phase-4** | `'pre_phase4'` (or NULL) | `drive` / `local` | < 2026-05-05 | Partial. raw_uri may be stale. FK to canonical (`raw_object_id`) may be absent. |
| **Live (GCS)** | `'live'` | `gcs` | ≥ 2026-05-05 | Full. gs:// URI stable, content_hash verified, FK present after promotion. |

**Canonical rows with `raw_object_id IS NULL`** are pre-lineage: ingested before Phase 1 launched. Provenance is absent — but canonical data is trusted. This is honest architecture.

### Lineage confidence vocabulary

When reasoning about provenance, use this vocabulary (informational, not enforced at BQ level):

| Confidence | When | Meaning |
|---|---|---|
| `NONE` | canonical row has `raw_object_id IS NULL` | Pre-lineage era. No raw file tracked. Trust canonical data; provenance absent. |
| `PARTIAL` | `lineage_era='pre_phase4'` OR FK present but not GCS-backed | Raw row registered, but file may be on Drive/local (path may not resolve). |
| `VERIFIED` | `lineage_era='live'`, FK chain intact, hash matches promotion record | Full chain: GCS file → intake → promote → canonical row. Replayable. |
| `RECONSTRUCTED` | retroactively backfilled post-hoc | Use only for legally/compliance-required backfill. Mark as RECONSTRUCTED — never present as VERIFIED. |

**Rules:**
- Do not claim `VERIFIED` for pre-Phase-4 rows.
- Do not backfill retroactively unless legally required. Accept `NULL` FK as honest provenance gap.
- The **value of lineage is forward integrity**, not retroactive perfection.
- Cutoff constant: `core.lineage.schemas.PHASE4_GCS_CUTOFF = 2026-05-05T00:00:00Z`



- Nasce una nuova canonical source → aggiorna §Canonical Registry.
- Nuovo invariant in `INVARIANTS.md` → rispecchialo qui in §Invarianti.
- Nuova persona / vertical → §Vocabolario.
- Nuovo drift detector → §Drift detectors.

**Non aggiornare qui**: conteggi di tabelle, elenchi di view, comandi CLI, schemi. Quelli vivono in `CLAUDE.md` del repo, vicini al codice.

---

## One-line compression

> *Reason from raw → canonical → semantic → operational, enforce one canonical truth per concept, declare the temporal dimension, and ensure every output is explainable, traceable, and complete.*
