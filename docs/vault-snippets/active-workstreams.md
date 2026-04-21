# HotelOps — Active Workstreams

**Last update:** 2026-04-21 (post-swarm audit)
**Purpose:** cross-session glossary + workstream state. Load as first-read when opening any new Claude Code instance on hotelops, to re-enter the context without repeating vocabulary clarification.
**Destination finale:** `<vault>/hotelops/active-workstreams.md` (copia da qui dopo review).

## 🚨 Modalità corrente: REFACTOR before NEW CODE

**Le due sessioni S1 + S2 sono state chiuse dopo lo swarm audit del 2026-04-21.** Stato di ciascuna al momento della chiusura:

- **S1**: WI-1 completato (decoder timedelta + parser CE cross-ref), dry-run clean (1380 rows, 0 UNMAPPED, 257/257 tests pass). BQ DELETE+INSERT su `f_budget_mensile` NON ESEGUITO — rimandato post-refactor.
- **S2**: Walkthrough + spec rewritten; plan era in fase di Write dopo Read precondition soddisfatta, **rimandato**.

La nuova istanza opera sul **refactor roadmap consolidato** prima di proseguire con:
1. Nuovo codice Projects vertical (S2)
2. WI-2/WI-3/WI-4 di Condges Rosa→Gasparotto (S1)
3. BQ writes destructive rimandati

**👉 Leggi `docs/vault-snippets/refactor-roadmap.md` come secondo file.** Contiene Fase 0 (blockers) + Fase 1 (foundations cross-layer) + Fase 2 (per-layer cleanup) + Fase 3 (prep Projects).

---

## Canonical vocabulary (NON negoziabile)

- **Modello Gasparotto** — il modello finanziario multi-foglio strategico. Vive oggi come Excel con 8 sheet (`Stato Patrimoniale`, `Rating`, `Vendite`, `Conto Economico`, `Budget`, `Cash-Flow`, `invesitmneti` [sic, vuoto], `Indicatori`) + VBA + 9K formule. Il modello in sé è il contenuto semantico, non il file.

- **Rosa** — **NON** un vertical, **NON** un peer di Gasparotto. È letteralmente **un foglio del modello Gasparotto** (il Cash-Flow), estratto come file standalone perché Rosa dell'amministrazione ha un workflow operativo dedicato: ogni 1° del mese genera un nuovo file partendo dai saldi banca end-of-prev-month + scadenziario fornitori, aggiornato via Streamlit app `condges/app_scadenzario.py`. Il file non evolve — è snapshot atomico mensile.

- **CONDGES vertical** (esistente, in evoluzione) — la app multi-foglio che unifica Rosa + Gasparotto in una UI letta da BQ. Base: `condges/app_cdg.py` (1265 LOC, 4 tab attuali: CE, Budget, Tesoreria, Indicatori). Target: 8 tab corrispondenti agli 8 fogli Gasparotto.

- **Progetti vertical** (nuovo, 4°) — project subledger per cantieri capex. Entità: Project, ScopePackage, Document, Commitment, PaymentSchedule, + link tables. Vive in nuova cartella `progetti/`. Target: HPAN25PIANO1 (in corso), Lido Spiaggia (future), N altri.

---

## Bridge Progetti ↔ CONDGES (unico punto di contatto)

**Forward-flow, opzionale, asimmetrico:** Progetti scrive a CONDGES, mai viceversa.

```
Progetti.Commitment (stato ∈ FIRMATO | IN_CORSO)
  + Progetti.PaymentSchedule (rate future non fatturate)
    ↓
  f_piano_finanziario_input (
      societa_pagante,
      voce_id = INVESTIMENTI_CAPEX  if capex+INTUR
              = voce_opex_lookup    if opex (es. PM fee)
      mese,
      importo,
      fonte = PROGETTI    ← valore nuovo nel dominio `fonte`
    )
    ↓
  CONDGES tab Cash-Flow (legge `v_piano_finanziario_mensile`)
  CONDGES tab Investimenti (future — legge filtrato voce=INVESTIMENTI_CAPEX)
```

### Regola allocazione costi (business rule, NON invariant platform)

- Capex su immobili di proprietà → società proprietaria (INTUR per Hotel Panorama, immobili Maiori)
- Opex operazioni → società operativa (ORTI per gestione hotel+residence+CVM)
- Eccezione: consulenze/PM su progetti capex = opex della società operativa che impiega il servizio (es. PM Hospitality Project = opex ORTI anche se il progetto è capex INTUR)
- Eccezione intercompany: fitto ORTI→INTUR si elide in consolidato

Documentata in `<vault>/hotelops/ontology/business-rules/capex-opex-allocation.md`. NON in `INVARIANTS.md` (vedi motivo sotto).

---

## Session 1 — Condges Rosa→Gasparotto integration

| | |
|---|---|
| **Spec** | `docs/superpowers/specs/2026-04-20-condges-rosa-gasparotto-design.md` (commit `caad836`) |
| **Plan** | `docs/superpowers/plans/2026-04-21-condges-rosa-gasparotto-plan.md` (commit `beddc7e`, 12 task, 4 WI) |
| **Stato** | plan completo, in attesa esecuzione inline con checkpoint per-WI |
| **Invariante I9** | `f_piano_finanziario_input` è unica SoT per cashflow. No reverse ingest di rendering. |

### Scoperte chiave del piano (da non rifare se si riapre la sessione)

1. Sheet "Budget" del workbook Gasparotto è **entirely formula-driven** (`='Conto Economico'!...`); il parser va riscritto su sheet `Conto Economico`.
2. Col A di CE ha **cod_conto corrotti a timedelta** (es. `47.91.03` → `timedelta(days=2, seconds=1863)`). Decoder con prefix-context da righe vicine. 4 casi fixture validati (R11, R18, R20, R22).
3. Task 2 (parser CE) dipende da Task 7 (force_recalc LibreOffice) perché anche CE col L è cached-only.
4. Workbook ha 9K formule + VBA + 48 defined names (20 di Lotus 1-2-3 legacy) + 60 merged ranges. Nessun chart/pivot. openpyxl survivable ma richiede test round-trip e `libreoffice --headless` per ricomputare cached values.
5. Cash-Flow sheet del workbook è **supplier-level** (40+ righe vendor); `f_piano_finanziario_input` è **voce-level** (28 aggregate). **Divergenza accettata** — app_cdg resta voce-level; supplier-level coperto dal vertical Progetti via forward-flow per i cantieri.

### Cosa S1 deve sapere di S2

- Aggiungere nuova voce `INVESTIMENTI_CAPEX` a `d_voci_piano_finanziario` (fonte=MANUALE, pattern vuoto perché arriva via forward-flow, non via LIKE Esolver)
- Aggiungere `PROGETTI` al dominio del campo `fonte` di `f_piano_finanziario_input`
- Il tab Cash-Flow in WI-2 deve supportare il badge `fonte=PROGETTI` (già specificato nel plan)

---

## Session 2 — Projects MVP

| | |
|---|---|
| **Walkthrough** | `docs/progetti/HPAN25PIANO1-walkthrough.md` |
| **Seed data** | `docs/progetti/HPAN25PIANO1-seed-data.md` (importi reali Excel + mapping vendor best-guess) |
| **Spec** | `docs/superpowers/specs/2026-04-20-projects-mvp-design.md` (commit `1cc4201`, **STALE** post-reframe — va riscritto) |
| **Plan** | `docs/superpowers/plans/2026-04-20-projects-mvp.md` (**STALE** post-reframe — va riscritto) |
| **Stato** | walkthrough HPAN25PIANO1 completato, blocchi 4+5 risolti, rewrite spec+plan in corso |

### Decisioni di modello consolidate

1. 4° vertical `progetti/` (NON extension di CONDGES)
2. Entità: Project, ScopePackage, Document (types: Preventivo/Contratto/Fattura/Altro), Commitment, PaymentSchedule, + `f_progetto_scope_commitment_link` (N:M) + `f_progetto_invoice_link` (join a `f_movimenti_contabili`)
3. ScopePackage può esistere **senza vendor** (solo scope + `importo_stimato_eur` manuale) — legittimo
4. `Commitment.importo_impegnato_eur` **immutabile dopo firma**. Overrun = varianza tracciata in `v_commitment_status`, NON update
5. `Commitment.societa_pagante_id` **obbligatorio** — non derivabile da progetto (un progetto può avere più paganti)
6. Granularità ScopePackage = lotto di lavoro coerente (es. porte standard ≠ porte REI)
7. Budget view cascade: `COALESCE(impegnato, max(preventivo), stimato)`
8. `stato_censimento` su `d_anagrafica_fornitori` (`DA_CENSIRE / CENSITO / ATTIVO`). Commitment snapshot denormalizzato alla creazione.
9. `Document.stato_preventivo` = `RICEVUTO | ACCETTATO | RIFIUTATO | SCADUTO`
10. `Commitment.from_document_id` opzionale → tracciabilità preventivo → contratto
11. Regola capex/opex → società = **business rule vertical, NON invariant platform**

### Decisione blocchi 4+5 (2026-04-21)

**Blocco 4: Voce PF target per forward-flow** → nuova `INVESTIMENTI_CAPEX` (non riuso voce esistente). Motivazioni: semantica distinta da opex, sheet `invesitmneti` del workbook Gasparotto come ponte naturale, costo implementazione minimo. Il forward-flow è non uniforme: if `societa=INTUR AND tipo=capex → INVESTIMENTI_CAPEX`; else `lookup_opex_voce(categoria_scope)`.

**Blocco 5: I10 candidate** → **RITIRATO**. La regola capex/opex→società è policy business, non invariant strutturale. Motivazioni: impatto retroattivo su fact tables già popolate, gruppo-specificità (ORTI/INTUR struttura propria di Gruppo Panorama), evoluzione futura possibile. Vive in vault ontology, enforcement a data-entry via UI warning.

### Cosa S2 deve sapere di S1

- Commitments di Progetti NON sono scritti direttamente in `f_movimenti_contabili` o `f_banche_movimenti` — quelli restano CASSA effettiva da Esolver/banche
- PaymentSchedule è l'unico punto di scrittura forward, su `f_piano_finanziario_input` fonte=PROGETTI
- La nuova voce `INVESTIMENTI_CAPEX` deve esistere in `d_voci_piano_finanziario` prima che S2 possa scrivere forward-flow — coord con S1 WI-1 se aggiunge la voce
- I9 invariante (CASSA SoT) va rispettata: Progetti forward-writes solo, mai reverse-reads di rendering

---

## Reality check HPAN25PIANO1 (dai seed data)

- **Cap dichiarato:** 1.200.000 EUR
- **Buffer nominale:** 116.434 EUR
- **Overrun già consumato:** AMCN +37.539 + STE +5.085 = **42.624 EUR**
- **Buffer reale residuo:** **73.810 EUR**
- **Righe ancora a effettivo=0:** SANTELIA 86K + Metal 2000 107K + Arredi 285K + Spese Tecniche 91K + Imprevisti 38K = **607K residui**
- **Proiezione sforamento se disciplina non si stringe:** 50-150K

Il buffer reale (73K) è inferiore al 7% del residuo da pagare (607K). **Margine operativo ridotto** — qualsiasi overrun sulle 5 macro non ancora fatturate lo consuma.

---

## Open items cross-session

- [ ] File `01_26_25_budget_cost_1_piano_10_cam_COMPLETO.xlsx` — Stefano carica in Cowork o aggiunge al repo. Contiene split individuali professionisti + mapping vendor arredi (assente nel file disponibile).
- [ ] **Capone TV** — ragione sociale canonica (disambiguare da "Anna Capone" persona/Studio Ninni)
- [ ] **Metal 2000 scope** — confermato = infissi esterni (da seed data, doc ref `20260107-PREVENTIVO_infissi_aggiornato.pdf`)
- [ ] **Dierre bucket** — confermato = (b) contratto firmato (vault ordine 864 + 12K porte standard nel tab 02)
- [ ] Atelier Hospitality, Studio Ninni, Rino Cuomo — preventivi ancora attivi? importi?
- [ ] Allocazione IMPREVISTI 38K — cassa generica o prealloc a scope?
- [ ] Regola business capex/opex → file vault da creare: `<vault>/hotelops/ontology/business-rules/capex-opex-allocation.md`

---

## How to use this file

1. **Apertura nuova CC instance:** "Leggi `docs/vault-snippets/active-workstreams.md` prima di qualsiasi altra cosa" → riparti con context coerente, niente replay di vocabolario.
2. **Dopo modifiche importanti in una sessione:** aggiorna la sezione rilevante qui, committa. Data-stampa in alto.
3. **Non è una spec** — è lo stato corrente delle sessioni. Le spec autoritative sono nei file `docs/superpowers/specs/`.
4. **Questo file nasce come vault-snippet** — destinazione finale in `<vault>/hotelops/active-workstreams.md` dopo review. In repo serve come artefatto committato per ogni CC instance.
