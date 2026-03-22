# Piano Finanziario — Tabelle Cassa

Dominio del Piano Finanziario: flussi di cassa previsionali e consuntivi per voce PF. Usato da Rosa (Tesoreria) per la gestione della liquidità.

---

## Tabelle Chiave

### f_piano_finanziario_input
**Location**: `hotelops-suite.hotelops.f_piano_finanziario_input`
**Descrizione**: Input manuali di previsione cash flow per voce PF. Fonti multiple (PIANO_FINANZIARIO da XLSX Rosa, SCADENZIARIO per mutui, BVA_2026 per ricavi, CLI/NANOCLAW per aggiornamenti).
**Primary Key**: `hash_riga` (MD5 di societa_id | voce_id | anno | mese | fonte)
**Row Count**: ~213
**Update**: WRITE_APPEND con MD5 dedup / DELETE-INSERT per fonte

| Colonna | Tipo | Descrizione | Note |
|---------|------|-------------|------|
| `hash_riga` | STRING | Chiave dedup MD5 | |
| `societa_id` | STRING REQUIRED | ORTI o INTUR | |
| `voce_id` | STRING REQUIRED | FK → d_voci_piano_finanziario | Es: ENTRATE_HOTEL |
| `anno` | INTEGER REQUIRED | Anno | 2026, 2027 |
| `mese` | INTEGER REQUIRED | Mese (1-12) | |
| `importo` | FLOAT | Importo previsto (€) | Sempre positivo |
| `fonte` | STRING | Origine dato | PIANO_FINANZIARIO, SCADENZIARIO, BVA_2026, CLI, NANOCLAW |
| `note` | STRING | Note libere | |
| `file_sorgente` | STRING | File di origine | |
| `data_caricamento` | TIMESTAMP | Timestamp caricamento | |

**Relazioni**:
- `voce_id` → `d_voci_piano_finanziario.voce_id`

---

### f_chiusura_mensile
**Location**: `hotelops-suite.hotelops.f_chiusura_mensile`
**Descrizione**: Snapshot di fine mese generato da `hotelops chiudi`. Confronta previsione vs consuntivo per ogni voce e salva il delta. Serve per tracciare l'accuratezza delle previsioni nel tempo.
**Update**: DELETE-INSERT per societa + anno + mese

| Colonna | Tipo | Descrizione | Note |
|---------|------|-------------|------|
| `societa_id` | STRING REQUIRED | ORTI o INTUR | |
| `anno` | INTEGER REQUIRED | Anno | |
| `mese` | INTEGER REQUIRED | Mese (1-12) | |
| `voce_id` | STRING REQUIRED | FK → d_voci_piano_finanziario | |
| `voce_label` | STRING | Label della voce | |
| `sezione` | STRING | ENTRATE o USCITE | |
| `importo_consuntivo` | FLOAT | Importo effettivo | |
| `importo_previsione` | FLOAT | Importo previsto | |
| `delta` | FLOAT | Consuntivo - Previsione | |
| `delta_pct` | FLOAT | Percentuale delta | |
| `saldo_banca_fine_mese` | FLOAT | Saldo banca a fine mese | |
| `data_chiusura` | STRING | Data chiusura (ISO) | |

---

### f_saldi_banca_snapshot
**Location**: `hotelops-suite.hotelops.f_saldi_banca_snapshot`
**Descrizione**: Saldi bancari storici estratti dagli header degli Excel MPS. Usato come ancora per calcolare saldi a qualsiasi data.
**Update**: DELETE-INSERT per societa + banca + data_snapshot

| Colonna | Tipo | Descrizione | Note |
|---------|------|-------------|------|
| `societa_id` | STRING | ORTI o INTUR | |
| `banca_id` | STRING | ID banca | |
| `data_snapshot` | DATE | Data dello snapshot | |
| `saldo_finale` | FLOAT | Saldo finale (€) | |
| `file_sorgente` | STRING | File origine | |
| `data_caricamento` | TIMESTAMP | Timestamp caricamento | |

---

## View

### v_piano_finanziario_mensile ⭐ LA VIEW PER ROSA
**Location**: `hotelops-suite.hotelops.v_piano_finanziario_mensile`
**Descrizione**: Budget vs consuntivo per voce PF, rolling 18 mesi (−6 storia, +12 previsione).

**Come funziona**:
1. **Scaffold**: Genera tutte le combinazioni voce × mese × società per 18 mesi
2. **Consuntivo**: Aggrega da `v_piano_finanziario_consuntivo` (movimenti + banche via LIKE)
3. **Budget**: Aggrega da `f_budget_mensile` (via LIKE su cod_conto normalizzato) + `f_piano_finanziario_input` (via voce_id diretto)
4. **Calcola**: scostamento = consuntivo - budget

| Colonna | Tipo | Descrizione |
|---------|------|-------------|
| `societa_id` | STRING | ORTI o INTUR |
| `voce_id` | STRING | FK → d_voci |
| `voce_label` | STRING | Label leggibile |
| `sezione` | STRING | ENTRATE o USCITE |
| `categoria` | STRING | Categoria (Ricavi, Personale, etc.) |
| `ord` | INTEGER | Ordine display |
| `anno` | INTEGER | Anno |
| `mese` | INTEGER | Mese (1-12) |
| `periodo` | STRING | "YYYY-MM" |
| `tipo_periodo` | STRING | CONSUNTIVO o BUDGET |
| `importo_consuntivo` | FLOAT | Importo effettivo |
| `importo_budget` | FLOAT | Importo previsto (budget + input manuale) |
| `scostamento` | FLOAT | Consuntivo - Budget |
| `scostamento_pct` | FLOAT | Delta % |

### v_piano_finanziario_consuntivo
**Location**: `hotelops-suite.hotelops.v_piano_finanziario_consuntivo`
**Descrizione**: Aggrega i movimenti effettivi per voce PF. Unisce dati Esolver (competenza→cassa) e dati banche.

**Il pattern LIKE** — come funziona il matching:
```sql
-- Per fonte ESOLVER: match su cod_conto dei movimenti contabili
m.cod_conto LIKE v.cod_conto_pattern
-- Es: cod_conto_pattern = '4101%' matcha 410101, 410102, 410103...

-- Per fonte BANCHE: match su tipo_movimento delle transazioni bancarie
b.tipo_movimento LIKE v.banca_tipo_pat
-- Es: banca_tipo_pat = '%(09)%' matcha "(09) INCASSO TRAMITE P.O.S."
```

---

### v_previsione_cassa ⭐ LA VIEW PER LA LIQUIDITÀ
**Location**: `hotelops-suite.hotelops.v_previsione_cassa`
**SQL Source**: `bq/views/v_previsione_cassa.sql`
**Descrizione**: Proiezione cash forward mensile con ancora bancaria reale. Rolling 12 mesi dall'ultimo saldo certificato. Combina consuntivo (mesi chiusi) e stime PF (mesi futuri) con lo scadenzario come colonna informativa.
**Status**: ✅ **LIVE** — deployata marzo 2026. `hotelops saldo` la usa per la proiezione.

**Come funziona** (5 step):
1. **ANCORA**: Ultimo saldo reale per banca da `f_saldi_banca_snapshot`, aggregato per società
2. **MESI**: 12 mesi in avanti dall'ancora (es. mar 2026 → feb 2027)
3. **FLUSSI per mese**:
   - `tipo_periodo = CONSUNTIVO` → actuals da `v_piano_finanziario_consuntivo`
   - `tipo_periodo = CORRENTE/BUDGET` → stime da `f_piano_finanziario_input` (fonte=PIANO_FINANZIARIO)
4. **SALDO PROIETTATO**: saldo_ancora + SUM(netto) cumulativo con window function
5. **SCADENZARIO**: Uscite certe da `f_partite_aperte_fornitori` — colonna **informativa**, non entra nel saldo proiettato per evitare doppio conteggio con le stime PF

| Colonna | Tipo | Descrizione | Note |
|---------|------|-------------|------|
| `societa_id` | STRING | ORTI o INTUR | |
| `anno` | INTEGER | Anno | |
| `mese` | INTEGER | Mese (1-12) | |
| `periodo` | STRING | "YYYY-MM" | |
| `tipo_periodo` | STRING | CONSUNTIVO, CORRENTE, BUDGET | Basato su data corrente timezone Europe/Rome |
| `saldo_ancora` | FLOAT | Saldo iniziale dall'ultimo snapshot | Costante per tutti i mesi |
| `data_ancora` | DATE | Data dell'ultimo snapshot usato | |
| `entrate` | FLOAT | Entrate del mese | Consuntivo o stima PF |
| `uscite_pf` | FLOAT | Uscite del mese (da PF) | Usate per il saldo proiettato |
| `uscite_scad` | FLOAT | Uscite certe da scadenzario | **Informativa** — non entra nel saldo |
| `n_fatture_scad` | INTEGER | Conteggio fatture nello scadenzario | |
| `netto_pf` | FLOAT | entrate - uscite_pf | |
| `saldo_proiettato` | FLOAT | Saldo rolling cumulativo | ancora + cumsum(netto_pf) |
| `stato_liquidita` | STRING | OK, ATTENZIONE, PERICOLO | <0 = PERICOLO, <50K = ATTENZIONE |

**Dipendenza**: Richiede almeno un record in `f_saldi_banca_snapshot` per società. Attualmente: ORTI MPS €134,647 al 28/02/2026.

---

## Query Comuni

### Riepilogo PF mensile con totali
```sql
WITH pf AS (
    SELECT *
    FROM `hotelops-suite.hotelops.v_piano_finanziario_mensile`
    WHERE societa_id = 'ORTI' AND anno = 2026
)
SELECT
    mese,
    SUM(CASE WHEN sezione = 'ENTRATE' THEN importo_budget ELSE 0 END) AS budget_entrate,
    SUM(CASE WHEN sezione = 'USCITE' THEN importo_budget ELSE 0 END) AS budget_uscite,
    SUM(CASE WHEN sezione = 'ENTRATE' THEN importo_consuntivo ELSE 0 END) AS cons_entrate,
    SUM(CASE WHEN sezione = 'USCITE' THEN importo_consuntivo ELSE 0 END) AS cons_uscite,
    SUM(CASE WHEN sezione = 'ENTRATE' THEN importo_budget ELSE 0 END)
    - SUM(CASE WHEN sezione = 'USCITE' THEN importo_budget ELSE 0 END) AS netto_budget,
    SUM(CASE WHEN sezione = 'ENTRATE' THEN importo_consuntivo ELSE 0 END)
    - SUM(CASE WHEN sezione = 'USCITE' THEN importo_consuntivo ELSE 0 END) AS netto_consuntivo
FROM pf
GROUP BY mese
ORDER BY mese
```

### Accuratezza previsioni (da chiusure mensili)
```sql
SELECT
    voce_label,
    sezione,
    AVG(ABS(delta_pct)) AS avg_errore_pct,
    COUNT(*) AS n_mesi
FROM `hotelops-suite.hotelops.f_chiusura_mensile`
WHERE societa_id = 'ORTI'
GROUP BY voce_label, sezione
HAVING COUNT(*) >= 2
ORDER BY AVG(ABS(delta_pct)) DESC
```

### Proiezione liquidità — mesi a rischio (v_previsione_cassa)
```sql
-- Mesi dove il saldo proiettato scende sotto zero o sotto soglia
SELECT
    societa_id,
    periodo,
    tipo_periodo,
    entrate,
    uscite_pf,
    netto_pf,
    saldo_proiettato,
    stato_liquidita,
    uscite_scad  -- uscite certe da fatture (informativa)
FROM `hotelops-suite.hotelops.v_previsione_cassa`
WHERE societa_id = 'ORTI'
ORDER BY anno, mese
```

### Confronto uscite previste vs uscite certe da scadenzario
```sql
-- Per ogni mese futuro: quanto delle uscite PF è "coperto" da fatture già registrate?
SELECT
    periodo,
    uscite_pf        AS uscite_stimate_pf,
    uscite_scad      AS uscite_certe_scad,
    n_fatture_scad,
    SAFE_DIVIDE(uscite_scad, NULLIF(uscite_pf, 0)) * 100 AS pct_coperto
FROM `hotelops-suite.hotelops.v_previsione_cassa`
WHERE societa_id = 'ORTI'
  AND tipo_periodo IN ('CORRENTE', 'BUDGET')
ORDER BY anno, mese
```
