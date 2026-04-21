# HPAN25PIANO1 Walkthrough — Projects MVP model validation

**Progetto:** HPAN25PIANO1 — Camere Primo Piano Hotel Panorama (10 camere, Q1-Q2 2026)
**Cap:** 1.200.000 EUR
**Speso+Committed dichiarato:** ~1.084.000 EUR (da Excel attuale, user brief)
**Buffer residuo:** ~116.000 EUR
**Obiettivo:** validare il modello `ScopePackage + Commitment + PaymentSchedule + Document` su 25 vendor reali, produrre decomposizione del cap 1.2M, far emergere raffinamenti del modello e vault drift.

---

## Entity model in prova

- **Project** — una riga in `d_progetti`. Budget cap societa-agnostico.
- **ScopePackage** — unità di lavoro / WBS node, budget-bearing. Stati: `IDENTIFICATO → PREVENTIVATO → IMPEGNATO → CHIUSO`. Può esistere senza vendor (solo scope + `importo_stimato_eur` manuale).
- **Document** — `Preventivo | Contratto | Fattura | Altro`. FK `scope_package_id`. `stato_preventivo` (RICEVUTO / ACCETTATO / RIFIUTATO / SCADUTO).
- **Commitment** — obbligazione formale verso un vendor. Stati: `FIRMATO → IN_CORSO → CHIUSO (+ ANNULLATO)`. Ha `societa_pagante_id` (obbligatorio). `importo_impegnato_eur` è fisso alla firma.
- **PaymentSchedule** — ripartizione temporale del Commitment in rate di cassa. Feed forward a `f_piano_finanziario_input` fonte=`PROGETTI`.
- **InvoiceLink** — join `f_progetto_invoice_link` fra Commitment e `f_movimenti_contabili`.
- **Link N:M** — `f_progetto_scope_commitment_link(scope_package_id, commitment_id, quota_importo_eur)`.

---

## Vendor table

Legenda:
- `importo_eur` è il valore rilevante per lo stato: fatturato se bucket (a), committed se (b), preventivo se (c), stima manuale se (d).
- `stato_esolver`: `DA_CENSIRE` = nessun codice Esolver; `CENSITO` = in `d_anagrafica_fornitori`; `ATTIVO` = con movimenti in `f_movimenti_contabili`; `?` = da verificare.
- `<excel>` = importo non fornito nel brief, da recuperare da `01_26_25_budget_cost_1_piano_10_cam_COMPLETO.xlsx`.

| # | bucket | vendor | scope | societa_pagante | importo_eur | stato | stato_esolver | note |
|---|---|---|---|---|---|---|---|---|
| 1 | (a) | AMCN | Opere murarie strutturali | INTUR? | 413.000 fatturato (vs 375.000 committed) | FATTURATO — overrun +37K | ? | Rottura #1: `importo_fatturato > importo_impegnato`. Testa `v_commitment_status.delta_overrun_eur`. |
| 2 | (a) | STE srl | Impiantistica elettrica | INTUR? | <excel> parziale | FATTURATO parz. + IN_CORSO residuo | CENSITO (vault) | Contratto firmato 27/02/2026. SUM(invoice_link) < Commitment.importo_impegnato → residuo su PaymentSchedule. |
| 3 | (b) | SANTELIA | Impianti meccanici + idrico-sanitari | INTUR? | 86.000 | FIRMATO → IN_CORSO | CENSITO (vault) | Contratto firmato 27/02/2026. |
| 4 | (b) | Metal 2000 | Carpenteria metallica/infissi ? | INTUR? | 107.000 | FIRMATO → IN_CORSO | ? | **Scope da confermare** (il brief non specifica: carpenteria vs infissi vs altro). |
| 5 | (b?) | Dierre | Porte standard | INTUR? | <excel> | FIRMATO (ordine n.864 conf. 27/02) | CENSITO (vault) | **Ambiguità bucket**: user lo mette in (d); vault ha ordine confermato → sarebbe (b). Da risolvere. |
| 6 | (c) | Archisavio (Savio Marigliano) | Progettazione architettonica | INTUR | <excel> | PREVENTIVO | DA_CENSIRE | Document=Preventivo su ScopePackage "Progettazione architettonica". Nessun Commitment. |
| 7 | (c) | Amalia Pisacane | Direzione lavori (ingegneria) | INTUR | <excel> | PREVENTIVO | DA_CENSIRE | **Drift naming**: brief "Amalisa" vs vault "Amalia". Canonical = Amalia. |
| 8 | (c) | NESE | Progettazione impianti | INTUR | <excel> | PREVENTIVO | DA_CENSIRE | Diverso da STE/Santelia (quelli sono esecuzione; NESE è progettazione). |
| 9 | (c) | Hospitality Project | Project management | **ORTI** | <excel> | PREVENTIVO | ? | Rottura #3: unico (c) pagato da ORTI. Testa `Commitment.societa_pagante_id`. Regola business: PM fee = opex ORTI; capex struttura = INTUR. |
| 10 | (c?) | Studio Ninni (ref. Anna Capone) | Armadi + cucine | INTUR? | <excel> | PREVENTIVO (vault 21/02/2026, 30gg) | CENSITO (vault) | **Riclassifica proposta**: brief lo implica in (d); vault dice preventivo acquisito → (c). Da confermare. |
| 11 | (c?) | Atelier Hospitality | Arredi camere | INTUR? | <excel> | PREVENTIVO (vault) | CENSITO (vault, TACTICAL) | **Riclassifica proposta**: vault dice "preventivo acquisito" → (c), non (d). Non elencato esplicitamente dall'user. |
| 12 | (d) | Rino Cuomo | Falegnameria custom | INTUR? | <excel> | IDENTIFICATO | DA_CENSIRE | ScopePackage orfano. |
| 13 | (d) | Sicigniano | Piastrelle (materiale) | INTUR? | <excel> | IDENTIFICATO | DA_CENSIRE | |
| 14 | (d) | — | Piastrellista (posa) | INTUR? | <excel> | IDENTIFICATO | **NO VENDOR** | Rottura #5a: ScopePackage senza vendor, solo scope + stima. |
| 15 | (d) | Dorelan | Letti | INTUR? | <excel> | IDENTIFICATO | DA_CENSIRE | |
| 16 | (d) | Domus | Testiere + tende | INTUR? | <excel> | IDENTIFICATO | DA_CENSIRE | |
| 17 | (d) | Floor | Moquette | INTUR? | <excel> | IDENTIFICATO | DA_CENSIRE | |
| 18 | (d) | Indelb | Frigo + cassaforte camera | INTUR? | <excel> | IDENTIFICATO | DA_CENSIRE | |
| 19 | (d) | Capone (elettronica?) | TV | INTUR? | <excel> | IDENTIFICATO | DA_CENSIRE | **Ambiguità #2**: vault ha "Anna Capone" (persona, di Studio Ninni, interior design). Brief ha "Capone: TV" → presumibilmente vendor aziendale distinto (elettronica). Richiede nome canonico disambiguato. |
| 20 | (d) | Zara | Comodini | INTUR? | <excel> | IDENTIFICATO | DA_CENSIRE | |
| 21 | (d) | Illuxit | Luci camere | INTUR? | <excel> | IDENTIFICATO | DA_CENSIRE | |
| 22 | (d) | — | Luci balconi | INTUR? | <excel> | IDENTIFICATO | **NO VENDOR** | ScopePackage senza vendor. |
| 23 | (d) | Flab | Doccia + specchi bagno | INTUR? | <excel> | IDENTIFICATO | DA_CENSIRE | |
| 24 | (d) | VDA | Domotica / automation camera | INTUR? | <excel> | IDENTIFICATO | DA_CENSIRE | |
| 25 | (d) | CSC | Porte REI (antincendio) | INTUR? | <excel> | IDENTIFICATO | DA_CENSIRE | Scope distinto da Dierre → due ScopePackage "porte standard" (#5) + "porte REI" (#25). Rottura #6. |
| 26 | (d) | Geberit + Frattini + Rocky + Comoda (da vault) | Igienici e rubinetteria | INTUR? | <excel> | IDENTIFICATO | parz. CENSITO | 4 vendor in vault, ma nessun contratto/ordine citato. Brief non li elenca esplicitamente. |
| 27 | (d) | — | Segnaletica interna | INTUR? | <excel> | IDENTIFICATO | **NO VENDOR** | |
| 28 | (d) | — | Sedie + tavoli camera | INTUR? | <excel> | IDENTIFICATO | **NO VENDOR** | Possibile Atelier Hospitality → riclassifica (c)? |

> Note sulla conta: brief stimava 25 vendor. Tabella ha 28 righe perché (i) ho splittato Dierre vs CSC (porte std vs REI); (ii) ho aggiunto Atelier Hospitality + Studio Ninni dal vault; (iii) i 4 igienici vault sono raggruppati in una sola riga. Righe con `— NO VENDOR` sono ScopePackage orfani senza fornitore identificato.

---

## Validation per bucket

### (a) Fatture pagate

**Rotture testate:**
- **#1 AMCN overrun +37K.** Il modello deve distinguere `Commitment.importo_impegnato_eur` (fisso alla firma) da `importo_fatturato_cum_eur` (derivato, da InvoiceLink). Nasce view `v_commitment_status` con colonne `delta_overrun_eur`, `residuo_eur`, `stato_overrun` (`OK` / `WARN >5%` / `ALERT >10%`). Overrun **non** aggiorna il Commitment originale — diventa varianza tracciata.
- **STE parziale.** `SUM(invoice_link.importo) < Commitment.importo_impegnato` → `residuo_eur` alimenta PaymentSchedule per le rate future.

**Gap emerso:** `v_progetto_invoice_link` serve come view materializzata con `importo_fatturato_cum_eur` per `commitment_id`.

### (b) Contratti firmati in corso

**Rotture testate:**
- `Commitment.stato = FIRMATO | IN_CORSO` + PaymentSchedule attivo.
- Forward-flow: solver genera righe `f_piano_finanziario_input` fonte=`PROGETTI` per ogni rata non ancora fatturata.

**Gap emerso:**
- **Voce PF target per forward-flow: DECISIONE APERTA.** Opzioni: (i) nuova voce `INVESTIMENTI_CAPEX` in `d_voci_piano_finanziario`; (ii) riuso voce esistente (es. "Costi straordinari"). Richiede allineamento con Session 1 (Gasparotto Cash-Flow) se quella sessione ristruttura `d_voci_piano_finanziario`.
- Granularità forward-flow: `(societa_pagante × voce × mese)`. Scope progetto NON è dimensione PF — si aggrega via `progetto_id` solo nella dashboard progetti.

### (c) Preventivi non firmati

**Rotture testate:**
- **#4 Document type=Preventivo su ScopePackage, NO Commitment.** N Preventivi possibili per stesso ScopePackage (comparison). `Commitment.from_document_id` opzionale per tracciare quale Preventivo è diventato impegno.
- **#3 Hospitality Project pagato ORTI.** `Commitment.societa_pagante_id` obbligatorio e binding.

**Gap emerso:**
- **Regola business** (candidate I10 vertical): capex struttura → società proprietaria immobile (INTUR); costi operativi (PM, consulenze) → società operativa (ORTI). Vincola `societa_pagante_id` al tipo di spesa.
- `Document.stato_preventivo` = `RICEVUTO | ACCETTATO | RIFIUTATO | SCADUTO`.
- Preventivi dei bucket (c) reali: Archisavio + Pisacane + NESE + Hospitality Project + (da vault) Studio Ninni + Atelier Hospitality = **6 preventivi pending**, non 4.

### (d) Orfani senza preventivo

**Rotture testate:**
- **#5 ScopePackage con 0 Document + 0 Commitment + `importo_stimato_eur` manuale.**
- **#5a ScopePackage senza vendor** (es. "Piastrellista posa", "Luci balconi", "Segnaletica interna", "Sedie+tavoli"). Legittimo: solo scope + stima.
- **#6 Granularità ScopePackage = lotto di lavoro coerente**, non categoria generica. "Porte" si splitta in "porte standard" (Dierre) + "porte REI" (CSC). Stesso per piastrelle: materiale (Sicigniano) vs posa (piastrellista).
- **stato_esolver=DA_CENSIRE** per ~15 vendor nuovi → pipeline entity_protocol_v1 (candidate → approved → active).

**Gap emerso:**
- Budget view fa cascade `COALESCE(commitment.importo_impegnato, max(preventivo.importo), scope.importo_stimato)` per ciascun ScopePackage.
- Vendor DA_CENSIRE richiedono triage CORE / TACTICAL / TRANSIENT via `ENTITY_REVIEW.md` prima di creare entry in `d_anagrafica_fornitori`.

---

## Budget decomposition (pre-Excel)

| Componente | Importo noto (K EUR) | Fonte |
|---|---:|---|
| (a) AMCN fatturato | 413 | user brief |
| (a) STE fatturato parziale | `<excel>` | user brief |
| (b) SANTELIA committed | 86 | user brief |
| (b) Metal 2000 committed | 107 | user brief |
| (b) Dierre committed | `<excel>` | vault (ordine n.864) |
| **Sub-total (a)+(b) noto** | **606 + STE + Dierre** | — |
| **Sub-total (a)+(b) user-dichiarato** | **~1.084** | user brief |
| **Implied residuo (STE + Dierre + altri)** | **~478** | 1.084 − 606 |
| (c) Preventivi pending (6 vendor) | `<excel>` — stima 60–100K (fees 5–8% di 1.2M) | — |
| (d) Orfani (17 item) | `<excel>` — stima 300–400K (arredi + finiture) | vault storico ~350K era probabilmente solo arredi |
| **Somma (c)+(d) stimata** | **~360–500** | |
| **Buffer residuo vs cap 1.2M** | **116** | 1.200 − 1.084 |

**Verdetto pre-Excel:** probabile **sforamento di 240–380K** rispetto al cap 1.2M. Buffer attuale (116K) copre solo fees consulenziali bucket (c); il bucket (d) arredi/finiture sembra non finanziato. Richiede conferma con numeri reali Excel prima di allertare.

---

## Model refinements (consolidato dei gap emersi)

1. **`societa_pagante_id` obbligatorio su Commitment**, non derivabile da progetto (HPAN25PIANO1 ha sia ORTI che INTUR come paganti).
2. **`ScopePackage.stato`** = `IDENTIFICATO → PREVENTIVATO → IMPEGNATO → CHIUSO`.
3. **ScopePackage senza vendor è legittimo** (solo scope + stima).
4. **`Document.stato_preventivo`** = `RICEVUTO | ACCETTATO | RIFIUTATO | SCADUTO`.
5. **`Commitment.from_document_id`** opzionale → tracciabilità preventivo → contratto.
6. **`Commitment.importo_impegnato_eur` è immutabile dopo firma.** Overrun = varianza, non update.
7. **View `v_commitment_status`** con `importo_fatturato_cum_eur`, `delta_overrun_eur`, `residuo_eur`, `stato_overrun`.
8. **`stato_censimento` su `d_anagrafica_fornitori`** (`DA_CENSIRE / CENSITO / ATTIVO`). Commitment denormalizza snapshot alla creazione.
9. **Granularità ScopePackage = lotto di lavoro coerente**, non categoria generica. Esempi: porte std vs porte REI; piastrelle materiale vs posa.
10. **Budget view cascade**: `COALESCE(impegnato, preventivo_max, stimato)` per ogni ScopePackage.
11. **Regola business capex/opex → società pagante** (candidate I10 vertical): capex struttura → proprietaria immobile; opex operativi → società operativa.

---

## Forward-flow integration a CONDGES

`Commitment.stato ∈ (FIRMATO, IN_CORSO)` + `PaymentSchedule` → righe `f_piano_finanziario_input` fonte=`PROGETTI`, granularità `(societa_pagante × voce_pf × mese)`.

Voce PF target: **decisione aperta**. Proposta iniziale: nuova voce `INVESTIMENTI_CAPEX` in `d_voci_piano_finanziario` (+ nuovo valore `PROGETTI` in `fonte`). Rosa (ORTI CASSA) vede solo Hospitality Project (PM fee); Gasparotto (consolidato) vede tutto il capex progetto.

**Indipendenza dalla Session 1** (Gasparotto Cash-Flow workbook): le due sessioni si toccano solo sulla voce PF target. Se Session 1 ristruttura `d_voci_piano_finanziario`, questo walkthrough resta valido — cambia solo il nome della voce.

---

## Vault drift alert (capture proposal Mode B)

1. **Budget progetto:** vault `CamerePrimoPiano.md` dichiara ~350K (last_seen 2026-03-12), reality 1.2M cap → drift 850K + 5 settimane aging. **Proposta:** update ontology `projects/CamerePrimoPiano.md` con cap aggiornato, link a Excel attuale, lista fornitori aggiornata bucket (a-d).
2. **Fornitori nuovi:** ~15 vendor bucket (c+d) non nel vault. **Proposta:** triage CORE / TACTICAL / TRANSIENT via `ENTITY_REVIEW.md` prima di censire. Consulenti (Archisavio, Pisacane, NESE, Hospitality Project) → likely CORE se continueranno su prossimi progetti; fornitori arredo/finitura (Dorelan, Domus, Flab, VDA, ecc.) → TACTICAL.
3. **Naming drift:** "Amalisa" (brief) vs "Amalia" (vault) Pisacane. Uso Amalia (canonical).
4. **Ambiguità "Capone":** vault = persona (Anna Capone, Studio Ninni). Brief = vendor aziendale TV. Richiede nome canonico disambiguato prima di censire (es. `Capone Elettronica` o ragione sociale reale).
5. **Ambiguità Dierre bucket:** vault = ordine 864 confermato → (b). Brief = (d). Risolvere.
6. **Fornitori vault non menzionati dal brief:** Atelier Hospitality, Studio Ninni, Geberit, Frattini, Rocky, Comoda. Se preventivi/ordini ancora attivi → rientrano in (c) o (d). Da riconciliare.

---

## Aperti / decisioni bloccanti

- [ ] User conferma `stato` e `societa_pagante` di AMCN, STE, SANTELIA, Metal 2000, Dierre (oggi `INTUR?`).
- [ ] User fornisce importi `<excel>` per le 21 righe mancanti (Excel attuale `01_26_25_budget_cost_1_piano_10_cam_COMPLETO.xlsx`).
- [ ] User conferma Dierre bucket (b) vs (d).
- [ ] User disambigua "Capone TV" (nome canonico ragione sociale).
- [ ] User conferma se Atelier Hospitality, Studio Ninni, sanitari (Geberit/Frattini/Rocky/Comoda) sono ancora attivi e in che bucket.
- [ ] User conferma scope di Metal 2000 (carpenteria vs infissi vs altro).
- [ ] **Decisione voce PF target per forward-flow** (nuova `INVESTIMENTI_CAPEX` vs riuso esistente) — coord. con Session 1 Gasparotto se esiste dipendenza.
- [ ] **Decisione I10 candidate**: regola capex/opex → società pagante come invariant platform-wide o business rule del solo vertical `progetti/`?

---

## Next step

Post-risposta user su blocchi sopra:

1. Rewrite `docs/superpowers/specs/2026-04-20-projects-mvp-design.md` sotto il modello validato:
   - 4° vertical `progetti/` (non extension CONDGES).
   - Entities: Project, ScopePackage, Document, Commitment, PaymentSchedule, + link N:M + InvoiceLink.
   - Forward-flow a `f_piano_finanziario_input` fonte=`PROGETTI`.
   - 4 UI views (Register / Documents / Budget evolution / Payment planning).
2. Rewrite `docs/superpowers/plans/2026-04-20-projects-mvp.md` con task TDD aggiornati (entity set nuovo; seed HPAN25PIANO1 da questo walkthrough).
3. Vault captures:
   - `vault/decisions/2026-04-21_Projects_Vertical.md` (4° vertical + forward-flow).
   - update `vault/ontology/projects/CamerePrimoPiano.md`.
   - triage entity nuovi via `ENTITY_REVIEW.md`.
4. Branch `projects-mvp-hpan25piano1`, commit plan + spec, iniziare Task 0.
