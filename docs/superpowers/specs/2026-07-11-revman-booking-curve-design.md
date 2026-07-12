# Revman — `v_booking_curve` + pagina hub Revenue

**Data:** 2026-07-11 · **Fronte:** revman (issue #81, hub vault `workstreams/REVMAN`)
**Worktree:** `.worktrees/revman` (`feat/revman`)

## Contesto e goal

La spina dorsale del revenue management esiste (loop `season_forecast`, commit
`1a6970a`): `f_prenotazioni_otb` accumula fotografie del portafoglio, la
metodologia è validata sul campo (vault `concepts/BOOKING_PACE_E_BASI`):
la curva è una batteria, l'ADR marginale tra foto è il test dell'ultima camera,
l'ADR richiesto sulle notti vendibili è il verdetto prezzo-vs-domanda.

Questo progetto rende la metodologia **un artefatto ripetibile**: una vista BQ
(`v_booking_curve`) che calcola le metriche a ogni nuova foto, e una pagina hub
("Revenue") che le mostra. NON è un motore di pricing: è una lente + un loop
umano settimanale (export → intake → promote → lettura → decisione).

**Primo caso d'uso reale:** ottobre 2026 — prezzo ok a 175€+, mancano ~380
notti di domanda.

**Definition of done:** vista deployata su BQ + pagina hub che mostra
batteria / ADR marginale / ADR richiesto per mese, viva sulle foto esistenti,
e che riproduce i numeri validati a mano l'11/07 (§Verifica).

## Scope

- **BU:** tutte e tre (HOTEL, RESIDENCE, CVM) — deciso da Stefano. Selettore in
  pagina, default HOTEL.
- **Base di misura:** sempre **imponibile** (regola basi omogenee del concept).
- **Fuori scope:** curva 2025 retroattiva same-lead-time (bloccata sull'export
  `DataPrenotazione` — HANDOFF nell'issue #81, acceleratore non prerequisito);
  segmentazione per canale/mercato; qualsiasi write-path.

## Componente 1 — vista `v_booking_curve`

File `core/bq/views/v_booking_curve.sql`, deploy via `hotelops deploy-views`.
**Grana: 1 riga = BU × mese soggiorno × snapshot_date** (~60 righe oggi).

**Struttura CTE obbligatoria** (ogni passaggio verificabile separatamente, in
questo ordine esplicito — la selezione variante e l'aggregazione mensile
PRECEDONO il LAG, mai window su righe alla granularità originaria):

1. `source_ranked` — rank delle varianti per (snapshot_date, BU);
2. `selected_variant` — UNA variante per (snapshot_date, BU);
3. `otb_monthly` — aggregazione a BU × mese_soggiorno × snapshot_date;
4. `otb_with_pickup` — LAG partizionato per BU × mese_soggiorno, ordinato
   per snapshot_date;
5. `ly_monthly` — benchmark 2025 per BU × mese;
6. `capacity_by_year` — capacità osservata per BU × anno;
7. `curve_metrics` — select finale con le metriche.

### Selezione variante (input da `f_prenotazioni_otb`)

Le foto non condividono la variante (14/5 solo NESSUNA; 6/7 ASSEGNATA+VENDUTA;
11/7 solo VENDUTA). Per ogni (snapshot_date, BU) si usa UNA variante con
preferenza **VENDUTA > ASSEGNATA > NESSUNA**; mai sommate (sono la stessa foto
su dimensioni diverse). Assunzione dichiarata: i totali mensili sono
variante-invarianti — verificata sul 6/7 dove esistono entrambe (§Verifica).

### Colonne (4 blocchi)

**1. OTB (la foto):**
- `otb_notti` = SUM(camere), `otb_imponibile` = SUM(imponibile),
  `otb_adr` = imponibile/notti.

**2. Pickup (foto vs foto precedente, stessa BU — window `LAG` su snapshot_date):**
- `gg_tra_foto`; `pickup_notti`, `pickup_imponibile` (Δ);
- `pickup_notti_gg`, `pickup_eur_gg` (Δ normalizzato sui giorni = il rate);
- `adr_marginale` = Δimponibile / Δnotti — **NULL sulla prima foto e quando
  Δnotti ≤ 0** (niente marginali fantasma su cancellazioni nette).

**3. LY e target (fonti PMS 2025 — decisione gate 2, 2026-07-11):**
- `ly_notti` = SUM(camere_vendute) da `f_pms_statistiche`;
- `ly_imponibile` = SUM(importo_imponibile) da **`f_produzione_pms` classe
  01ROOM** (per BU — la base già validata l'11/07: ADR ott 206 = 01ROOM/5.279).
  NON `f_pms_statistiche.revenue_room`: il gate 2 ha mostrato che è una base
  terza (ratio vs 01ROOM: 1,09 maggio, 1,04 giugno — né imponibile né lordo);
- `ly_adr` = ly_imponibile / ly_notti;
- filtro anomalia: righe RESIDENCE 2025 con `camere_totali > 20` escluse dal
  calcolo capacità (alcuni giorni segnano 55);
- `cap_ratio` = capacità 2026 / capacità 2025, **misurata dai dati**:
  MAX(camere_totali) per BU per anno **sui soli giorni operativi**
  (`camere_vendute > 0` — i mesi di chiusura hanno inventario configurato
  diverso, es. HOTEL gen-feb 2025 = 78): 86/76, 20/20, 10/10 — non hardcoded;
- `target_imponibile` = ly_imponibile × cap_ratio (**parità-camera**, il vero
  zero dell'ambizione);
- `notti_attese` = ly_notti × cap_ratio;
- **colonne diagnostiche** (il benchmark LY assume calendario operativo
  comparabile — aperture parziali, inventario fuori servizio, giorni mancanti
  nella fonte PMS lo indeboliscono; non si corregge in v1, si ESPONE):
  `ly_giorni_con_capacita`, `cy_giorni_con_capacita_osservati`,
  `ly_capacita_massima`, `cy_capacita_massima`.

**4. Verdetto (numeri in SQL, semantica in Python):**
- `saturazione_pct` = otb_notti / (capacità_cy × giorni del mese) — **la
  batteria: occupancy OTB vs capacità FISICA** (è il "luglio 80,7% pieno"
  validato l'11/07: 2152/(86×31));
- `avanzamento_volume_pct` = otb_notti / notti_attese — progresso verso il
  volume LY riproporzionato (metrica DIVERSA dalla batteria: luglio 94,4%
  sulla stessa foto — riconciliato in build 2026-07-11);
- `gap_target` = target_imponibile − otb_imponibile;
- `gap_notti_target` = notti_attese − otb_notti — **le notti MANCANTI per
  raggiungere il volume LY riproporzionato**, NON la capacità residua reale
  (quella sarebbe capacità disponibile futura − OTB: oggetto diverso, fuori
  scope v1);
- `adr_richiesto` = gap_target / gap_notti_target (NULL se
  gap_notti_target ≤ 0) — **l'ADR medio necessario sulle notti aggiuntive
  richieste per raggiungere il target**, non l'ADR sulle camere fisicamente
  ancora disponibili.

**Semantica del verdetto** — funzione pura Python (`verdetto(row) -> str`,
testabile senza BQ), con stati preliminari PRIMA delle 3 zone:
1. mese consumato (mese < mese della foto) → `CONSUNTIVO` (nessun verdetto
   operativo);
2. prima foto o pickup_notti ≤ 0 → `DATI_INSUFFICIENTI`;
3. gap_target ≤ 0 → `TARGET_RAGGIUNTO`;
4. gap_notti_target ≤ 0 con gap_target > 0 → `TARGET_INCOERENTE` (gap
   economico positivo senza volume atteso residuo);
5. adr_marginale NULL → `NESSUN_CONFRONTO`;
poi le 3 zone: adr_richiesto < 0,6 × adr_marginale → `TARGET_SCONTATO`;
adr_richiesto > adr_marginale → `SERVE_REPRICING`; altrimenti →
`SERVE_DOMANDA`.

### Caveat dichiarati (commento in testa al SQL)

- Per i **mesi già consumati** l'OTB include il consuntivo (la foto è
  "consumato + futuro"): la curva ha senso pieno sui mesi ≥ mese della foto.
- **Aprile 2026 drogato** dall'apertura anticipata (3/4 vs 16/4): non si
  aggiusta in SQL, si legge col benchmark giusto (concept §3).
- Capacità 2026 per i mesi futuri = valore osservato corrente (86/20/10);
  `notti_attese` usa il riproporzionamento LY, non il calendario, quindi i
  giorni di apertura futuri non servono.

## Componente 2 — pagina hub "Revenue"

`verticals/hub/pages_/revenue.py` + 1 riga registry:
`HubApp("revenue", "Revenue", "📈", "Finanza", "page", revenue.render,
"booking curve & pace", sensitive=False)` (read-only).

Legge SOLO `v_booking_curve`. Layout dall'alto (design dataviz — forma prima,
colore dopo; palette = reference instance della skill dataviz, definita come
ruoli in un punto solo, non hex sparsi):

1. **Stat tile freshness**: data ultima foto + giorni trascorsi; avviso se
   >10 giorni ("manca l'export settimanale").
2. **Tabella batteria** (il cuore) — una riga per mese soggiorno, ultima foto,
   selettore BU (default HOTEL):
   - colonna saturazione = **meter** in cella (ramp blu sequenziale, barra
     step 450 `#2a78d6` su track step 100 `#cde2fb`);
   - colonne numeriche (OTB notti/€, pickup €/gg, ADR medio, ADR marginale,
     ADR richiesto, gap) in inchiostro testo, `tabular-nums`, mai colorate;
   - **verdetto** = status palette riservata con **icona + etichetta, mai
     colore da solo**: ✓ good `#0ca30c` "target scontato" · ⚠ warning
     `#fab219` "serve domanda" · ⛔ serious `#ec835a` "serve repricing"
     (warning/serious sotto 3:1 su superficie chiara by design — icona+label
     è la mitigazione). Il verdetto viene dalla funzione pura Python (§vista):
     TARGET_SCONTATO=good, SERVE_DOMANDA=warning, SERVE_REPRICING=serious;
     gli stati preliminari (CONSUNTIVO, DATI_INSUFFICIENTI, TARGET_RAGGIUNTO,
     TARGET_INCOERENTE, NESSUN_CONFRONTO) in inchiostro neutro con etichetta,
     senza status color. Soglia 0,6 = prima calibrazione (lug 218/476 ≈ 0,46
     = good; ott 175/206 ≈ 0,85 = warning, coerente col verdetto umano
   dell'11/07);
   - mesi consumati in grigio (contesto, non curva).
3. **Curva delle foto** — saturazione % per foto, **emphasis**: mese
   selezionato in slot-1 blu `#2a78d6`, altri mesi linee grigie de-enfatizzate;
   direct label sulla linea enfatizzata, niente legenda-scatola; linee 2px,
   marker ≥8px, tooltip hover; **un solo asse** (%, gli € vivono in tabella).

Validator della palette (`validate_palette.js`) eseguito in implementazione
sulla superficie reale del hub (light, e dark se il tema lo espone).

**Error handling:** 0 foto → "nessuna fotografia OTB"; prima foto → colonne
pickup vuote (NULL dalla vista); BQ irraggiungibile → errore secco, niente
numeri finti (pattern delle altre pagine).

## Verifica (gate, in ordine)

1. **Check variante (una tantum, prima di scrivere la vista):** sul 6/7,
   ASSEGNATA vs VENDUTA confrontate **per BU × mese_soggiorno** (mai solo sul
   totale BU: divergenze compensate tra mesi passerebbero). Criterio
   ripetibile: differenza assoluta notti = **0**; differenza assoluta
   imponibile ≤ **€1** per cella (arrotondamenti fonte). Se fallisce,
   l'assunzione variante-invariante cade → STOP, si riporta a Stefano.
2. **Check base LY (una tantum):** ESEGUITO 2026-07-11, esito STOP →
   risolto per decisione di Stefano: `revenue_room` scartata (ratio vs
   01ROOM instabile: 1,09 mag, 1,04 giu), LY € da `f_produzione_pms`
   01ROOM + notti da `f_pms_statistiche` (vedi §3 colonne).
3. **Test unitario SQL:** fixture con foto sintetiche → golden numbers
   (pickup, marginale con Δnotti ≤ 0, richiesto, cap_ratio).
4. **Verifica finale contro i numeri validati a mano l'11/07 (HOTEL):**
   luglio marginale ~476 vs media ~230, saturazione ~80,7%; agosto ~306 vs
   ~257; ottobre ~206 vs ~213 e adr_richiesto ~175 con gap_notti_target
   ~736 (di cui ~380 non coperte al pace attuale). Se la vista non li
   riproduce, è sbagliata lei.
5. Smoke pagina: `streamlit run verticals/hub/app.py` → pagina Revenue con
   dati reali, 3 BU selezionabili.

## Non-goals

- Nessuna tabella materializzata (`f_booking_curve`): i dati sono minuscoli,
  la vista basta.
- Nessuno stub in `d_camere`: la capacità viene da `f_pms_statistiche`.
- Nessun aggiustamento-aprile in SQL.
- Nessuna previsione/proiezione scritta su BQ (governance 2026-06-19: il pool
  `f_*` è solo fatti).
