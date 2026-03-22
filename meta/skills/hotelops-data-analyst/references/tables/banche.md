# Banche — Tabelle Transazioni Bancarie

Dominio bancario: transazioni da estratti conto, cashflow, incassi per canale. Fonte primaria per la dimensione CASSA.

---

## Tabelle Chiave

### f_banche_movimenti
**Location**: `hotelops-suite.hotelops.f_banche_movimenti`
**Descrizione**: Transazioni bancarie da estratti conto CSV (home banking). Ogni riga è un movimento su un conto bancario.
**Primary Key**: `hash_riga` (MD5)
**Row Count**: ~3,745
**Periodo**: 2025-01-01 → 2026-03-12
**Update**: WRITE_APPEND con MD5 dedup

| Colonna | Tipo | Descrizione | Note |
|---------|------|-------------|------|
| `hash_riga` | STRING | Chiave dedup | |
| `societa_id` | STRING | ORTI o INTUR | |
| `banca_id` | STRING | MPS, MPS_KROSS, SELLA, INTESA, BCP | |
| `data_operazione` | DATE | Data transazione | |
| `data_valuta` | DATE | Data valuta | |
| `descrizione` | STRING | Descrizione movimento | Testo libero dalla banca |
| `importo_debito` | FLOAT | Uscita (positivo) | |
| `importo_credito` | FLOAT | Entrata (positivo) | |
| `importo_netto` | FLOAT | credito - debito | **Positivo = entrata, negativo = uscita** |
| `tipo_movimento` | STRING | Tipo codificato | Critico per mapping voce PF |
| `categoria_normalizzata` | STRING | Categoria normalizzata | |
| `sottocategoria_normalizzata` | STRING | Sottocategoria | |
| `codice_identificativo_banca` | STRING | CRO / riferimento bancario | |
| `business_unit_id` | STRING | BU | |
| `funzione_id` | STRING | Funzione | |
| `location_id` | STRING | Location | |
| `oggetto_id` | STRING | Oggetto | |
| `etichette` | STRING | Tag manuali | |
| `note` | STRING | Note | |
| `file_sorgente` | STRING | File CSV origine | |
| `riga_sorgente` | INTEGER | Riga nel file | |
| `data_ingresso` | DATE | Data caricamento BQ | |

**Valori comuni `tipo_movimento`**:
- `(09) INCASSO TRAMITE P.O.S.` → POS / Carte
- `(48) BONIFICO A VOSTRO FAVORE` → Bonifico in entrata
- `(26) VOSTRA DISPOSIZIONE A FAVORE DI` → Bonifico in uscita
- `(78) VERSAMENTO CONTANTE` → Contante
- `Commissioni` → Spese bancarie
- `Bonifico` → Generico

---

### f_accodamenti
**Location**: `hotelops-suite.hotelops.f_accodamenti`
**Descrizione**: Vendite da HotelCube PMS registrate in Esolver: corrispettivi, caparre, fatture attive. Ponte tra PMS e contabilità.
**Row Count**: ~63
**Periodo**: gen 2026

| Colonna | Tipo | Descrizione | Note |
|---------|------|-------------|------|
| `id_registrazione` | STRING | ID registrazione | |
| `societa_id` | STRING | ORTI o INTUR | |
| `banca_id` | STRING | Banca | |
| `data_registrazione` | DATE | Data registrazione | |
| `descrizione` | STRING | Descrizione | |
| `importo` | FLOAT | Importo netto | |
| `importo_dare` | FLOAT | Dare | |
| `importo_avere` | FLOAT | Avere | |
| `riferimento_registrazione` | STRING | Riferimento (es. "PNC n X") | |

---

### f_partite_aperte_fornitori
**Location**: `hotelops-suite.hotelops.f_partite_aperte_fornitori`
**Descrizione**: Snapshot partite aperte fornitori da Esolver. Terza dimensione (IMPEGNO): fatture registrate non ancora pagate.
**Update**: DELETE-INSERT per societa + data_snapshot

| Colonna | Tipo | Descrizione | Note |
|---------|------|-------------|------|
| `societa_id` | STRING REQUIRED | ORTI o INTUR | |
| `data_snapshot` | DATE REQUIRED | Data dello snapshot | |
| `codice_fornitore` | INTEGER REQUIRED | Codice fornitore Esolver | |
| `nome_fornitore` | STRING | Ragione sociale | |
| `tipo_documento` | STRING | FT (fattura), NC (nota credito), AFT | |
| `numero_documento` | STRING | N. documento | |
| `data_documento` | DATE | Data fattura | |
| `data_scadenza` | DATE | Data scadenza pagamento | **Chiave per proiezione cash-out** |
| `importo_residuo` | FLOAT | Saldo residuo | **Negativo = debito verso fornitore** |
| `importo_abs` | FLOAT | Valore assoluto | Usare per aggregazioni |
| `codice_pagamento` | STRING | 04=Bonifico, 03=SDD, 10=Carta | |
| `metodo_pagamento` | STRING | Bonifico SEPA, SDD, Carta di credito | |
| `is_intercompany` | BOOLEAN | Flag intercompany | TRUE per PANORAMA COMPANY / INTUR |
| `file_sorgente` | STRING | File origine | |

**⚠️ Usare sempre l'ultimo snapshot**:
```sql
WHERE data_snapshot = (
    SELECT MAX(data_snapshot)
    FROM `hotelops-suite.hotelops.f_partite_aperte_fornitori`
    WHERE societa_id = 'ORTI'
)
```

---

### f_saldi_banca_snapshot ✅ LIVE
**Location**: `hotelops-suite.hotelops.f_saldi_banca_snapshot`
**Descrizione**: Saldi bancari storici (ancora). Usato da `v_previsione_cassa` come punto di partenza per la proiezione rolling.
**Status**: ✅ **LIVE** — prima ancora: ORTI MPS €134,647 al 28/02/2026.
**Update**: DELETE-INSERT per societa + banca + data_snapshot

| Colonna | Tipo | Descrizione | Note |
|---------|------|-------------|------|
| `societa_id` | STRING | ORTI o INTUR | |
| `banca_id` | STRING | MPS, MPS_KROSS, SELLA, INTESA, BCP | |
| `data_snapshot` | DATE | Data dello snapshot saldo | |
| `saldo_finale` | FLOAT | Saldo finale (€) | L'ancora per v_previsione_cassa |
| `fonte` | STRING | SCHEDA_CONTABILE, BANCA_EXCEL | Primary source is SCHEDA_CONTABILE |
| `file_sorgente` | STRING | File CSV/Excel origine | |
| `data_caricamento` | TIMESTAMP | Timestamp caricamento | |

**⚠️ Naming convention**: Usare esattamente `societa_id`, `banca_id`, `data_snapshot`, `saldo_finale` — il codebase (`cli.py`) si aspetta queste colonne.

---

### f_affidamenti ✅ LIVE
**Location**: `hotelops-suite.hotelops.f_affidamenti`
**Descrizione**: Linee di credito e fidi bancari. Necessario per calcolare la liquidità disponibile totale = saldo_proiettato + fido_residuo.
**Status**: ✅ **LIVE** — snapshot 2026-03-20.
**Dati reali**: INTUR SELLA €50,000 fido di cassa. ORTI: nessun fido.

| Colonna | Tipo | Descrizione | Note |
|---------|------|-------------|------|
| `societa_id` | STRING REQUIRED | ORTI o INTUR | |
| `banca_id` | STRING REQUIRED | MPS, MPS_KROSS, SELLA, INTESA, BCP | |
| `tipo_affidamento` | STRING | Tipo | Fido di cassa, SBF, Anticipo fatture, Castelletto |
| `importo_accordato` | FLOAT | Limite accordato (€) | Es: €200,000 |
| `importo_utilizzato` | FLOAT | Quota già utilizzata (€) | |
| `data_snapshot` | DATE | Data dello snapshot | |
| `data_scadenza_fido` | DATE | Scadenza della linea | |
| `note` | STRING | Note | |

**Metriche derivabili**:
- Fido residuo: `importo_accordato - importo_utilizzato`
- Liquidità disponibile: `saldo_proiettato + SUM(fido_residuo)`
- Utilizzo fido: `SAFE_DIVIDE(importo_utilizzato, importo_accordato) * 100`

---

## View

### v_cashflow_mensile
**Location**: `hotelops-suite.hotelops.v_cashflow_mensile`
**Descrizione**: Cashflow mensile aggregato dalle transazioni bancarie.

| Colonna | Descrizione |
|---------|-------------|
| `mese` | DATE troncata al mese |
| `societa_id` | ORTI o INTUR |
| `entrate` | Somma importi positivi |
| `uscite` | Somma importi negativi (in valore assoluto) |
| `netto` | entrate - uscite |
| `netto_cumulativo` | Running sum del netto |

### v_incassi_per_canale
**Location**: `hotelops-suite.hotelops.v_incassi_per_canale`
**Descrizione**: Entrate per metodo di pagamento.

| Colonna | Descrizione |
|---------|-------------|
| `mese` | "YYYY-MM" |
| `societa_id` | ORTI o INTUR |
| `banca_id` | Banca |
| `canale` | BONIFICO, CARTE, CONTANTI, ALTRO |
| `importo_credito` | Importo entrata |

**Logica canale**:
- BONIFICO: tipo_movimento contiene '48' o 'BONIF'
- CARTE: tipo_movimento contiene '09' (POS)
- CONTANTI: tipo_movimento contiene '78'
- ALTRO: tutto il resto

---

## Query Comuni

### Trend entrate/uscite mensili
```sql
SELECT
    mese,
    entrate,
    uscite,
    netto,
    netto_cumulativo
FROM `hotelops-suite.hotelops.v_cashflow_mensile`
WHERE societa_id = 'ORTI'
ORDER BY mese
```

### Top fornitori per importo partite aperte
```sql
SELECT
    nome_fornitore,
    COUNT(*) AS n_fatture,
    SUM(importo_abs) AS totale_dovuto,
    MIN(data_scadenza) AS scadenza_piu_vicina,
    is_intercompany
FROM `hotelops-suite.hotelops.f_partite_aperte_fornitori`
WHERE societa_id = 'ORTI'
  AND data_snapshot = (SELECT MAX(data_snapshot) FROM `hotelops-suite.hotelops.f_partite_aperte_fornitori` WHERE societa_id = 'ORTI')
GROUP BY nome_fornitore, is_intercompany
ORDER BY SUM(importo_abs) DESC
LIMIT 20
```

### Riconciliazione banca vs contabilità (un mese)
```sql
WITH banca AS (
    SELECT SUM(importo_netto) AS totale_banca
    FROM `hotelops-suite.hotelops.f_banche_movimenti`
    WHERE societa_id = 'ORTI' AND banca_id = 'MPS'
      AND EXTRACT(YEAR FROM data_operazione) = 2026
      AND EXTRACT(MONTH FROM data_operazione) = 1
),
contabilita AS (
    SELECT SUM(imp_avere - imp_dare) AS totale_contabilita
    FROM `hotelops-suite.hotelops.f_movimenti_contabili`
    WHERE societa_id = 'ORTI'
      AND cod_conto LIKE '15%'  -- conti banca
      AND anno = 2026 AND mese = 1
)
SELECT
    b.totale_banca,
    c.totale_contabilita,
    b.totale_banca - c.totale_contabilita AS differenza
FROM banca b, contabilita c
```

### Mix incassi per canale (mensile)
```sql
SELECT
    mese,
    canale,
    SUM(importo_credito) AS totale,
    SAFE_DIVIDE(
        SUM(importo_credito),
        SUM(SUM(importo_credito)) OVER (PARTITION BY mese)
    ) * 100 AS pct
FROM `hotelops-suite.hotelops.v_incassi_per_canale`
WHERE societa_id = 'ORTI'
GROUP BY mese, canale
ORDER BY mese, totale DESC
```
