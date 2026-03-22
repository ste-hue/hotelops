# HotelOps Key Metrics

## Financial Metrics

### Scostamento Budget vs Consuntivo
- **Definition**: Monthly variance between budget and actual for each voce
- **Table**: `v_piano_finanziario_mensile`
- **Formula**: `scostamento = importo_consuntivo - importo_budget`
- **Pct**: `scostamento_pct` (pre-calculated in view)
- **Time grain**: Monthly
- **Caveats**:
  - `tipo_periodo = 'CONSUNTIVO'` for months with actual data, `'BUDGET'` for future
  - View window is rolling 18 months (-6m to +12m from today)
  - Registration delays mean recent "consuntivo" months may be incomplete

### Cashflow Netto
- **Definition**: Net cash inflows minus outflows
- **Table**: `f_banche_movimenti` or `v_cashflow_mensile`
- **Formula**: `SUM(importo_netto)` — already signed (positive = inflow)
- **Alternative**: `SUM(importo_credito) - SUM(importo_debito)`
- **Time grain**: Daily (raw) or Monthly (aggregated)
- **Caveats**: Exclude intercompany transfers

### Saldo Banca
- **Definition**: Running bank balance per account
- **Table**: `f_banche_movimenti`
- **Formula**: Cumulative `SUM(importo_netto) OVER (PARTITION BY banca_id ORDER BY data_operazione)`
- **Caveats**: Starting balance not stored — need to calibrate with a known snapshot

### Incassi POS
- **Definition**: Credit card receipts via POS terminals
- **Table**: `f_banche_movimenti`
- **Formula**: `SUM(importo_credito) WHERE UPPER(tipo_movimento) LIKE '%(09)%'`
- **Caveats**: "(09)" prefix identifies POS in tipo_movimento

### Costo Personale per Divisione
- **Definition**: Labor cost breakdown by organizational division
- **Table**: `d_personale_mensile`
- **Formula**: `SUM(importo)` grouped by `divisione`, `mese_num`
- **Caveats**: `mese` is text ("Gen", "Feb"...) — use `mese_num` for sorting

### Costi Fissi per BU
- **Definition**: Fixed cost allocation across Business Units
- **Table**: `d_budget_costi_fissi`
- **Formula**: Read BU-specific columns: `hotel`, `residence`, `cvm`, `spiaggia`, `hq`
- **Caveats**: Annual snapshot, not monthly. For monthly, use `f_budget_mensile` with `tipo_costo = 'F'`

---

## Aggregation Rules

### Sign Conventions

| Context | Entrate (inflows) | Uscite (outflows) |
|---------|-------------------|-------------------|
| `f_movimenti_contabili` | `imp_avere - imp_dare` | `imp_dare - imp_avere` |
| `f_banche_movimenti` | `importo_credito` (or `importo_netto > 0`) | `importo_debito` (or `importo_netto < 0`) |
| `v_piano_finanziario_*` | Positive = inflow | Positive = outflow |
| `f_bilancino` | `saldo = dare - avere` | Per accounting convention |

### Date Dimensions

- **Fiscal year** = Calendar year (Jan-Dec)
- **Seasonal business**: Hotels open Apr-Oct (see `d_periodi_apertura`)
- **Monthly grain**: Most views aggregate to `anno + mese`
- **Period format**: `FORMAT_DATE('%Y-%m', date_col)` for display
