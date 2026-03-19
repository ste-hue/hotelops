# HotelOps Entities & Relationships

## Core Entities

### Società (Company)
- **Definition**: Legal entity. Two companies in the group.
- **Primary Table**: Appears as `societa_id` in every fact table
- **ID Field**: `societa_id` — STRING: `'ORTI'` or `'INTUR'`
- **Rule**: ALWAYS filter by societa_id. Never mix unless doing consolidated group analysis.

| ID | Name | Role | BUs |
|----|------|------|-----|
| ORTI | ORTI SRL | Hotel operations | HOTEL, RESIDENCE, CVM, LIDO, HQ |
| INTUR | INTUR SRL | Holding / real estate | HQ |

### Business Unit (BU)
- **Definition**: Operational division within ORTI
- **Primary Table**: `business_unit_id` in fact tables
- **Values**: HOTEL, RESIDENCE, CVM, LIDO, HQ
- **Note**: INTUR typically only uses HQ

### Voce Piano Finanziario
- **Definition**: Conceptual financial line item that unifies data across systems
- **Primary Table**: `d_voci_piano_finanziario`
- **ID Field**: `voce_id` (e.g., `ENTRATE_HOTEL`, `USCITE_SALARI`)
- **Role**: The Rosetta Stone mapping Esolver account codes ↔ bank transaction types ↔ manual input
- **Sections**: ENTRATE (11 voci), USCITE (18 voci)

### Conto (Account)
- **Definition**: Chart of accounts entry from Esolver ERP
- **Primary Table**: `d_piano_conti`
- **ID Field**: `codice_conto` (6-8 digits, no dots)
- **Subtypes**: C=Cliente, F=Fornitore, B=Banca, S=Cespite
- **Sections**: CE (Conto Economico / P&L), SP (Stato Patrimoniale / Balance Sheet)

### Banca (Bank Account)
- **Definition**: Bank account per società
- **ID Field**: `banca_id` in `f_banche_movimenti`
- **Active Banks**:
  - ORTI: MPS, MPS_KROSS
  - INTUR: MPS, SELLA, INTESA

---

## Relationships (Join Keys)

### Pattern-Based Joins (LIKE)

These are the most important and trickiest joins. The `d_voci_piano_finanziario` table uses prefix patterns, not exact matches:

```
f_movimenti_contabili.cod_conto
    LIKE CONCAT(d_voci_piano_finanziario.cod_conto_pattern, '%')
    → Used in v_piano_finanziario_consuntivo (fonte=ESOLVER)

f_banche_movimenti.tipo_movimento
    LIKE CONCAT('%', d_voci_piano_finanziario.banca_tipo_pat, '%')
    → Used in v_piano_finanziario_consuntivo (fonte=BANCHE)

f_budget_mensile.codice_conto (NORMALIZED: REPLACE(codice_conto, '.', ''))
    LIKE CONCAT(d_voci_piano_finanziario.cod_conto_pattern, '%')
    → Used in v_piano_finanziario_mensile (importo_budget)
```

**WARNING**: `d_voci_piano_finanziario` has up to 3 pattern columns: `cod_conto_pattern`, `cod_conto_pat2`, `cod_conto_pat3`. Check all three in OR conditions.

### Direct Joins (Equality)

```
f_piano_finanziario_input.voce_id
    = d_voci_piano_finanziario.voce_id
    → Direct FK, used for manual/projected input

f_movimenti_contabili.cod_conto
    = d_piano_conti.codice_conto
    → Lookup account description, tipo_conto, sezione
```

### Common Join Conditions

```sql
-- Voce match via Esolver account codes
LEFT JOIN `hotelops-suite.hotelops.d_voci_piano_finanziario` v
  ON m.cod_conto LIKE CONCAT(v.cod_conto_pattern, '%')
  AND (v.societa_id IS NULL OR v.societa_id = m.societa_id)

-- Account description lookup
LEFT JOIN `hotelops-suite.hotelops.d_piano_conti` pc
  ON m.cod_conto = pc.codice_conto

-- Budget normalization join
LEFT JOIN `hotelops-suite.hotelops.f_budget_mensile` b
  ON REPLACE(b.codice_conto, '.', '') LIKE CONCAT(v.cod_conto_pattern, '%')
  AND b.societa_id = scaffold.societa_id
  AND b.anno = scaffold.anno
  AND b.mese = scaffold.mese
```

---

## Entity Relationship Diagram (Conceptual)

```
d_voci_piano_finanziario (Rosetta Stone)
    ├── [LIKE cod_conto_pattern] → f_movimenti_contabili (Esolver actual)
    ├── [LIKE banca_tipo_pat]   → f_banche_movimenti (Bank actual)
    ├── [= voce_id]             → f_piano_finanziario_input (Manual/projected)
    └── [LIKE cod_conto_pattern] → f_budget_mensile (Budget, after dot-removal)

f_movimenti_contabili
    └── [= codice_conto] → d_piano_conti (Account metadata)

Views aggregate these:
    v_piano_finanziario_consuntivo → actual amounts per voce
    v_piano_finanziario_mensile   → budget vs actual per voce per month
    v_cashflow_mensile            → net cash per month
    v_incassi_per_canale          → receipts by channel
```
