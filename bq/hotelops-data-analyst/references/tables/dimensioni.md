# Dimensioni Tables (Lookups & Dictionaries)

Reference/dimension tables that provide metadata, mappings, and categorizations.

---

## d_voci_piano_finanziario (THE ROSETTA STONE)

**Location**: `hotelops-suite.hotelops.d_voci_piano_finanziario`
**Description**: Central dictionary mapping financial plan line items to Esolver account codes and bank transaction types. This is the most important dimension table — it bridges all three data worlds.
**Primary Key**: `voce_id`
**Row Count**: 29
**Update**: WRITE_TRUNCATE from CSV dictionary
**Pipeline**: `ingest_voci_piano_finanziario.py`

| Column | Type | Description | Notes |
|--------|------|-------------|-------|
| `voce_id` | STRING | PK — e.g., ENTRATE_HOTEL, USCITE_SALARI | |
| `voce_label` | STRING | Human-readable label | |
| `sezione` | STRING | ENTRATE or USCITE | |
| `categoria` | STRING | Category (Ricavi, Personale, Utenze...) | |
| `societa_id` | STRING | NULL=both, ORTI/INTUR=specific | |
| `fonte` | STRING | ESOLVER, BANCHE, or MANUALE | Determines join strategy |
| `cod_conto_pattern` | STRING | Account prefix for LIKE match (no dots) | Primary pattern |
| `cod_conto_pat2` | STRING | Alternative pattern 2 | Check in OR |
| `cod_conto_pat3` | STRING | Alternative pattern 3 | Check in OR |
| `banca_tipo_pat` | STRING | LIKE pattern on tipo_movimento | For bank data |
| `ord` | INTEGER | Display order | |
| `bu_filter` | STRING | BU-specific filter (e.g., LIDO) | |
| `categoria_ce` | STRING | P&L category | |
| `tipo_costo` | STRING | F, V, P, X, IP | |

**How the matching works**:
- `fonte=ESOLVER` → `f_movimenti_contabili.cod_conto LIKE CONCAT(cod_conto_pattern, '%')`
- `fonte=BANCHE` → `UPPER(f_banche_movimenti.tipo_movimento) LIKE CONCAT('%', banca_tipo_pat, '%')`
- `fonte=MANUALE` → `f_piano_finanziario_input.voce_id` direct FK

**Active Voci**:
- ENTRATE (11): ENTRATE_HOTEL, ENTRATE_RESIDENCE, ENTRATE_CVM, ENTRATE_SPIAGGIA_ORTI, ENTRATE_SPIAGGIA, ENTRATE_AFFITTI_INTUR, ENTRATE_AFFITTI_MINORI, ENTRATE_SUPERMERCATO, ENTRATE_CAPARRE, ENTRATE_CAPARRE_INTUR, ENTRATE_RIENTRO_SOSPESI
- USCITE (18): USCITE_SALARI, USCITE_UTENZE_ENERGIA/ACQUA/GAS/TEL/CONNETTIVITA, USCITE_MATERIE_PRIME, USCITE_TASSE, USCITE_MUTUI, USCITE_MUTUI_SEMESTRALE, USCITE_SPESE_BANCARIE, USCITE_CONSULENZE, USCITE_GODIMENTO_BENI, USCITE_COMMISSIONI, USCITE_CANONI, USCITE_CANONE_PASSIVO, USCITE_VARIE, USCITE_VARIE_EXT

---

## d_piano_conti

**Location**: `hotelops-suite.hotelops.d_piano_conti`
**Description**: Esolver chart of accounts — full account hierarchy with types and sections.
**Primary Key**: `codice_conto`
**Row Count**: 2,103
**Pipeline**: `ingest_piano_conti.py`

| Column | Type | Description | Notes |
|--------|------|-------------|-------|
| `codice_conto` | STRING REQUIRED | PK — 6-8 digits, no dots | |
| `descrizione` | STRING | Account description | |
| `tipo_conto` | STRING | C=Cliente, F=Fornitore, B=Banca, S=Cespite | |
| `sezione` | STRING | CE (P&L) or SP (Balance Sheet) | |
| `partitario` | STRING | Sub-ledger type | |
| `business_unit_id` | STRING | Associated BU | |

---

## d_budget_costi_fissi

**Location**: `hotelops-suite.hotelops.d_budget_costi_fissi`
**Description**: Annual snapshot of fixed costs per BU from consultant mapping.
**Row Count**: 43

| Column | Type | Description | Notes |
|--------|------|-------------|-------|
| `societa_id` | STRING REQUIRED | ORTI or INTUR | |
| `codice_conto` | STRING REQUIRED | Code WITH dots | |
| `descrizione` | STRING | Description | |
| `tipo` | STRING | Cost type | |
| `actuals_2025` | FLOAT | 2025 actuals | |
| `budget_2026` | FLOAT | 2026 annual budget | |
| `hotel` | FLOAT | HOTEL BU allocation | |
| `residence` | FLOAT | RESIDENCE BU allocation | |
| `cvm` | FLOAT | CVM BU allocation | |
| `spiaggia` | FLOAT | LIDO BU allocation | |
| `hq` | FLOAT | HQ BU allocation | |

---

## d_personale_mensile

**Location**: `hotelops-suite.hotelops.d_personale_mensile`
**Description**: Monthly personnel costs by organizational division.
**Row Count**: 78

| Column | Type | Description | Notes |
|--------|------|-------------|-------|
| `divisione` | STRING REQUIRED | MANAGEMENT, ROOM DIVISION, F&B, SPIAGGIA, AMM/ECO... | |
| `anno` | INTEGER REQUIRED | Year | |
| `mese` | STRING REQUIRED | "Gen", "Feb"... | Text, not number! |
| `mese_num` | INTEGER | Month as number 1-12 | Use for sorting |
| `importo` | FLOAT | Monthly cost per division (€) | |

---

## d_categorie_conti

**Location**: `hotelops-suite.hotelops.d_categorie_conti`
**Description**: Account → management category mapping from budget workbook.
**Row Count**: 167

---

## d_periodi_apertura

**Location**: `hotelops-suite.hotelops.d_periodi_apertura`
**Description**: Seasonal opening/closing calendar per BU per year.
**Row Count**: 3

| Column | Type | Description | Notes |
|--------|------|-------------|-------|
| `societa_id` | STRING REQUIRED | ORTI or INTUR | |
| `business_unit_id` | STRING REQUIRED | HOTEL, LIDO, RESIDENCE | |
| `anno` | INTEGER REQUIRED | Year | |
| `data_apertura` | DATE REQUIRED | Season opening | |
| `data_chiusura` | DATE | Season closing | |
| `notti_apertura` | INTEGER | Open nights count | |
| `note` | STRING | Notes | |
