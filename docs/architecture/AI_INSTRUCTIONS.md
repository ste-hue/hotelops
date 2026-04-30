---
type: ai_instructions
domain: HotelOps
audience: AI agents (Claude Code, NanoClaw, Cron agents, future)
last_updated: 2026-04-30
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

## Vocabolario canonico (use these names, nothing else)

- **Società**: `ORTI` (operator), `INTUR` (asset owner). Mai "Panorama" come entità legale.
- **Gruppo**: `Gruppo Panorama` (non formale, consolidato economico). DSCR e debt coverage si valutano **sempre a livello gruppo**.
- **Dimensioni**: `CASSA` (💰), `COMPETENZA` (📊), `IMPEGNO` (📅).
- **Lifecycle**: `APPEND` (♻️), `SNAPSHOT` (📸).
- **Personas**: Rosa (tesoreria), Gasparotto (budget/CdG), Antonio Russo (GM/reputation), Mario (economato), Stefano Della Pietra Jr (owner platform — distinto da Stefano Sr, AU ORTI).
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

Se non posso eseguire la verifica (credenziali, environment), **lo dichiaro esplicitamente** invece di claim di successo: *"Script eseguito senza errori; non verificato MAX(ingestion_ts) perché fuori ambiente."* Evidence before assertion.

Anti-pattern: *"Ho ingerito le partite aperte"* senza aver interrogato la tabella. *"Ho fixato il dedup"* senza un count-by-key. *"Ho allineato D_fornitori"* senza aver letto sia il vault `ontology/` sia il CSV.

## Drift detectors obbligatori

Il sistema espone (non nasconde) allarmi su:
- **Freshness**: `MAX(ingestion_ts)` per fact table → stale = alert.
- **Watermark reviews**: `MAX(data_review)` per piattaforma/BU → gap detection.
- **KPI di invariante**: `rent_coverage_ratio < 1.5` (warning) / `< 1.2` (critical); `beach_attribution_pct < 90%`.
- **Schema drift**: Pydantic contract fail = pipeline **stop**, non log-and-continue.
- **Ontology drift**: valori in `D_*` non presenti nel vault `ontology/` → flag.
- **Boundary drift**: row che supera Pydantic ma fallisce `json.dumps` → `SerializationBoundaryError` (vedi gate I1).

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

## Quando aggiornare questo file

- Nasce una nuova canonical source → aggiorna §Canonical Registry.
- Nuovo invariant in `INVARIANTS.md` → rispecchialo qui in §Invarianti.
- Nuova persona / vertical → §Vocabolario.
- Nuovo drift detector → §Drift detectors.

**Non aggiornare qui**: conteggi di tabelle, elenchi di view, comandi CLI, schemi. Quelli vivono in `CLAUDE.md` del repo, vicini al codice.

---

## One-line compression

> *Reason from raw → canonical → semantic → operational, enforce one canonical truth per concept, declare the temporal dimension, and ensure every output is explainable, traceable, and complete.*
