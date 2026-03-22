# Dimensioni — Tabelle di Riferimento

Tabelle dimensionali del data model hotelops: piano dei conti, voci PF, categorie, periodi apertura.

---

## Tabelle Dimensionali

### d_voci_piano_finanziario ⭐ LA ROSETTA STONE
**Location**: `hotelops-suite.hotelops.d_voci_piano_finanziario`
**Descrizione**: Le 29 voci del Piano Finanziario con i pattern di mapping verso i codici conto Esolver e i tipi movimento bancari. È il layer di traduzione centrale tra la struttura PF e la contabilità analitica.
**Source CSV**: `bq/dimensioni/d_voci_piano_finanziario.csv`
**Row Count**: 29
**Update**: WRITE_TRUNCATE

| Colonna | Tipo | Descrizione | Note |
|---------|------|-------------|------|
| `voce_id` | STRING PK | Identificativo voce | Es: ENTRATE_HOTEL, USCITE_SALARI |
| `voce_label` | STRING | Label leggibile | Es: "Entrate Hotel", "Salari e stipendi" |
| `sezione` | STRING | ENTRATE o USCITE | |
| `categoria` | STRING | Categoria | Ricavi, Personale, Utenze, Finanziario, etc. |
| `societa_id` | STRING | Società | NULL = entrambe, ORTI = solo ORTI, INTUR = solo INTUR |
| `fonte` | STRING | Fonte dati per il consuntivo | ESOLVER, BANCHE, MANUALE |
| `cod_conto_pattern` | STRING | Pattern LIKE primario (senza punti) | Es: `4101%`, `6701%` |
| `cod_conto_pat2` | STRING | Pattern LIKE alternativo 2 | Nullable |
| `cod_conto_pat3` | STRING | Pattern LIKE alternativo 3 | Nullable |
| `banca_tipo_pat` | STRING | Pattern LIKE su tipo_movimento | Per fonte BANCHE |
| `ord` | INTEGER | Ordine di display | |
| `bu_filter` | STRING | Filtro BU | Es: LIDO per voci specifiche spiaggia |
| `categoria_ce` | STRING | Categoria CE | |
| `tipo_costo` | STRING | F, V, P, X, IP | |

**Voci ENTRATE** (11):

| voce_id | Fonte | Pattern | Società |
|---------|-------|---------|---------|
| ENTRATE_HOTEL | ESOLVER | 4101% | ORTI |
| ENTRATE_RESIDENCE | ESOLVER | 4102% | ORTI |
| ENTRATE_CVM | ESOLVER | 4103% | ORTI |
| ENTRATE_SUPERMERCATO | ESOLVER | 4104% | ORTI |
| ENTRATE_SPIAGGIA | ESOLVER | 4105% | INTUR |
| ENTRATE_SPIAGGIA_ORTI | ESOLVER | 4105% | ORTI |
| ENTRATE_AFFITTI_MINORI | ESOLVER | 4106% | NULL |
| ENTRATE_AFFITTI_INTUR | ESOLVER | 6511% | INTUR |
| ENTRATE_CAPARRE | BANCHE | %caparra% | ORTI |
| ENTRATE_CAPARRE_INTUR | BANCHE | %caparra% | INTUR |
| ENTRATE_RIENTRO_SOSPESI | BANCHE | %sospeso% | NULL |

**Voci USCITE** (18):

| voce_id | Fonte | Pattern | Società |
|---------|-------|---------|---------|
| USCITE_SALARI | ESOLVER | 6701% | NULL |
| USCITE_UTENZE | ESOLVER | 6305% | NULL |
| USCITE_MATERIE_PRIME | ESOLVER | 5709% | NULL |
| USCITE_TASSE | ESOLVER | 6590% | NULL |
| USCITE_MUTUI | BANCHE | %mutuo% | NULL |
| USCITE_MUTUI_SEMESTRALE | MANUALE | — | NULL |
| USCITE_SPESE_BANCARIE | ESOLVER | 6509% | NULL |
| USCITE_CONSULENZE | ESOLVER | 6310% | NULL |
| USCITE_GODIMENTO_BENI | ESOLVER | 6501% | NULL |
| USCITE_COMMISSIONI | ESOLVER | 5701% | NULL |
| USCITE_CANONI | ESOLVER | 6505% | NULL |
| USCITE_CANONE_PASSIVO | ESOLVER | 6511% | ORTI |
| USCITE_DEPOSITO_FITTO | MANUALE | — | NULL |
| USCITE_MARKETING | ESOLVER | 6315% | NULL |
| USCITE_SERVIZI_PRODUZIONE | ESOLVER | 5701% | NULL |
| USCITE_VARIE | ESOLVER | 6320% | NULL |
| USCITE_VARIE_EXT | ESOLVER | 6590% | NULL |

**⚠️ Pattern overlap**: USCITE_COMMISSIONI e USCITE_SERVIZI_PRODUZIONE condividono il prefisso `5701%` — il matching preciso dipende da pat2/pat3.

---

### d_piano_conti
**Location**: `hotelops-suite.hotelops.d_piano_conti`
**Descrizione**: Piano dei conti 2026 completo da Esolver. Include conti CE (conto economico) e SP (stato patrimoniale).
**Row Count**: ~2,103 (di cui ~160 CE)
**Update**: WRITE_TRUNCATE

| Colonna | Tipo | Descrizione | Note |
|---------|------|-------------|------|
| `codice_conto` | STRING PK | Codice conto **senza punti** | Es: 570913 |
| `descrizione` | STRING | Descrizione conto | |
| `tipo_conto` | STRING | C, F, B, S | Cliente, Fornitore, Banca, Cespite |
| `sezione` | STRING | CE o SP | Filtrare `WHERE sezione = 'CE'` per P&L |
| `partitario` | STRING | Tipo partitario | |
| `business_unit_id` | STRING | BU associata | |

**Per avere solo i conti CE**: `WHERE sezione = 'CE'`

---

### d_categorie_conti
**Location**: `hotelops-suite.hotelops.d_categorie_conti`
**Descrizione**: Mapping canonico codice conto → tipo costo + categoria CE. Usato dalle view per classificare i movimenti.
**Row Count**: 167
**Update**: WRITE_TRUNCATE

| Colonna | Tipo | Descrizione | Note |
|---------|------|-------------|------|
| `codice_conto` | STRING | Codice conto (senza punti) | |
| `tipo_costo` | STRING | F, V, P, X, IP | |
| `categoria_ce` | STRING | Categoria CE | |

---

### d_budget_costi_fissi
**Location**: `hotelops-suite.hotelops.d_budget_costi_fissi`
**Descrizione**: Budget annuale costi fissi con allocazione per BU. Snapshot dal file MAPPATURA.
**Row Count**: 43

| Colonna | Tipo | Descrizione |
|---------|------|-------------|
| `societa_id` | STRING | ORTI o INTUR |
| `codice_conto` | STRING | **Con punti** |
| `descrizione` | STRING | Descrizione |
| `tipo` | STRING | Tipo costo |
| `actuals_2025` | FLOAT | Consuntivo 2025 |
| `budget_2026` | FLOAT | Budget annuale 2026 |
| `hotel` | FLOAT | Quota HOTEL |
| `residence` | FLOAT | Quota RESIDENCE |
| `cvm` | FLOAT | Quota CVM |
| `spiaggia` | FLOAT | Quota LIDO |
| `hq` | FLOAT | Quota HQ |

---

### d_personale_mensile
**Location**: `hotelops-suite.hotelops.d_personale_mensile`
**Descrizione**: Costi personale mensili per divisione operativa. Da file Incidenza.
**Row Count**: 78

| Colonna | Tipo | Descrizione | Note |
|---------|------|-------------|------|
| `divisione` | STRING | MANAGEMENT, ROOM DIVISION, F&B, SPIAGGIA, AMM/ECO | |
| `anno` | INTEGER | Anno | |
| `mese` | STRING | Nome mese ("Gen", "Feb", ...) | ⚠️ Testo, non numero |
| `mese_num` | INTEGER | Mese numerico (1-12) | |
| `importo` | FLOAT | Costo mensile per divisione (€) | |

---

### d_periodi_apertura
**Location**: `hotelops-suite.hotelops.d_periodi_apertura`
**Descrizione**: Calendario apertura/chiusura stagionale per BU.
**Row Count**: 3

| Colonna | Tipo | Descrizione |
|---------|------|-------------|
| `societa_id` | STRING | ORTI o INTUR |
| `business_unit_id` | STRING | HOTEL, LIDO, RESIDENCE |
| `anno` | INTEGER | Anno |
| `data_apertura` | DATE | Data apertura stagione |
| `data_chiusura` | DATE | Data chiusura |
| `notti_apertura` | INTEGER | Notti totali aperte |
| `note` | STRING | Note |

---

## Pattern di Join Comuni

### Voci PF → Movimenti Contabili (LIKE pattern)
```sql
-- Il join centrale del data model
SELECT v.voce_id, v.voce_label, m.*
FROM `hotelops-suite.hotelops.f_movimenti_contabili` m
JOIN `hotelops-suite.hotelops.d_voci_piano_finanziario` v
  ON v.fonte = 'ESOLVER'
  AND (m.cod_conto LIKE v.cod_conto_pattern
       OR (v.cod_conto_pat2 IS NOT NULL AND m.cod_conto LIKE v.cod_conto_pat2)
       OR (v.cod_conto_pat3 IS NOT NULL AND m.cod_conto LIKE v.cod_conto_pat3))
  AND (v.societa_id IS NULL OR v.societa_id = m.societa_id)
```

### Budget → Piano dei Conti (normalizzazione punti)
```sql
SELECT b.*, p.descrizione, p.sezione
FROM `hotelops-suite.hotelops.f_budget_mensile` b
LEFT JOIN `hotelops-suite.hotelops.d_piano_conti` p
  ON REPLACE(b.codice_conto, '.', '') = p.codice_conto
```

### Movimenti → Categorie CE
```sql
SELECT m.*, c.tipo_costo, c.categoria_ce
FROM `hotelops-suite.hotelops.f_movimenti_contabili` m
LEFT JOIN `hotelops-suite.hotelops.d_categorie_conti` c
  ON m.cod_conto = c.codice_conto
```

### Costi personale: dimensione → budget
```sql
SELECT d.divisione, d.mese_num, d.importo
FROM `hotelops-suite.hotelops.d_personale_mensile` d
WHERE d.anno = 2026
ORDER BY d.divisione, d.mese_num
```
