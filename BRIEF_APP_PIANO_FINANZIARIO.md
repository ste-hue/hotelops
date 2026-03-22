# Brief: App Interattiva Piano Finanziario

**Per**: Claude Code (con accesso BigQuery)
**Da**: Stefano (CFO) + Claude (Cowork)
**Data**: 2026-03-21
**Obiettivo**: Sostituire il workflow Excel manuale di Rosa con un'app interattiva che legge/scrive BigQuery

---

## 1. Contesto Business

Rosa (tesoreria) gestisce il Piano Finanziario (PF) di due società — **ORTI** (operazioni hotel) e **INTUR** (holding finanziaria) — tramite Excel. Ogni mese:

1. Parte dal **saldo banca reale** (ultimo giorno del mese precedente)
2. Inserisce le **entrate previste** per voce (hotel, residence, CVM, spiaggia, affitti...)
3. Inserisce le **uscite previste** per voce, con dettaglio per fornitore (materie prime, utenze, consulenze...)
4. Calcola il **cash flow netto** e il **saldo proiettato** mese per mese
5. Per le uscite: controlla lo **scadenzario** (fatture aperte in Esolver) e le sposta in avanti se non pagate

Il problema: i file Excel si perdono, non c'è versioning, le formule si rompono, e ogni mese ricomincia da zero. L'app deve **replicare esattamente questo workflow** ma su BigQuery.

---

## 2. Struttura Excel di Rosa (da replicare)

Rosa usa un file Excel con 14 fogli per società. Ecco la struttura del file `ORTI - Piano Finanziario - 03_mar2026.xlsx`:

### 2.1 Foglio Principale: "Piano Finanziario"

Layout a griglia: **righe = voci**, **colonne = mesi** (rolling window, tipicamente set2025 → set2026).

```
Riga  Contenuto
─────────────────────────────────────────────────
R1    Intestazione anni (C3=2025, C7=2026)
R2    Società (A="ORTI") + nomi mesi (C=SETTEMBRE...O=SETTEMBRE)
R3    Sottointestazione mesi (mese di competenza per i totali annuali)
R4    SALDO MESE PRECEDENTE — il valore ancora: cascata dal mese precedente
      R4.C5 = saldo_proiettato del mese prima (134.646,79 = MPS 67.724 + Intesa 66.922)
R6    Entrate Hotel
R7    Entrate Residence
R8    Entrate CVM
R9    Entrate Supermercato
R10   Rientro Sospesi
R11   Caparre Intur
R12   TOTALE ENTRATE = SUM(R6:R11)
R14   ===== (separatore)
R15   Salari e Stipendi
R16   Utenze
R17   Materie Prime/Consumo
R18   Tasse e Imposte
R19   Commissioni Portali
R20   Mutui e Finanziamenti
R21   Consulenze
R22   Godimento Beni di Terzi
R23   Varie ed Eventuali
R24   Canoni e servizi
R25   Deposito Fitto
R28   TOTALE USCITE = SUM(R15:R25)
R30   Cash Flow = TOTALE ENTRATE - TOTALE USCITE
R33   Saldo MPS (valore reale da estratto conto)
R34   Saldo Intesa (valore reale da estratto conto)
R36   TOTALE BANCHE = MPS + Intesa
R38   CASSA CONTANTI
R40   Saldo di Periodo/Proiettato = SALDO PRECEDENTE + Cash Flow
      (questo valore diventa SALDO MESE PRECED. del mese successivo → cascata)
R42   Fin. MPS 60 mesi (finanziamento attivo, informativo)
```

**Logica cascata critica**: `R40[mese N]` → `R4[mese N+1]`. Se cambi aprile, maggio-dicembre si ricalcolano tutti.

### 2.2 Fogli Dettaglio Uscite (10 fogli)

Ogni voce di uscita ha un foglio dedicato con dettaglio per fornitore/sotto-voce:

| Foglio | Voce PF | Contenuto |
|--------|---------|-----------|
| Salari e Stipendi | USCITE_SALARI | Salari, Contributi, TFR, INPS/INAIL |
| Utenze | USCITE_UTENZE | Energia elettrica, Gas, Acqua, Telefonia, Internet |
| Materie Prime-Consumo | USCITE_MATERIE_PRIME | ~60 fornitori (Le Croissant, Bianco Bufala, Amazon...) |
| Tasse e Imposte | USCITE_TASSE | IMU, Imposte, IVA, F24, TARI, ecc. |
| Commissioni Portali | USCITE_COMMISSIONI | Booking, Expedia, Nexi POS |
| Mutui e Finanziamenti | USCITE_MUTUI | Mutuo MPS, Ex Mutuo Intesa, Fin. MPS 60 mesi |
| Consulenze | USCITE_CONSULENZE | Consulenza lavoro, fiscale, legale, TeamWork... |
| Godimento Beni di Terzi | USCITE_GODIMENTO_BENI | Fitto Ramo d'Azienda (ORTI→INTUR), noleggi, leasing |
| Canoni e servizi | USCITE_CANONI | Proxima, Hoxell, software vari |
| Varie ed Eventuali | USCITE_VARIE | Spese condominiali, varie |

**Struttura tipo foglio dettaglio** (es. "Materie Prime-Consumo"):
```
R1   Anni (C4=2025, C8=2026)
R2   Nomi mesi
R3/4 Totale voce (SUM di tutte le righe sottostanti) — collegato al foglio principale
R5+  Righe individuali: un fornitore per riga, importi per mese
     Colonna A = metodo pagamento (RID, Bonifico...)
     Colonna B = nome fornitore
     Colonne C+ = importi mensili
```

Il totale del foglio dettaglio alimenta la riga corrispondente nel foglio principale.

### 2.3 Foglio "Saldi Banca"

Storico saldi banca reali con data, banca, saldo, fonte.

### 2.4 Foglio "Consuntivo vs Previsione"

Confronto mese per mese: Previsione | Consuntivo | Delta — per ogni voce.

---

## 3. BigQuery — Tabelle e Viste Rilevanti

### 3.1 GCP Setup

- **Progetto**: `hotelops-suite`
- **Dataset**: `hotelops`
- **Auth**: `gcloud` authenticated, usa `google.cloud.bigquery.Client(project="hotelops-suite")`

### 3.2 Tabelle Fatto (lettura)

#### `f_saldi_banca_snapshot` — Ancora bancaria
```sql
-- Schema: 4 colonne
societa_id    STRING   -- ORTI | INTUR
banca_id      STRING   -- MPS | MPS_KROSS | SELLA | INTESA
data_snapshot DATE     -- Data del saldo (tipicamente fine mese)
saldo_finale  FLOAT    -- Saldo in €

-- Query: ultimo saldo per banca per società
SELECT societa_id, banca_id, saldo_finale, data_snapshot
FROM (
  SELECT *, ROW_NUMBER() OVER (
    PARTITION BY societa_id, banca_id ORDER BY data_snapshot DESC
  ) AS rn
  FROM `hotelops-suite.hotelops.f_saldi_banca_snapshot`
)
WHERE rn = 1
```

**Banche attive**: ORTI → MPS, MPS_KROSS · INTUR → MPS, SELLA, INTESA

#### `f_partite_aperte_fornitori` — Scadenzario (3a dimensione: IMPEGNO)
```sql
-- Schema: 14 colonne
societa_id         STRING   -- ORTI | INTUR
data_snapshot      DATE     -- Data dello snapshot (quando Rosa esporta da Esolver)
codice_fornitore   INTEGER  -- Codice fornitore Esolver
nome_fornitore     STRING   -- Ragione sociale
tipo_documento     STRING   -- FT (fattura), NC (nota credito), AFT
numero_documento   STRING   -- Numero documento
data_documento     DATE     -- Data emissione
data_scadenza      DATE     -- Data scadenza pagamento  ← CHIAVE PER ROLL-FORWARD
importo_residuo    FLOAT    -- Importo residuo (negativo = debito nostro)
importo_abs        FLOAT    -- Valore assoluto
codice_pagamento   STRING   -- 01=Rimessa, 02=RIBA, 03=SDD, 04=Bonifico, 10=Carta
metodo_pagamento   STRING   -- Descrizione pagamento
is_intercompany    BOOLEAN  -- True per PANORAMA COMPANY, INTUR, ORTI S.R.L.
file_sorgente      STRING   -- File Excel di origine

-- Query: snapshot più recente, raggruppato per mese di scadenza
SELECT
  p.societa_id,
  EXTRACT(YEAR FROM p.data_scadenza) AS anno,
  EXTRACT(MONTH FROM p.data_scadenza) AS mese,
  p.nome_fornitore,
  ROUND(SUM(p.importo_abs), 0) AS importo,
  p.is_intercompany
FROM `hotelops-suite.hotelops.f_partite_aperte_fornitori` p
JOIN (
  SELECT societa_id, MAX(data_snapshot) AS data_snapshot
  FROM `hotelops-suite.hotelops.f_partite_aperte_fornitori`
  GROUP BY societa_id
) ls USING (societa_id)
WHERE p.data_snapshot = ls.data_snapshot
GROUP BY 1, 2, 3, 4, 6
```

#### `f_piano_finanziario_input` — Previsioni manuali (lettura + scrittura)
```sql
-- Schema: 9 colonne
hash_riga        STRING     -- MD5 dedup key
societa_id       STRING     -- ORTI | INTUR
voce_id          STRING     -- FK → d_voci_piano_finanziario.voce_id
anno             INTEGER
mese             INTEGER    -- 1-12
importo          FLOAT      -- Importo in €
fonte            STRING     -- PIANO_FINANZIARIO | CLI | NANOCLAW | SCADENZIARIO | BVA_2026
note             STRING
file_sorgente    STRING
data_caricamento TIMESTAMP

-- Fonti attive:
-- PIANO_FINANZIARIO: dal parsing degli Excel PF di Rosa
-- SCADENZIARIO: rate mutui
-- BVA_2026: ricavi budget
-- CLI: aggiornamenti manuali da `hotelops previsione`
```

#### `f_movimenti_contabili` — Consuntivo contabile
```sql
-- Colonne chiave:
societa_id          STRING   -- ORTI | INTUR
cod_conto           STRING   -- Codice conto SENZA PUNTI (es. "570913")
anno                INTEGER
mese                INTEGER
imp_dare            FLOAT
imp_avere           FLOAT
data_registrazione  DATE
```

#### `f_banche_movimenti` — Consuntivo bancario
```sql
-- Colonne chiave:
societa_id       STRING
banca_id         STRING
data_operazione  DATE
tipo_movimento   STRING   -- Per LIKE match con d_voci (es. "PAGAMENTO RATA")
importo_netto    FLOAT    -- Positivo = entrata, negativo = uscita
descrizione      STRING
```

### 3.3 Tabelle Dimensione

#### `d_voci_piano_finanziario` — Il dizionario centrale (29 righe)
```
voce_id              | voce_label                                    | sezione  | ord
─────────────────────┼───────────────────────────────────────────────┼──────────┼────
ENTRATE_HOTEL        | Entrate Hotel                                 | ENTRATE  | 60
ENTRATE_RESIDENCE    | Entrate Residence                             | ENTRATE  | 70
ENTRATE_CVM          | Entrate CVM                                   | ENTRATE  | 80
ENTRATE_SUPERMERCATO | Entrate Supermercato                          | ENTRATE  | 90
ENTRATE_SPIAGGIA_ORTI| Spiaggia Alloggiati (Hotel+Res+CVM)          | ENTRATE  | 25
ENTRATE_SPIAGGIA     | Entrate Spiaggia (clienti esterni)            | ENTRATE  | 20
ENTRATE_AFFITTI_INTUR| Canone Affitto Ramo Azienda (ORTI→INTUR)     | ENTRATE  | 10
ENTRATE_AFFITTI_MINORI| Affitti Minori (Farmacia e altri)            | ENTRATE  | 30
ENTRATE_CAPARRE      | Caparre da Intur                              | ENTRATE  | 110
ENTRATE_CAPARRE_INTUR| Caparre (da girare)                           | ENTRATE  | 40
ENTRATE_RIENTRO_SOSPESI| Rientro Sospesi                            | ENTRATE  | 100
USCITE_SALARI        | Salari e Stipendi                             | USCITE   | 200
USCITE_UTENZE        | Utenze (Energia+Acqua+Gas+Tel+Internet)       | USCITE   | 210
USCITE_MATERIE_PRIME | Materie Prime / Consumo                       | USCITE   | 250
USCITE_TASSE         | Tasse e Imposte                               | USCITE   | 260
USCITE_MUTUI         | Mutui e Finanziamenti (rate mensili)           | USCITE   | 270
USCITE_MUTUI_SEMESTRALE| Rimborso Finanziamenti (semestrale)         | USCITE   | 275
USCITE_SPESE_BANCARIE| Commissioni e Spese Bancarie                  | USCITE   | 278
USCITE_CONSULENZE    | Consulenze e Marketing                        | USCITE   | 280
USCITE_GODIMENTO_BENI| Godimento Beni di Terzi (Fitti Passivi)       | USCITE   | 290
USCITE_COMMISSIONI   | Commissioni OTA e Portali                     | USCITE   | 300
USCITE_CANONI        | Canoni e Servizi                              | USCITE   | 310
USCITE_CANONE_PASSIVO| Canone Affitto Ramo Azienda (INTUR→ORTI)     | USCITE   | 315
USCITE_DEPOSITO_FITTO| Deposito Fitto (una tantum)                   | USCITE   | 325
USCITE_MARKETING     | Marketing e Pubblicità                        | USCITE   | 316
USCITE_SERVIZI_PRODUZIONE| Servizi per la Produzione                 | USCITE   | 317
USCITE_VARIE         | Varie ed Eventuali                            | USCITE   | 320
USCITE_VARIE_EXT     | Varie ed Eventuali                            | USCITE   | 321
```

Colonne aggiuntive: `societa_id` (NULL=entrambe), `fonte` (ESOLVER|BANCHE|MANUALE), `cod_conto_pattern`, `cod_conto_pat2`, `cod_conto_pat3`, `banca_tipo_pat`, `bu_filter`.

#### `d_fornitori` — Mapping fornitore → voce PF (65 righe)
```sql
-- Schema:
codice_fornitore  INTEGER  -- PK, codice Esolver
nome_esolver      STRING   -- Ragione sociale Esolver
nome_pf           STRING   -- Nome abbreviato per il PF
voce_id           STRING   -- FK → d_voci_piano_finanziario.voce_id
is_intercompany   BOOLEAN  -- True per PANORAMA COMPANY (cod 264)

-- Questo è il PONTE tra scadenzario (f_partite_aperte_fornitori.codice_fornitore)
-- e la voce PF di appartenenza. Permette di raggruppare le fatture aperte
-- per categoria di spesa.
```

### 3.4 Viste Analitiche

#### `v_piano_finanziario_consuntivo` — Actuals per voce PF
```sql
-- Aggrega f_movimenti_contabili + f_banche_movimenti → importo per voce/mese
-- Join via LIKE patterns su d_voci_piano_finanziario
-- Output: societa_id, voce_id, voce_label, sezione, anno, mese, importo
-- Sign: ENTRATE positivo = entrata, USCITE positivo = uscita
```

#### `v_piano_finanziario_mensile` — Budget vs Consuntivo (rolling 18 mesi)
```sql
-- Scaffold: d_voci × mesi[-6m,+12m] × {ORTI,INTUR}
-- LEFT JOIN consuntivo, budget_costi (via LIKE), input_manuale (via voce_id)
-- Output: societa_id, voce_id, voce_label, sezione, ord, anno, mese,
--         tipo_periodo, importo_consuntivo, importo_budget, scostamento, scostamento_pct
-- tipo_periodo: CONSUNTIVO (mese passato) | BUDGET (mese corrente/futuro)
-- importo_budget = COALESCE(budget_costi,0) + COALESCE(input_manuale,0)
```

#### `v_previsione_cassa` — Cash forward rolling 12 mesi
```sql
-- 1. ANCORA: ultimo saldo reale per banca (f_saldi_banca_snapshot), sommato per società
-- 2. MESI: 12 mesi in avanti dall'ancora
-- 3. FLUSSI: CONSUNTIVO → v_piano_finanziario_consuntivo, CORRENTE/BUDGET → f_piano_finanziario_input
-- 4. SALDO PROIETTATO: saldo_ancora + SUM(netto) cumulativo
-- 5. SCADENZARIO: uscite certe da f_partite_aperte_fornitori (informativa, NON entra nel saldo)
-- Output: societa_id, anno, mese, periodo, tipo_periodo, saldo_ancora, entrate,
--         uscite_pf, uscite_scad (informativa), netto_pf, saldo_proiettato, stato_liquidita
```

### 3.5 Convenzioni Segno

| Contesto | ENTRATE | USCITE |
|----------|---------|--------|
| Esolver (f_movimenti_contabili) | imp_avere - imp_dare (positivo=entrata) | imp_dare - imp_avere (positivo=uscita) |
| Banche (f_banche_movimenti) | importo_netto (positivo=entrata) | -importo_netto (positivo=uscita) |
| Viste PF | Positivo = entrata | Positivo = uscita |
| f_partite_aperte_fornitori | N/A | importo_abs sempre positivo |

### 3.6 Formato Codici Conto

| Tabella | Formato | Esempio |
|---------|---------|---------|
| f_movimenti_contabili.cod_conto | Senza punti | `570913` |
| f_budget_mensile.codice_conto | Con punti | `57.09.13` |
| d_voci.cod_conto_pattern | Senza punti (prefisso) | `5709` |

Per join budget: `REPLACE(codice_conto, '.', '') LIKE CONCAT(pattern, '%')`

---

## 4. Logica di Business Critica

### 4.1 Roll-Forward Scadenzario (la logica più importante)

Quando una fattura ha `data_scadenza` nel passato ma è ancora nello snapshot (= non pagata), Rosa la **sposta al mese corrente o successivo**. Questa è la regola:

```
SE data_scadenza < primo giorno mese corrente E fattura ancora aperta:
    → SPOSTA al mese corrente (o al prossimo mese utile)
    → AGGIUNGI l'importo alle stime PF esistenti per quel mese (NON sostituire)
```

**Implementazione SQL suggerita**:
```sql
-- Mese effettivo = il più grande tra scadenza reale e mese corrente
GREATEST(
  DATE_TRUNC(data_scadenza, MONTH),
  DATE_TRUNC(CURRENT_DATE('Europe/Rome'), MONTH)
) AS mese_effettivo
```

**IMPORTANTE**: Le fatture rolled-forward si SOMMANO alle stime PF, non le sostituiscono. Se Rosa ha stimato €80K di materie prime per aprile, e ci sono €15K di fatture scadute di marzo non pagate, aprile diventa €95K.

### 4.2 Cascata Saldo Proiettato

Il saldo proiettato è una catena cumulativa:

```
saldo[mese 0] = saldo_banca_reale (da f_saldi_banca_snapshot)
saldo[mese N] = saldo[mese N-1] + entrate[mese N] - uscite[mese N]
```

Se l'utente modifica una previsione di aprile, TUTTI i mesi successivi si ricalcolano.

### 4.3 Dettaglio Uscite per Fornitore

Per ogni voce di uscita, Rosa vuole vedere il dettaglio fornitori. Il ponte è:

```
f_partite_aperte_fornitori.codice_fornitore
  → d_fornitori.codice_fornitore → d_fornitori.voce_id
  → d_voci_piano_finanziario.voce_id
```

Esempio per USCITE_MATERIE_PRIME (aprile):
- Stima PF: €80.000
- Scadenzario dettaglio:
  - Le Croissant SRL: €3.200 (scad. 15/04)
  - Bianco Bufala: €1.800 (scad. 20/04)
  - Giacinto Di Palma: €950 (scad. 30/03 → rolled forward ad aprile)
  - ... altri fornitori
- Totale scadenzario: €12.500 (su €80K stimati — il resto sono stime senza dettaglio fattura)

### 4.4 Intercompany

PANORAMA COMPANY (cod. 264) è intercompany. Il canone ORTI→INTUR (€732K/anno, 6 rate da €122K) appare come:
- ORTI: USCITE_CANONE_PASSIVO (voce_id=USCITE_CANONE_PASSIVO)
- INTUR: ENTRATE_AFFITTI_INTUR (voce_id=ENTRATE_AFFITTI_INTUR)

Nel consolidato si cancella. Flag `is_intercompany=True` in f_partite_aperte_fornitori.

---

## 5. Specifiche App

### 5.1 Tecnologia Consigliata

**Streamlit** — già in pyproject.toml come dipendenza opzionale (`pip install -e ".[dashboard]"`).
Dipendenze disponibili: `streamlit>=1.35`, `plotly>=5.0`, `db-dtypes>=1.0`.

L'app va in `dashboard/app_piano_finanziario.py` (o simile).

### 5.2 Vista Principale: Griglia PF

Replica il foglio principale di Rosa:

```
┌─────────────────────────────────────────────────────────────────────┐
│  [ORTI ▼]  Piano Finanziario 2026          [💾 Salva] [📥 Excel]  │
├─────────────────────────────────────────────────────────────────────┤
│  SALDO INIZIALE (28/02/2026)                                       │
│  MPS: €67.725  |  Intesa: €66.922  |  TOTALE: €134.647            │
├──────────────────┬────────┬────────┬────────┬────────┬─────────────┤
│  Voce            │  Mar   │  Apr   │  Mag   │  Giu   │  ...        │
├──────────────────┼────────┼────────┼────────┼────────┼─────────────┤
│  ══ ENTRATE ══   │        │        │        │        │             │
│  Entrate Hotel   │  ████  │ [edit] │ [edit] │ [edit] │             │
│  Entrate Resid.  │  ████  │ [edit] │ [edit] │ [edit] │             │
│  ...             │        │        │        │        │             │
│  TOT ENTRATE     │ 25.620 │180.000 │320.000 │450.000 │             │
├──────────────────┼────────┼────────┼────────┼────────┼─────────────┤
│  ══ USCITE ══    │        │        │        │        │             │
│  Salari       ▶  │ 18.142 │ 27.780 │ 77.000 │102.000 │             │
│  Utenze       ▶  │ 14.671 │ 17.500 │  8.000 │ 20.500 │             │
│  Mat. Prime   ▶  │ 12.338 │ [edit] │ [edit] │ [edit] │             │
│  ...             │        │        │        │        │             │
│  TOT USCITE      │169.969 │        │        │        │             │
├──────────────────┼────────┼────────┼────────┼────────┼─────────────┤
│  CASH FLOW       │-144.349│        │        │        │             │
│  SALDO PROIETT.  │ -9.702 │-33.958 │159.847 │-129.733│             │
│  Stato           │ 🔴     │ 🔴     │  🟢   │  🔴    │             │
└──────────────────┴────────┴────────┴────────┴────────┴─────────────┘
```

**Colori celle**:
- Nero/sfondo verde chiaro: consuntivo (mesi passati, non editabile)
- Blu/sfondo giallo: previsione (editabile)
- Verde: totali (formula)
- Rosso: saldo negativo

**Freccia ▶ sulle uscite**: cliccabile, apre il dettaglio fornitori (sezione 5.3).

### 5.3 Vista Dettaglio: Drill-down per Voce Uscita

Quando Rosa clicca su una voce di uscita (es. "Materie Prime ▶"), si apre il dettaglio:

```
┌─────────────────────────────────────────────────────────────────────┐
│  MATERIE PRIME / CONSUMO — ORTI — Aprile 2026                     │
│  Stima PF: €80.000 | Scadenzario: €12.500 | Non coperto: €67.500  │
├──────────────────────────┬──────────┬────────────┬─────────────────┤
│  Fornitore               │ Importo  │ Scadenza   │ Stato           │
├──────────────────────────┼──────────┼────────────┼─────────────────┤
│  Le Croissant SRL        │  €3.200  │ 15/04/2026 │ In scadenza     │
│  Bianco Bufala           │  €1.800  │ 20/04/2026 │ In scadenza     │
│  Giacinto Di Palma       │    €950  │ 30/03/2026 │ ⚠️ Rolled fwd   │
│  Amazon EU               │    €420  │ 10/04/2026 │ In scadenza     │
│  ...                     │          │            │                 │
├──────────────────────────┼──────────┼────────────┼─────────────────┤
│  TOTALE SCADENZARIO      │ €12.500  │            │                 │
│  Stima PF residua        │ €67.500  │            │ (senza fattura) │
└──────────────────────────┴──────────┴────────────┴─────────────────┘
```

**Query per il dettaglio**:
```sql
SELECT
  p.nome_fornitore,
  d.nome_pf,
  d.voce_id,
  p.data_scadenza,
  p.importo_abs,
  p.tipo_documento,
  p.numero_documento,
  p.metodo_pagamento,
  p.is_intercompany,
  -- Roll-forward: se scaduta, sposta al mese corrente
  CASE
    WHEN p.data_scadenza < DATE_TRUNC(CURRENT_DATE('Europe/Rome'), MONTH)
    THEN 'ROLLED_FORWARD'
    WHEN p.data_scadenza < DATE_ADD(DATE_TRUNC(CURRENT_DATE('Europe/Rome'), MONTH), INTERVAL 1 MONTH)
    THEN 'IN_SCADENZA'
    ELSE 'FUTURO'
  END AS stato
FROM `hotelops-suite.hotelops.f_partite_aperte_fornitori` p
LEFT JOIN `hotelops-suite.hotelops.d_fornitori` d
  ON p.codice_fornitore = d.codice_fornitore
WHERE p.societa_id = @societa
  AND p.data_snapshot = (
    SELECT MAX(data_snapshot)
    FROM `hotelops-suite.hotelops.f_partite_aperte_fornitori`
    WHERE societa_id = @societa
  )
  AND p.is_intercompany = FALSE
ORDER BY
  GREATEST(p.data_scadenza, DATE_TRUNC(CURRENT_DATE('Europe/Rome'), MONTH)),
  p.importo_abs DESC
```

### 5.4 Scrittura Previsioni (Salva in BQ)

Quando Rosa modifica una cella di previsione e clicca "Salva":

1. Calcola hash: `MD5(societa_id | voce_id | anno | mese | "APP")`
2. DELETE existing row con stesso hash (o stessa combinazione societa+voce+anno+mese+fonte='APP')
3. INSERT nuova riga in `f_piano_finanziario_input`:

```python
row = {
    "hash_riga": make_hash(societa_id, voce_id, anno, mese, "APP"),
    "societa_id": societa_id,
    "voce_id": voce_id,
    "anno": anno,
    "mese": mese,
    "importo": nuovo_importo,
    "fonte": "APP",
    "note": f"Modificato da Rosa via app il {date.today()}",
    "file_sorgente": "app_piano_finanziario",
    "data_caricamento": datetime.now().isoformat(),
}
```

**Pattern DELETE-INSERT** (già usato da `actions/update_previsione.py`):
```sql
DELETE FROM `hotelops-suite.hotelops.f_piano_finanziario_input`
WHERE societa_id = @societa
  AND voce_id = @voce_id
  AND anno = @anno
  AND mese = @mese
  AND fonte = 'APP'
```

### 5.5 Export Excel

Bottone "📥 Excel" genera un file Excel con la stessa struttura di Rosa (reusa `actions/genera_piano_finanziario.py` come base, ma aggiungendo i fogli dettaglio uscite).

### 5.6 Stato Liquidità

Semaforo per ogni mese basato su saldo_proiettato:
- 🟢 OK: saldo > €50.000
- 🟡 ATTENZIONE: €0 < saldo ≤ €50.000
- 🔴 PERICOLO: saldo ≤ €0

---

## 6. Queries Pronte per l'App

### 6.1 Saldo Banca Corrente (ancora)
```sql
SELECT
  societa_id,
  ROUND(SUM(saldo_finale), 2) AS saldo_totale,
  MAX(data_snapshot) AS data_ancora
FROM (
  SELECT societa_id, banca_id, saldo_finale, data_snapshot,
    ROW_NUMBER() OVER (PARTITION BY societa_id, banca_id ORDER BY data_snapshot DESC) AS rn
  FROM `hotelops-suite.hotelops.f_saldi_banca_snapshot`
)
WHERE rn = 1
GROUP BY societa_id
```

### 6.2 Saldi per Banca (dettaglio)
```sql
SELECT banca_id, saldo_finale, data_snapshot
FROM (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY banca_id ORDER BY data_snapshot DESC) AS rn
  FROM `hotelops-suite.hotelops.f_saldi_banca_snapshot`
  WHERE societa_id = @societa
)
WHERE rn = 1
```

### 6.3 PF Mensile Completo
```sql
SELECT
  voce_id, voce_label, sezione, categoria, ord, mese,
  tipo_periodo, importo_consuntivo, importo_budget,
  scostamento, scostamento_pct
FROM `hotelops-suite.hotelops.v_piano_finanziario_mensile`
WHERE societa_id = @societa AND anno = @anno
ORDER BY ord, mese
```

### 6.4 Scadenzario per Voce e Mese (con roll-forward)
```sql
WITH latest AS (
  SELECT societa_id, MAX(data_snapshot) AS snap
  FROM `hotelops-suite.hotelops.f_partite_aperte_fornitori`
  GROUP BY societa_id
),
partite AS (
  SELECT
    p.*,
    d.voce_id,
    d.nome_pf,
    -- Roll-forward: fatture scadute → mese corrente
    GREATEST(
      DATE_TRUNC(p.data_scadenza, MONTH),
      DATE_TRUNC(CURRENT_DATE('Europe/Rome'), MONTH)
    ) AS mese_effettivo
  FROM `hotelops-suite.hotelops.f_partite_aperte_fornitori` p
  JOIN latest l ON p.societa_id = l.societa_id AND p.data_snapshot = l.snap
  LEFT JOIN `hotelops-suite.hotelops.d_fornitori` d ON p.codice_fornitore = d.codice_fornitore
  WHERE p.is_intercompany = FALSE
)
SELECT
  voce_id,
  EXTRACT(YEAR FROM mese_effettivo) AS anno,
  EXTRACT(MONTH FROM mese_effettivo) AS mese,
  nome_fornitore,
  nome_pf,
  data_scadenza,
  mese_effettivo,
  importo_abs,
  tipo_documento,
  numero_documento,
  metodo_pagamento,
  CASE
    WHEN data_scadenza < DATE_TRUNC(CURRENT_DATE('Europe/Rome'), MONTH) THEN 'ROLLED_FORWARD'
    ELSE 'IN_SCADENZA'
  END AS stato
FROM partite
WHERE societa_id = @societa
ORDER BY voce_id, mese_effettivo, importo_abs DESC
```

### 6.5 Totale Scadenzario per Voce e Mese (aggregato)
```sql
-- Come 6.4 ma aggregato — da sommare alle stime PF
WITH latest AS (
  SELECT societa_id, MAX(data_snapshot) AS snap
  FROM `hotelops-suite.hotelops.f_partite_aperte_fornitori`
  GROUP BY societa_id
)
SELECT
  d.voce_id,
  EXTRACT(YEAR FROM GREATEST(p.data_scadenza, DATE_TRUNC(CURRENT_DATE('Europe/Rome'), MONTH))) AS anno,
  EXTRACT(MONTH FROM GREATEST(p.data_scadenza, DATE_TRUNC(CURRENT_DATE('Europe/Rome'), MONTH))) AS mese,
  ROUND(SUM(p.importo_abs), 0) AS uscite_scadenzario,
  COUNT(*) AS n_fatture
FROM `hotelops-suite.hotelops.f_partite_aperte_fornitori` p
JOIN latest l ON p.societa_id = l.societa_id AND p.data_snapshot = l.snap
LEFT JOIN `hotelops-suite.hotelops.d_fornitori` d ON p.codice_fornitore = d.codice_fornitore
WHERE p.societa_id = @societa
  AND p.is_intercompany = FALSE
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3
```

### 6.6 Consuntivo per Voce (mesi passati)
```sql
SELECT voce_id, mese, ROUND(SUM(importo), 0) AS importo
FROM `hotelops-suite.hotelops.v_piano_finanziario_consuntivo`
WHERE societa_id = @societa AND anno = @anno
GROUP BY 1, 2
```

---

## 7. File di Riferimento nel Repo

```
hotelops/
├── cli.py                                    # CLI entry point (hotelops command)
├── pyproject.toml                            # Dependencies: pip install -e ".[dashboard]"
├── actions/
│   ├── genera_piano_finanziario.py           # Excel generator (base per export)
│   └── update_previsione.py                  # Write forecasts to BQ (pattern DELETE-INSERT)
├── lib/
│   ├── schemas.py                            # Pydantic models + validate_batch()
│   └── config.py                             # BQ constants (PROJECT, DATASET, table IDs)
├── bq/
│   ├── SCHEMA_CONTEXT.md                     # Full BQ schema docs
│   ├── views/
│   │   ├── v_piano_finanziario_mensile.sql   # Rosa's main view
│   │   ├── v_piano_finanziario_consuntivo.sql # Actuals per voce
│   │   └── v_previsione_cassa.sql            # Cash forward 12 mesi
│   └── dimensioni/
│       ├── d_voci_piano_finanziario.csv      # 29 voci mapping
│       └── d_fornitori.csv                   # 65 suppliers → voce_id
├── pipelines/amministrativa/
│   └── ingest_partite_aperte.py              # Scadenzario pipeline
└── dashboard/                                # ← APP VA QUI
    └── app_piano_finanziario.py              # Da creare
```

---

## 8. Checklist Implementazione

1. **Setup Streamlit base** con selector società (ORTI/INTUR) e anno
2. **Fetch saldo banca** da f_saldi_banca_snapshot (ancora)
3. **Fetch PF mensile** da v_piano_finanziario_mensile
4. **Fetch scadenzario** con roll-forward logic (query 6.4/6.5)
5. **Griglia principale** con voci × mesi, colori consuntivo/previsione
6. **Cascata saldo**: saldo_iniziale + cumsum(entrate - uscite)
7. **Celle editabili** per previsioni future (st.data_editor o st.number_input)
8. **Drill-down uscite** per fornitore (expander o modal)
9. **Salva in BQ**: DELETE-INSERT in f_piano_finanziario_input con fonte='APP'
10. **Export Excel**: genera file scaricabile (reusa genera_piano_finanziario.py)
11. **Semaforo liquidità**: verde/giallo/rosso per saldo proiettato
12. **Consuntivo vs Previsione**: tab aggiuntiva con delta storico

---

## 9. Note Tecniche

- **Auth BQ**: usa `google.cloud.bigquery.Client(project="hotelops-suite")`. L'auth è via `gcloud` (service account o user credentials del Mac di Stefano).
- **Streamlit**: `streamlit run dashboard/app_piano_finanziario.py`
- **Non usare localStorage** o cache browser — tutto in session_state di Streamlit.
- **Pydantic validation**: usa `validate_batch()` da `lib/schemas.py` prima di ogni write in BQ.
- **Hash dedup**: usa `make_hash()` da `lib/schemas.py` per generare hash_riga.
- **Timezone**: sempre `Europe/Rome` per date correnti.
- **Società operative**: anno operativo Nov-Ott (non calendario), ma il PF è su anno solare.
- **Encoding fornitori**: alcuni nomi hanno caratteri speciali (accenti, apostrofi) — usare UTF-8.
