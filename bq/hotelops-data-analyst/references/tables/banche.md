# Banche Tables (Bank Movements)

Bank transaction data sourced from CSV exports from home banking portals.

---

## f_banche_movimenti

**Location**: `hotelops-suite.hotelops.f_banche_movimenti`
**Description**: Bank statement transactions across all active bank accounts.
**Primary Key**: `hash_riga` (MD5 on bank movement key)
**Row Count**: ~3,745
**Period**: 2025-01-01 → 2026-03-12
**Update**: CSV from home banking, run via `run_banca.sh`
**Banks**: ORTI/MPS, ORTI/MPS_KROSS, INTUR/MPS, INTUR/SELLA, INTUR/INTESA

| Column | Type | Description | Notes |
|--------|------|-------------|-------|
| `hash_riga` | STRING | Dedup key | |
| `societa_id` | STRING | ORTI or INTUR | **Always filter** |
| `business_unit_id` | STRING | BU assignment | |
| `funzione_id` | STRING | Operational function | |
| `location_id` | STRING | Location | |
| `oggetto_id` | STRING | Transaction object | |
| `banca_id` | STRING | MPS, MPS_KROSS, SELLA, INTESA | Key filter |
| `data_operazione` | DATE | Transaction date | |
| `data_valuta` | DATE | Value date | |
| `descrizione` | STRING | Movement description | |
| `divisa` | STRING | Currency (EUR default) | |
| `importo_debito` | FLOAT | Outflow (positive) | |
| `importo_credito` | FLOAT | Inflow (positive) | |
| `importo_netto` | FLOAT | credito - debito | **Positive = inflow** |
| `categoria_raw` | STRING | Original bank category | |
| `sottocategoria_raw` | STRING | Original subcategory | |
| `categoria_normalizzata` | STRING | Normalized category | |
| `sottocategoria_normalizzata` | STRING | Normalized subcategory | |
| `tipo_movimento` | STRING | Movement type | Key for LIKE joins |
| `codice_identificativo_banca` | STRING | CRO / bank reference | |
| `etichette` | STRING | Manual tags | |
| `note` | STRING | Notes | |
| `data_ingresso` | DATE | BQ load date | |
| `file_sorgente` | STRING | Source file | |
| `riga_sorgente` | INTEGER | Row in source | |

### Tipo Movimento Values

| tipo_movimento | Description | Category |
|----------------|-------------|----------|
| `(09) INCASSO TRAMITE P.O.S.` | POS credit card receipts | Entrate |
| `(26) VOSTRA DISPOSIZIONE A FAVORE DI` | Outgoing bank transfer | Uscite |
| `(48) BONIFICO A VOSTRO FAVORE` | Incoming bank transfer | Entrate |
| `(78) VERSAMENTO CONTANTE` | Cash deposit | Entrate |
| `Commissioni` | Bank fees | Uscite |
| `Bonifico` | Generic transfer | Check sign |

**Relationships**:
- Joins to `d_voci_piano_finanziario` on `UPPER(tipo_movimento) LIKE CONCAT('%', banca_tipo_pat, '%')`
- Use `societa_id + banca_id` to identify specific bank accounts

---

## Sample Queries

### Cashflow mensile per banca (ORTI)
```sql
SELECT
  FORMAT_DATE('%Y-%m', data_operazione) AS periodo,
  banca_id,
  SUM(importo_credito) AS entrate,
  SUM(importo_debito) AS uscite,
  SUM(importo_netto) AS netto
FROM `hotelops-suite.hotelops.f_banche_movimenti`
WHERE societa_id = 'ORTI'
GROUP BY periodo, banca_id
ORDER BY periodo, banca_id;
```

### Incassi POS giornalieri
```sql
SELECT
  data_operazione,
  SUM(importo_credito) AS incasso_pos
FROM `hotelops-suite.hotelops.f_banche_movimenti`
WHERE societa_id = 'ORTI'
  AND UPPER(tipo_movimento) LIKE '%(09)%'
GROUP BY data_operazione
ORDER BY data_operazione;
```

### Top tipo_movimento per volume
```sql
SELECT
  tipo_movimento,
  COUNT(*) AS n,
  SUM(importo_credito) AS tot_credito,
  SUM(importo_debito) AS tot_debito
FROM `hotelops-suite.hotelops.f_banche_movimenti`
WHERE societa_id = 'ORTI'
GROUP BY tipo_movimento
ORDER BY n DESC;
```
