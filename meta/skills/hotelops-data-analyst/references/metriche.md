# Metriche e KPI — Hotelops

## Metriche del Piano Finanziario (Cassa)

### Saldo Banca Corrente
- **Definizione**: Saldo effettivo del conto bancario a una data specifica
- **Formula**: `saldo_snapshot + SUM(importo_netto) [transazioni dopo lo snapshot]`
- **Tabelle**: `f_saldi_banca_snapshot` (ancora) + `f_banche_movimenti` (movimenti successivi)
- **Granularità**: Giornaliera
- **Ancora corrente**: ORTI MPS: €134,647 al 28/02/2026. INTUR: da inserire.
- **Nota storica**: Prima dell'ancora, la somma cumulativa di f_banche_movimenti dava −€3.26M per ORTI (senza senso). Ora con l'ancora il saldo è corretto.

```sql
-- Saldo banca a una data specifica
WITH ultimo_snapshot AS (
    SELECT saldo_finale, data_snapshot
    FROM `hotelops-suite.hotelops.f_saldi_banca_snapshot`
    WHERE societa_id = 'INTUR' AND banca_id = 'MPS'
    ORDER BY data_snapshot DESC
    LIMIT 1
),
movimenti_post AS (
    SELECT SUM(importo_netto) AS delta
    FROM `hotelops-suite.hotelops.f_banche_movimenti`
    WHERE societa_id = 'INTUR' AND banca_id = 'MPS'
      AND data_operazione > (SELECT data_snapshot FROM ultimo_snapshot)
)
SELECT
    s.saldo_finale + COALESCE(m.delta, 0) AS saldo_corrente
FROM ultimo_snapshot s, movimenti_post m
```

### Scostamento Budget (per Voce PF)
- **Definizione**: Differenza tra importo effettivo e previsione per voce del Piano Finanziario
- **Formula**: `importo_consuntivo - importo_budget`
- **Tabella**: `v_piano_finanziario_mensile`
- **Granularità**: Mensile per voce
- **Interpretazione**: Per ENTRATE positivo = incassato più del previsto (buono). Per USCITE positivo = speso più del previsto (cattivo).

### Cash Flow Netto Mensile
- **Definizione**: Totale entrate meno totale uscite dal conto in un mese
- **Formula**: dalla view `v_cashflow_mensile` → colonna `netto`
- **Tabella**: `v_cashflow_mensile` oppure calcolo diretto da `f_banche_movimenti`
- **Granularità**: Mensile

```sql
SELECT
    DATE_TRUNC(data_operazione, MONTH) AS mese,
    SUM(CASE WHEN importo_netto > 0 THEN importo_netto ELSE 0 END) AS entrate,
    SUM(CASE WHEN importo_netto < 0 THEN ABS(importo_netto) ELSE 0 END) AS uscite,
    SUM(importo_netto) AS netto
FROM `hotelops-suite.hotelops.f_banche_movimenti`
WHERE societa_id = 'ORTI'
GROUP BY 1
ORDER BY 1
```

### Proiezione Cash Forward (12 mesi) ⭐ v_previsione_cassa
- **Definizione**: Saldo banca proiettato mese per mese, partendo da un'ancora bancaria reale
- **Formula**: `saldo_ancora + cumsum(entrate - uscite_pf)` con window function
- **View**: `v_previsione_cassa`
- **Fonti**: `f_saldi_banca_snapshot` (ancora) + `v_piano_finanziario_consuntivo` (mesi chiusi) + `f_piano_finanziario_input` fonte=PIANO_FINANZIARIO (mesi futuri)
- **Colonne chiave**: `saldo_proiettato` (saldo rolling), `stato_liquidita` (OK/ATTENZIONE/PERICOLO), `uscite_scad` (fatture certe, informativa)
- **Scopo**: Identificare in anticipo mesi di crisi di liquidità — "ad agosto il saldo scende sotto zero → serve anticipare incassi o ritardare pagamenti"
- **Status**: ✅ LIVE — deployata marzo 2026

```sql
-- Mesi critici per ORTI
SELECT periodo, saldo_proiettato, stato_liquidita
FROM `hotelops-suite.hotelops.v_previsione_cassa`
WHERE societa_id = 'ORTI'
  AND stato_liquidita != 'OK'
ORDER BY anno, mese
```

### Liquidità Disponibile
- **Definizione**: Saldo proiettato + fidi residui non utilizzati
- **Formula**: `saldo_proiettato + SUM(importo_accordato - importo_utilizzato)`
- **Tabelle**: `v_previsione_cassa` + `f_affidamenti`
- **Scopo**: Un saldo negativo non è necessariamente PERICOLO se c'è fido disponibile
- **Status**: ✅ LIVE — INTUR SELLA: €50K fido di cassa. ORTI: nessun fido.
- **Nota**: Per ORTI il fido è zero, quindi liquidità disponibile = saldo proiettato. Per INTUR, saldo + €50K buffer.

```sql
-- Liquidità disponibile per società
SELECT
    p.societa_id,
    p.periodo,
    p.saldo_proiettato,
    COALESCE(SUM(a.importo_accordato - a.importo_utilizzato), 0) AS fido_residuo,
    p.saldo_proiettato + COALESCE(SUM(a.importo_accordato - a.importo_utilizzato), 0) AS liquidita_disponibile
FROM `hotelops-suite.hotelops.v_previsione_cassa` p
LEFT JOIN `hotelops-suite.hotelops.f_affidamenti` a
  ON p.societa_id = a.societa_id
  AND a.data_snapshot = (SELECT MAX(data_snapshot) FROM `hotelops-suite.hotelops.f_affidamenti` WHERE societa_id = p.societa_id)
GROUP BY p.societa_id, p.periodo, p.saldo_proiettato, p.anno, p.mese
ORDER BY p.anno, p.mese
```

### Copertura Scadenzario
- **Definizione**: Percentuale delle uscite stimate PF che sono "certe" (fatture già registrate in scadenzario)
- **Formula**: `SAFE_DIVIDE(uscite_scad, uscite_pf) * 100`
- **View**: `v_previsione_cassa`
- **Interpretazione**: 80% copertura → le stime PF sono affidabili. 20% → le stime sono molto più incerte

---

## Metriche del Controllo di Gestione (Competenza)

### Scostamento per Codice Conto
- **Definizione**: Delta tra consuntivo e budget per singolo codice conto CE
- **Formula**: `consuntivo - budget` (dalla view)
- **Tabella**: `v_budget_vs_consuntivo`
- **Granularità**: Mensile per cod_conto
- **Flag status**: OK, OVER_10PCT, UNDER_10PCT, SOLO_CONSUNTIVO, SOLO_BUDGET, IN_RANGE

```sql
-- Top 20 scostamenti YTD
SELECT cod_conto, descrizione, tipo_costo,
    SUM(budget) AS budget_ytd,
    SUM(consuntivo) AS consuntivo_ytd,
    SUM(delta) AS delta_ytd
FROM `hotelops-suite.hotelops.v_budget_vs_consuntivo`
WHERE societa_id = 'ORTI' AND anno = 2026
GROUP BY 1, 2, 3
ORDER BY ABS(SUM(delta)) DESC
LIMIT 20
```

### P&L per Categoria CE
- **Definizione**: Conto economico aggregato per categoria (Ricavi, Costi Fissi, Costi Variabili, Personale, Oneri Finanziari)
- **Formula**: Aggregazione da movimenti contabili per `categoria_ce`
- **Tabella**: `v_pl_movimenti`
- **Granularità**: Mensile per categoria

### Incassi per Canale
- **Definizione**: Entrate bancarie per metodo di pagamento (POS, bonifico, contante)
- **Tabella**: `v_incassi_per_canale`
- **Canali**: BONIFICO, CARTE, CONTANTI, ALTRO

---

## Metriche della Terza Dimensione (Impegno)

### Totale Partite Aperte
- **Definizione**: Somma delle fatture registrate ma non ancora pagate
- **Formula**: `SUM(importo_abs) WHERE data_snapshot = MAX(data_snapshot)`
- **Tabella**: `f_partite_aperte_fornitori`
- **⚠️ Nota**: `importo_residuo` è negativo (debito) — usare `importo_abs` per totali

```sql
-- Totale dovuto per scadenza
SELECT
    CASE
        WHEN data_scadenza < CURRENT_DATE() THEN 'SCADUTO'
        WHEN data_scadenza <= DATE_ADD(CURRENT_DATE(), INTERVAL 30 DAY) THEN 'PROSSIMI_30GG'
        WHEN data_scadenza <= DATE_ADD(CURRENT_DATE(), INTERVAL 60 DAY) THEN 'PROSSIMI_60GG'
        ELSE 'OLTRE_60GG'
    END AS bucket_scadenza,
    SUM(importo_abs) AS totale_dovuto,
    COUNT(*) AS n_partite
FROM `hotelops-suite.hotelops.f_partite_aperte_fornitori`
WHERE societa_id = 'ORTI'
  AND data_snapshot = (SELECT MAX(data_snapshot) FROM `hotelops-suite.hotelops.f_partite_aperte_fornitori` WHERE societa_id = 'ORTI')
  AND is_intercompany = FALSE
GROUP BY 1
ORDER BY 1
```

---

## Metriche Operative (Future)

### Costo per Coperto
- **Definizione**: Costo materie prime diviso numero coperti
- **Formula**: `SUM(f_consumi_economato.importo) / SUM(f_coperti.n_coperti)`
- **Stato**: Disponibile ma KPI non ancora formalizzato
- **Granularità**: Mensile per BU/tipo_pasto

### Costo per Camera (futuro)
- **Definizione**: Costi operativi hotel diviso notti occupate
- **Stato**: Richiede dati occupancy da HotelCube (non ancora disponibili)

---

## Budget: Fonti e Priorità

| Fonte | Scope | Granularità | Tabella |
|-------|-------|-------------|---------|
| `GASPAROTTO` | CE completo (112 conti, €4.08M ORTI) | Società, 1/12 flat mensile | `f_budget_mensile` |
| `MAPPATURA` | Costi fissi/variabili per BU | Per BU | `f_budget_mensile` |
| `INCIDENZA` | Personale per divisione | Per divisione | `f_budget_mensile` |
| `PIANO_FINANZIARIO` | Cash flow (29 voci, €5.7M entrate) | Per voce × mese | `f_piano_finanziario_input` |
| `BVA_2026` | Budget ricavi da Gasparotto | Per voce × mese | `f_piano_finanziario_input` |
| `SCADENZIARIO` | Rate mutui certe | Per scadenza | `f_piano_finanziario_input` |
| `CLI` / `NANOCLAW` | Aggiornamenti manuali forecast | Per voce × mese | `f_piano_finanziario_input` |

**⚠️ MAI mescolare fonti senza filtro esplicito** — ogni fonte ha scope e granularità diversi.
