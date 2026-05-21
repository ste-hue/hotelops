# Audit consumi F&B per la Direzione — design

**Data**: 2026-05-21 (rev. canonical-transformation-matrix)
**Branch**: `worktree-looker-fb`
**Stato**: design approvato, pronto per implementation plan

## Contesto

Abbiamo 3 fonti dati F&B su BigQuery:

1. **Ricavi F&B** — `f_ricavi_fb` da Power BI Produzione Netta HotelCube
2. **Consumi magazzino** — `f_consumi_economato` da Excel Economato (mensile per reparto×prodotto)
3. **Coperti** — `f_coperti_giornalieri` da Hoxell / Google Sheet RistoCube (giornaliero per BU×tipo_pasto)

## Mental model: canonical transformation matrix

Il modello F&B non è "report", è una **matrice canonica di trasformazione** in 6 layer:

```
RICAVI       (domanda — cosa è stato venduto, da dove)
   ↓
CONSUMI      (assorbimento materie — quanto magazzino è uscito)
   ↓
COPERTI      (volume operativo reale — quante persone servite)
   ↓
KPI          (efficienza normalizzata — €/coperto, %, quantità/coperto)
   ↓
RANGE        (aspettativa industria — qual è la fascia normale?)
   ↓
ALERT        (deviazione — cosa è fuori range e va indagato)
```

Per ogni vertical (BREAKFAST / RISTORANTE / BAR) i 6 layer sono diversi: fonti, reparti consumo, coperti applicabili, KPI sensati, range industria.

L'obiettivo dell'audit è che la direzione **confermi i componenti dei layer 1-3** (quali codici, quali reparti, quali coperti) per il primo modello operativo. I layer 4-6 li costruiamo noi col modello standard.

## Obiettivi

1. **Mostrare** i 3 vertical alla direzione con: codici/reparti/coperti proposti, numeri 2025, KPI calcolati, range industria, alert dove fuori
2. **Raccogliere** conferma o correzione dei codici per bucket via Google Form (no teorie, solo conferma layer 1-3)
3. **Iterare** il modello dopo le risposte

## Non-obiettivi

- Non chiediamo allo chef matrice categoria_prodotto → ricetta
- Non chiediamo teorie sulle cause di anomalie (le indaghiamo noi nei round successivi)
- Non modifichiamo dati su BQ — audit pure read-only

## I 3 vertical

### Vertical 1 — BREAKFAST

| Layer | Componenti |
|---|---|
| **Ricavi** | `SCBKFBB` (HOTEL B&B scorporo) + `SCBKFHB` (CVM HB scorporo) + `BRKADULT` + `BRKBABY` + `BRKEXT` + `BRKEXTC` su **HOTEL + RESIDENCE + ANGELINA + CVM** (multi-BU) |
| **Consumi** | reparto `BRK` |
| **Coperti** | `f_coperti_giornalieri.tipo_pasto = 'BRK'` (tutte BU) |
| **KPI A** | Costo materie prime / coperto = `cost BRK / coperti BRK` |
| **KPI B** | Ricavo / coperto = `(SCBKFBB + BRK*) / coperti BRK` |
| **KPI C** | Food cost % = `cost BRK / ricavi breakfast` |
| **Range industria** | Buffet hotel 4*: cost €4-6/pax, ricavo €8-12/pax, FC 30-50% sensato. <30% sospetto basso, >60% investigate |
| **Esempio aprile 2026** | cost €4/pax, ricavo €10/pax → FC 40% — sensato |

### Vertical 2 — RISTORANTE (lunch + dinner)

| Layer | Componenti |
|---|---|
| **Ricavi food** | `RISLFOOD` + `RISDFOOD` + `RISTLUNC` + `RISTDINN` + `DINFOOD` + `LUNBAR` + **bar food** (`RISBFOOD`) + **banchetti food** (`BAN`) + eventi food (`FERRAD`, `FERRBA`, `PASQAD`, `PARTY`, `BRUNCH`, `APERIDIN`) — _da confermare se eventi qui o bucket separato_ |
| **Consumi** | reparto `CUCINA` |
| **Coperti** | `f_coperti_giornalieri.tipo_pasto IN ('LUNCH','DINNER')` + coperti eventi/banchetti se tracciati |
| **KPI A** | Food cost % = `cost CUCINA / ricavi food ristorante` |
| **KPI B** | Costo / coperto = `cost CUCINA / (coperti lunch + dinner)` |
| **KPI C** | Quantità materia prima / coperto (avanzato): es. kg carne/pax, kg pesce/pax, kg verdura/pax, kg pane/pax — _round successivo, richiede category mapping_ |
| **Range industria** | **Pizzeria**: ~15% · **Ristorante medio**: 25-35% · **Michelin 3\***: 38% · **Target Panorama**: 25-35% · **Warning**: >40% · **Investigate**: >50% |
| **Cause possibili food cost >50-60%** | pricing sbagliato, porzioni eccessive, furto, sprechi, mix prodotti, menu engineering, eventi sottocosto, ricavi incompleti, consumi caricati male |

### Vertical 3 — BAR / BEVERAGE

| Layer | Componenti |
|---|---|
| **Ricavi beverage** | `BAR` (bar generico) + `BARHOTEL` (bar hotel) + `RISLBEVE` + `RISLBEV` + `RISDBEV` + `DINBEV` + `BANB` (banchetti beverage) + `PROSECCO` |
| **Consumi** | reparto `CANTINA` |
| **Coperti** | non c'è "coperti bar" diretto. Usabili: coperti lunch+dinner (per drink al pasto) o totale stagione (per bar standalone) |
| **KPI A** | Beverage cost % = `cost CANTINA / ricavi beverage` |
| **KPI B** | Quantità / coperto: bottiglie acqua/pax, bicchieri vino/pax, spritz/pax, ecc. — _round successivo, richiede category mapping_ |
| **Range industria** | Beverage cost classico: 10-30% · Top-tier ristorante: ~30% · Hotel bar mix: tipicamente 15-25% |
| **Avvertenze** | Il beverage è il più falsato: complimentary, staff drinks, eventi, minibar, stock movement, inventario inaccurato. Trattare i numeri con cautela |

## Architettura: due artefatti sincronizzati

| Artefatto | Cosa fa | Quando |
|---|---|---|
| **A. Streamlit `audit_consumi_dashboard.py`** | Read-only viewer: primer + 3 pagine vertical (B1/B2/B3) + 1 pagina anomalie FYI + recap | _Prima_ — direttore vede dati, KPI, range, alert |
| **B. Google Form (via Apps Script)** | Sezioni di conferma codici/reparti/coperti per vertical (no teorie aperte) | _Dopo_ — direttore conferma layer 1-3 |

## Artefatto A — Streamlit

### Path

`verticals/condges/audit_consumi_dashboard.py`

### Pagine

| # | Pagina | Contenuto |
|---|---|---|
| 1 | 🏠 **Primer** | Le 3 fonti dati BQ + mental model 6-layer + cosa sono i 3 vertical |
| 2 | 🥐 **B1 — Breakfast** | Layer 1-3 (codici/reparto/coperti) come tabelle + KPI A/B/C + range industria + alert se fuori range |
| 3 | 🍽️ **B2 — Ristorante** | Stesso pattern + range pizzeria/medio/michelin + cause possibili anomalie |
| 4 | 🍷 **B3 — Bar / Beverage** | Stesso pattern + range beverage + avvertenze su falsità del beverage |
| 5 | ⚠️ **Anomalie FYI** | Tabella sintetica: storni UoM maggio, BANCHETTI sotto-stimato, BAR_HOTEL vuoto, codici da sospendere, codici orfani, reparti non-F&B, carico magazzino stagionale |
| 6 | 📋 **Recap + Form** | Link Google Form |

### Template per ogni pagina vertical

```
┌─────────────────────────────────────────────────────────────┐
│ # Vertical N — {Nome}                                        │
│ Mental model: 6 layer compatti (testo)                       │
│                                                             │
│ ## Layer 1: Ricavi                                          │
│   - Tabella codici inclusi + netto 2025 + somma             │
│   - Caveat: cross-BU? Cross-codice?                         │
│                                                             │
│ ## Layer 2: Consumi                                         │
│   - Reparto economato + cost 2025 + n_prodotti              │
│                                                             │
│ ## Layer 3: Coperti                                         │
│   - tipo_pasto + count 2025                                 │
│                                                             │
│ ## Layer 4: KPI normalizzati                                │
│   - Scorecard KPI A (€/coperto), KPI B (ricavo/cop),        │
│     KPI C (food cost %)                                     │
│                                                             │
│ ## Layer 5: Range industria                                 │
│   - Tabella range con bande target/warning/investigate      │
│                                                             │
│ ## Layer 6: Alert                                           │
│   - Verde se nel target, giallo se warning, rosso se        │
│     investigate. Numerico per mese + cumulativo.            │
│                                                             │
│ ## Andamento mensile                                        │
│   - Bar chart cost vs revenue per mese 2025                 │
│                                                             │
│ ## Per la tua valutazione                                   │
│   - 🔗 Vai al Google Form — sezione B{N}                     │
└─────────────────────────────────────────────────────────────┘
```

### Codici proposti per vertical (da confermare)

**B1 — Breakfast** (multi-BU):
- `SCBKFBB` (HOTEL B&B scorporo)
- `SCBKFHB` (CVM HB scorporo)
- `BRKADULT`, `BRKBABY`, `BRKEXT`, `BRKEXTC` su HOTEL + RESIDENCE + ANGELINA + CVM

**B2 — Ristorante**:
- `RISLFOOD`, `RISDFOOD`, `RISTLUNC`, `RISTDINN`, `DINFOOD`, `LUNBAR`
- `RISBFOOD` (bar food)
- `BAN` (banchetti food)
- Eventi food: `FERRAD`, `FERRBA`, `PASQAD`, `PARTY`, `BRUNCH`, `APERIDIN` (da confermare)
- `ROOMSERV`

**B3 — Bar / Beverage**:
- `BAR`, `BARHOTEL`
- `RISLBEVE`, `RISLBEV`, `RISDBEV`, `DINBEV`
- `BANB` (banchetti beverage)
- `PROSECCO`

### Pagina anomalie FYI

Tabella sintetica:

| Anomalia | Cosa | Implicazione | Conferma? |
|---|---|---|---|
| Storni UoM maggio 2025 | 15 righe -€166k | Escluse dai KPI (flag) | ✓ confermi? |
| BANCHETTI reparto €1.2k vs revenue €17k | Mismatch ~7% FC | Cibo banchetti in CUCINA — non spezziamo | ✓ confermi? |
| BAR_HOTEL reparto €0 vs revenue BAR €76k | Drink bar usa CANTINA | Unifichiamo | ✓ confermi? |
| Codici da sospendere (17) | da `pianodeicontilavoro.xlsx` | Filtriamo da default Looker | ✓ confermi? |
| Codici orfani (~1: ACCFCI) | Non in classe nota | Aggiungi a 07DIV o specifica | ✓ confermi? |
| Reparti operativi non-F&B (~€100k) | DIPEND, HSK*, MAN*, DIREZIONE, D*, DEPERIMENTO | Pagina dashboard separata | ✓ confermi? |
| Carico magazzino concentrato | Picco BRK luglio €76k | Lettura trimestrale > mensile | ✓ confermi? |

## Artefatto B — Google Form

### Sezioni

**S0 — Identità**: nome+ruolo, data

**S1 — Conferma codici B1 Breakfast**:
- Checkbox codici proposti
- Multiple choice: "Le 4 BU (HOTEL+RES+ANG+CVM) devono essere TUTTE aggregate per breakfast totale? O bucket per BU?"
- Text area: codici da aggiungere/escludere

**S2 — Conferma codici B2 Ristorante**:
- Checkbox codici food
- Multiple choice: "Gli eventi (FERRAD/FERRBA/PASQAD/PARTY/BRUNCH/APERIDIN) in (a) B2 ristorante (b) bucket eventi separato (c) escluderli?"
- Multiple choice: "RISBFOOD (Risto bar food) in B2 food o B3 drink?"
- Text area: aggiunte/note

**S3 — Conferma codici B3 Bar/Beverage**:
- Checkbox codici drink
- Multiple choice: "`BARHOTEL` e `BAR` sono lo stesso (fondi) o diversi?"
- Text area: aggiunte/note

**S4 — Coperti mapping**:
- Multiple choice: "Coperti BRK includono solo clienti hotel B&B o anche esterni paganti?"
- Multiple choice: "Coperti lunch e dinner sono separati nettamente o sovrapposti (es. brunch)?"
- Text area: dove guardare per coperti accurati (Hoxell? Excel? altro?)

**S5 — Range operativi**:
- Multiple choice: "Target food cost ristorante Panorama"
  - Pizzeria-level (~15%)
  - Ristorante medio (25-35%)
  - Top-tier (~38%)
- Multiple choice: "Target beverage cost"
  - 10-15% (basic)
  - 15-25% (medio)
  - 25-30% (top-tier)
- Text area: target tuoi personali

**S6 — Anomalie FYI**: 7 conferme rapide ✓/✗ + text area opzionale per ognuna

**S7 — Catch-all**: cosa manca?

## Workflow post-risposte

1. Stefano esporta risposte da Google Sheet
2. Per ogni vertical: aggiorna lista codici nel modello SQL (`v_fb_kpi` v3 con i layer corretti)
3. Aggiorna range industria nelle scorecard Looker secondo la direzione
4. Anomalie confermate: applica fix come deciso
5. Round successivo (se serve):
   - Chef per categoria_prodotto → ricetta (KPI B quantità/coperto)
   - POS Ristocube per separare drink bar/ristorante/banchetti

## Acceptance criteria

- Streamlit 6 pagine navigabili senza errori
- B1/B2/B3 mostrano:
  - Layer 1-3 (codici/reparto/coperti) come tabelle
  - Layer 4 (KPI A/B/C) come scorecard
  - Layer 5 (range industria) come tabella
  - Layer 6 (alert) come colori semaforo
- Esempio breakfast aprile 2026 deve mostrare ~€4 cost/pax + ~€10 ricavo/pax + FC ~40%
- Apps Script crea Form con 8 sezioni (S0-S7) senza errori
- Una compilazione test salva risposte nel Sheet

## Out of scope (round successivo)

- KPI B quantità/coperto (richiede mapping categoria_prodotto → bucket)
- POS Ristocube per decomporre drink bar/ristorante/banchetti
- Matrice ricetta categoria→articolo (chef)
- Streamlit Cloud hosting
- API HotelCube per modifiche piano dei conti
