# Contabilità Tables (Esolver ERP)

Accounting data sourced from Esolver ERP via manual XLS exports.

---

## f_movimenti_contabili

**Location**: `hotelops-suite.hotelops.f_movimenti_contabili`
**Description**: General ledger journal entries from Esolver. The primary source for actual accounting data.
**Primary Key**: `hash_riga` (MD5 of societa_id | id_documento | num_progr_riga)
**Row Count**: ~31,821
**Period**: 2024-12-03 → 2026-03-18
**Update**: Manual XLS upload, WRITE_APPEND with hash dedup
**Pipeline**: `ingest_movimenti_contabili.py`

| Column | Type | Description | Notes |
|--------|------|-------------|-------|
| `hash_riga` | STRING REQUIRED | MD5 dedup key | |
| `societa_id` | STRING REQUIRED | ORTI or INTUR | **Always filter** |
| `id_documento` | INTEGER | Esolver document ID | |
| `num_progr_riga` | INTEGER | Line number within document | |
| `gruppo_doc` | STRING | Document group (FAT, PNC) | |
| `anno` | INTEGER | Registration year | |
| `mese` | INTEGER | Registration month (1-12) | |
| `data_registrazione` | DATE | Accounting registration date | **Can lag weeks behind** |
| `sigla_doc` | STRING | Document type code | |
| `rif_registrazione` | STRING | Reference (e.g., "PNC n 123") | |
| `num_doc_originale` | STRING | Original document number | |
| `data_originale` | DATE | Original document date | |
| `tipo_documento` | STRING | Document type | |
| `cod_conto` | STRING | Account code **WITHOUT dots** | 6-8 digits: `570913` |
| `cod_partitario` | STRING | Sub-ledger code (customer/supplier) | |
| `rag_sociale` | STRING | Counterparty name | Useful for intercompany check |
| `causale_contabile` | STRING | Accounting reason | |
| `imp_dare` | FLOAT | Debit amount (€) | Always positive |
| `imp_avere` | FLOAT | Credit amount (€) | Always positive |
| `cod_divisione` | STRING | Esolver division/BU code | |
| `file_sorgente` | STRING | Source XLS filename | |
| `data_ingresso` | DATE | BQ load date | |

**Critical Notes**:
- `cod_conto` is always **without dots**: `57.09.13` → `570913`
- 6 digits = 3 levels, 8 digits = 4 levels
- Only **leaf** accounts have movements (no double-counting on parents)
- Bank accounts (15xxxx) are NOT present — those are in `f_banche_movimenti`

**Relationships**:
- Joins to `d_piano_conti` on `cod_conto = codice_conto`
- Joins to `d_voci_piano_finanziario` on `cod_conto LIKE CONCAT(cod_conto_pattern, '%')`

---

## f_bilancino

**Location**: `hotelops-suite.hotelops.f_bilancino`
**Description**: Trial balance (bilancio di verifica) from Esolver periodic export.
**Primary Key**: `hash_riga`
**Row Count**: 110
**Pipeline**: `ingest_bilancino.py`

| Column | Type | Description | Notes |
|--------|------|-------------|-------|
| `hash_riga` | STRING REQUIRED | Dedup key | |
| `societa_id` | STRING REQUIRED | ORTI or INTUR | |
| `mese` | STRING REQUIRED | Period as "YYYY-MM" | String, not integer! |
| `codice_conto` | STRING REQUIRED | Account code | |
| `descrizione` | STRING | Account description | |
| `tipo_conto` | STRING | Account type | |
| `sezione` | STRING | CE or SP | |
| `dare` | FLOAT | Period total debit | |
| `avere` | FLOAT | Period total credit | |
| `saldo` | FLOAT | Balance (dare - avere) | |
| `business_unit_id` | STRING | BU | |
| `categoria` | STRING | Category | |
| `file_sorgente` | STRING | Source file | |
| `data_ingresso` | STRING | Load date (string!) | |

---

## f_accodamenti

**Location**: `hotelops-suite.hotelops.f_accodamenti`
**Description**: Bank-side accounting entries from Esolver. Movements registered on bank accounts within the ERP.
**Primary Key**: `hash_riga`
**Row Count**: 63
**Period**: 2026-01-01 → 2026-01-22

| Column | Type | Description | Notes |
|--------|------|-------------|-------|
| `id_registrazione` | STRING | Registration ID | |
| `societa_id` | STRING | ORTI or INTUR | |
| `business_unit_id` | STRING | BU | |
| `banca_id` | STRING | Bank | |
| `data_registrazione` | DATE | Registration date | |
| `descrizione` | STRING | Description | |
| `importo` | FLOAT | Net amount | |
| `importo_dare` | FLOAT | Debit | |
| `importo_avere` | FLOAT | Credit | |
| `hash_riga` | STRING | Dedup key | |

---

## Sample Queries

### Movimenti per conto con descrizione
```sql
SELECT
  m.data_registrazione, m.cod_conto,
  pc.descrizione AS desc_conto, pc.tipo_conto,
  m.rag_sociale, m.causale_contabile,
  m.imp_dare, m.imp_avere,
  (m.imp_dare - m.imp_avere) AS saldo_mov
FROM `hotelops-suite.hotelops.f_movimenti_contabili` m
LEFT JOIN `hotelops-suite.hotelops.d_piano_conti` pc
  ON m.cod_conto = pc.codice_conto
WHERE m.societa_id = 'ORTI' AND m.anno = 2026
ORDER BY m.data_registrazione;
```

### Totale per conto (top 20)
```sql
SELECT
  cod_conto, COUNT(*) AS n_movimenti,
  SUM(imp_dare) AS tot_dare, SUM(imp_avere) AS tot_avere,
  SUM(imp_dare - imp_avere) AS saldo
FROM `hotelops-suite.hotelops.f_movimenti_contabili`
WHERE societa_id = 'ORTI' AND anno = 2026
GROUP BY cod_conto
ORDER BY ABS(saldo) DESC
LIMIT 20;
```
