# Contabilità — Tabelle Competenza

Dominio della contabilità generale: movimenti contabili da Esolver, budget per codice conto, P&L. Usato da Gasparotto (Controllo di Gestione) per il confronto budget vs consuntivo.

---

## Tabelle Chiave

### f_movimenti_contabili
**Location**: `hotelops-suite.hotelops.f_movimenti_contabili`
**Descrizione**: Prima nota completa da Esolver ERP. Ogni riga è un movimento contabile (dare o avere) su un codice conto.
**Primary Key**: `hash_riga` (MD5 di societa_id | id_documento | num_progr_riga)
**Row Count**: ~32K
**Periodo**: ORTI dal 2025, INTUR da dic 2024
**Update**: WRITE_APPEND con MD5 dedup

| Colonna | Tipo | Descrizione | Note |
|---------|------|-------------|------|
| `hash_riga` | STRING REQUIRED | Chiave dedup | |
| `societa_id` | STRING REQUIRED | ORTI o INTUR | |
| `id_documento` | INTEGER | ID documento Esolver | |
| `num_progr_riga` | INTEGER | N. riga nel documento | |
| `gruppo_doc` | STRING | Gruppo documento | FAT, PNC |
| `anno` | INTEGER | Anno registrazione | |
| `mese` | INTEGER | Mese registrazione (1-12) | |
| `data_registrazione` | DATE | Data registrazione contabile | |
| `sigla_doc` | STRING | Tipo documento | |
| `rif_registrazione` | STRING | Riferimento | Es: "PNC n 123" |
| `num_doc_originale` | STRING | N. documento originale | |
| `data_originale` | DATE | Data documento originale | |
| `tipo_documento` | STRING | Tipo documento | |
| `cod_conto` | STRING | Codice conto **SENZA PUNTI** | Es: 570913 (6-8 cifre) |
| `cod_partitario` | STRING | Codice partitario (cliente/fornitore) | |
| `rag_sociale` | STRING | Ragione sociale controparte | |
| `causale_contabile` | STRING | Causale | |
| `imp_dare` | FLOAT | Importo dare (€) | |
| `imp_avere` | FLOAT | Importo avere (€) | |
| `cod_divisione` | STRING | Divisione Esolver | |
| `file_sorgente` | STRING | File XLS sorgente | |
| `data_ingresso` | DATE | Data caricamento BQ | |

**⚠️ Nota critica**: `cod_conto` è SENZA punti. Per join con `f_budget_mensile.codice_conto` (che ha i punti), normalizzare con `REPLACE(codice_conto, '.', '')`.

**⚠️ Conti bancari assenti**: I conti 15xxxx non sono in questa tabella — usare `f_banche_movimenti` per le transazioni bancarie.

**Convenzione segno**:
- ENTRATE (ricavi): `imp_avere - imp_dare` → positivo
- USCITE (costi): `imp_dare - imp_avere` → positivo

---

### f_budget_mensile
**Location**: `hotelops-suite.hotelops.f_budget_mensile`
**Descrizione**: Budget mensile per codice conto. Tre fonti: GASPAROTTO (CE completo), MAPPATURA (per BU), INCIDENZA (personale).
**Row Count**: ~2217 (1380 GASPAROTTO + 837 MAPPATURA+INCIDENZA)
**Anno**: 2026
**Update**: DELETE-INSERT per anno + fonte

| Colonna | Tipo | Descrizione | Note |
|---------|------|-------------|------|
| `societa_id` | STRING REQUIRED | ORTI o INTUR | |
| `anno` | INTEGER REQUIRED | 2026 | |
| `mese` | INTEGER REQUIRED | Mese (1-12) | |
| `codice_conto` | STRING REQUIRED | Codice conto **CON PUNTI** | Es: 57.09.13 |
| `descrizione` | STRING | Descrizione conto | |
| `tipo_costo` | STRING | F, V, P, X | |
| `categoria_ce` | STRING | Categoria CE | |
| `business_unit_id` | STRING | HOTEL, RESIDENCE, CVM, LIDO, HQ | Solo per MAPPATURA/INCIDENZA |
| `importo` | FLOAT | Budget mensile (€) | Distribuzione flat 1/12 per GASPAROTTO |
| `fonte` | STRING | GASPAROTTO, MAPPATURA, INCIDENZA | |
| `data_caricamento` | TIMESTAMP | Timestamp caricamento | |

**⚠️ Budget flat 1/12**: GASPAROTTO divide l'annuale per 12. Per hotel stagionale è fuorviante — confronti mensili poco significativi.

---

### f_bilancino
**Location**: `hotelops-suite.hotelops.f_bilancino`
**Descrizione**: Bilancio di verifica periodico da Esolver. Solo leaf node (niente doppi conteggi da conti padre).
**Primary Key**: `hash_riga`
**Row Count**: ~110

| Colonna | Tipo | Descrizione | Note |
|---------|------|-------------|------|
| `hash_riga` | STRING REQUIRED | Chiave dedup | |
| `societa_id` | STRING REQUIRED | ORTI o INTUR | |
| `mese` | STRING REQUIRED | Periodo "YYYY-MM" | ⚠️ STRING, non INTEGER |
| `codice_conto` | STRING REQUIRED | Codice conto | |
| `descrizione` | STRING | Descrizione conto | |
| `tipo_conto` | STRING | Tipo conto | |
| `sezione` | STRING | CE o SP | |
| `dare` | FLOAT | Totale dare periodo | |
| `avere` | FLOAT | Totale avere periodo | |
| `saldo` | FLOAT | Saldo (dare - avere) | |

---

### f_consumi_economato
**Location**: `hotelops-suite.hotelops.f_consumi_economato`
**Descrizione**: Consumi materie prime per reparto/prodotto/categoria. Dettaglio granulare dei costi variabili.

| Colonna | Tipo | Descrizione | Note |
|---------|------|-------------|------|
| `hash_riga` | STRING REQUIRED | Chiave dedup | |
| `societa_id` | STRING REQUIRED | ORTI o INTUR | |
| `anno` | INTEGER REQUIRED | Anno | |
| `mese` | INTEGER REQUIRED | Mese | |
| `business_unit_id` | STRING | BU | |
| `reparto_id` | STRING | Reparto (cucina, bar, etc.) | |
| `reparto_raw` | STRING | Nome reparto grezzo | |
| `is_evento` | BOOLEAN | Se è per evento speciale | |
| `evento_nome` | STRING | Nome evento | |
| `codice_prodotto` | STRING | Codice prodotto | |
| `descrizione` | STRING | Descrizione | |
| `classe` | STRING | Classe prodotto | |
| `categoria_prodotto` | STRING | Categoria | |
| `sottocategoria` | STRING | Sottocategoria | |
| `quantita` | FLOAT | Quantità consumata | |
| `importo` | FLOAT | Costo (€) | |

---

### f_coperti_giornalieri
**Location**: `hotelops-suite.hotelops.f_coperti`
**Descrizione**: Numero coperti pasto giornalieri per BU e tipo ospite.
**Partizionata su**: `data_servizio` (MONTH)

| Colonna | Tipo | Descrizione | Note |
|---------|------|-------------|------|
| `societa_id` | STRING REQUIRED | ORTI o INTUR | |
| `data_servizio` | DATE REQUIRED | Data del servizio | Usare sempre come filtro! |
| `tipo_pasto` | STRING REQUIRED | colazione, pranzo, cena | |
| `tipo_ospite` | STRING REQUIRED | Tipo ospite | |
| `business_unit_id` | STRING | BU | |
| `n_coperti` | INT64 REQUIRED | Numero coperti | |

---

## View

### v_budget_vs_consuntivo ⭐ LA VIEW PER GASPAROTTO
**Location**: `hotelops-suite.hotelops.v_budget_vs_consuntivo`
**Descrizione**: FULL OUTER JOIN tra budget e consuntivo per codice conto × mese. Include flag di status.

| Colonna | Descrizione |
|---------|-------------|
| `societa_id` | ORTI o INTUR |
| `anno`, `mese` | Periodo |
| `cod_conto` | Codice conto (senza punti) |
| `codice_conto_display` | Con punti (57.09.13) |
| `descrizione` | Da d_piano_conti |
| `tipo_costo` | F, V, P, X |
| `categoria_ce` | Categoria CE |
| `business_unit_id` | BU (se da MAPPATURA) |
| `budget` | Importo budget mensile |
| `consuntivo` | Importo consuntivo mensile |
| `n_movimenti` | Conteggio movimenti |
| `delta` | consuntivo - budget |
| `delta_pct` | Delta percentuale |
| `status` | OK, OVER_10PCT, UNDER_10PCT, SOLO_CONSUNTIVO, SOLO_BUDGET, IN_RANGE |

### v_pl_movimenti
**Location**: `hotelops-suite.hotelops.v_pl_movimenti`
**Descrizione**: P&L aggregato per categoria CE. Ricavi - Costi per tipo.

| Colonna | Descrizione |
|---------|-------------|
| `societa_id`, `anno`, `mese`, `periodo` | Dimensioni |
| `categoria` | RICAVO, COSTO_FISSO, COSTO_VAR, PERSONALE, EXTRA_EBITDA, ALTRO |
| `categoria_ce` | Categoria CE dettagliata |
| `business_unit_id` | BU |
| `importo` | Importo netto |
| `ricavi` | Totale ricavi |
| `costi_totali` | Totale costi |
| `n_movimenti` | Conteggio |

---

## Query Comuni

### Dettaglio movimenti per un codice conto
```sql
SELECT
    data_registrazione,
    rif_registrazione,
    rag_sociale,
    causale_contabile,
    imp_dare,
    imp_avere,
    imp_dare - imp_avere AS netto
FROM `hotelops-suite.hotelops.f_movimenti_contabili`
WHERE societa_id = 'ORTI'
  AND cod_conto = '570913'
  AND anno = 2026
ORDER BY data_registrazione
```

### P&L mensile sintetico
```sql
SELECT
    mese,
    SUM(CASE WHEN categoria = 'RICAVO' THEN importo ELSE 0 END) AS ricavi,
    SUM(CASE WHEN categoria IN ('COSTO_FISSO', 'COSTO_VAR') THEN importo ELSE 0 END) AS costi_operativi,
    SUM(CASE WHEN categoria = 'PERSONALE' THEN importo ELSE 0 END) AS personale,
    SUM(ricavi) - SUM(costi_totali) AS margine
FROM `hotelops-suite.hotelops.v_pl_movimenti`
WHERE societa_id = 'ORTI' AND anno = 2026
GROUP BY mese
ORDER BY mese
```

### Confronto fonti budget per stesso conto
```sql
SELECT
    REPLACE(codice_conto, '.', '') AS cod,
    descrizione,
    fonte,
    SUM(importo) AS totale_annuo
FROM `hotelops-suite.hotelops.f_budget_mensile`
WHERE societa_id = 'ORTI' AND anno = 2026
GROUP BY 1, 2, 3
ORDER BY 1, 3
```
