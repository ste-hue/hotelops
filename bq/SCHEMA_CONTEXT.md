# hotelops-suite · BigQuery Schema Context

**Progetto**: `hotelops-suite`
**Dataset**: `hotelops`
**Aggiornato**: 2026-03-19
**Entità operative**: ORTI (hotel operations), INTUR (holding finanziaria)
**Banche attive**: ORTI → MPS, MPS_KROSS · INTUR → MPS, SELLA, INTESA

---

## Tabelle Fatto (f_*)

### `f_movimenti_contabili`
**Fonte**: Esolver ERP — Lista Movimenti Contabili (export manuale XLS)
**Righe**: ~31.821 · **Periodo**: 2024-12-03 → 2026-03-18
**Dedup key**: MD5(societa_id | id_documento | num_progr_riga)
**Pattern**: WRITE_APPEND con hash dedup

| Colonna | Tipo | Note |
|---|---|---|
| `hash_riga` | STRING REQUIRED | MD5 dedup key |
| `societa_id` | STRING REQUIRED | ORTI \| INTUR |
| `id_documento` | INTEGER | ID documento Esolver |
| `num_progr_riga` | INTEGER | Riga progressiva nel documento |
| `gruppo_doc` | STRING | Gruppo documento (es. FAT, PNC) |
| `anno` | INTEGER | Anno registrazione |
| `mese` | INTEGER | Mese registrazione (1-12) |
| `data_registrazione` | DATE | Data registrazione contabile |
| `sigla_doc` | STRING | Sigla tipo documento |
| `rif_registrazione` | STRING | Riferimento (es. "PNC n 123") |
| `num_doc_originale` | STRING | Numero documento originale |
| `data_originale` | DATE | Data documento originale |
| `tipo_documento` | STRING | Tipo documento |
| `cod_conto` | STRING | Codice conto **senza punti** (es. `479101`, `670101`) |
| `cod_partitario` | STRING | Codice partitario (cliente/fornitore) |
| `rag_sociale` | STRING | Ragione sociale controparte |
| `causale_contabile` | STRING | Causale (es. "Fattura fornitore") |
| `imp_dare` | FLOAT | Importo Dare (€) |
| `imp_avere` | FLOAT | Importo Avere (€) |
| `cod_divisione` | STRING | Codice divisione/BU Esolver |
| `file_sorgente` | STRING | Nome file XLS di origine |
| `data_ingresso` | DATE | Data caricamento in BQ |

**Note importanti**:
- `cod_conto` è sempre **senza punti**: `57.09.13` → `570913`
- Formato 6 cifre = 3 livelli, 8 cifre = 4 livelli
- Solo conti **foglia** hanno movimenti (nessun double-counting su padri)
- Conti banca (15xxxx) NON presenti — sono in `f_banche_movimenti`

---

### `f_banche_movimenti`
**Fonte**: Estratti conto bancari (CSV export da home banking)
**Righe**: ~3.745 · **Periodo**: 2025-01-01 → 2026-03-12
**Dedup key**: `hash_riga` = MD5 su chiave movimento banca
**Banche**: ORTI/MPS, ORTI/MPS_KROSS, INTUR/MPS, INTUR/SELLA, INTUR/INTESA

| Colonna | Tipo | Note |
|---|---|---|
| `hash_riga` | STRING | Dedup key |
| `societa_id` | STRING | ORTI \| INTUR |
| `business_unit_id` | STRING | BU di pertinenza |
| `funzione_id` | STRING | Funzione operativa |
| `location_id` | STRING | Sede |
| `oggetto_id` | STRING | Oggetto transazione |
| `banca_id` | STRING | MPS \| MPS_KROSS \| SELLA \| INTESA |
| `data_operazione` | DATE | Data operazione bancaria |
| `data_valuta` | DATE | Data valuta |
| `descrizione` | STRING | Descrizione movimento |
| `divisa` | STRING | Valuta (default EUR) |
| `importo_debito` | FLOAT | Importo uscita (positivo) |
| `importo_credito` | FLOAT | Importo entrata (positivo) |
| `importo_netto` | FLOAT | credito - debito (positivo=entrata, negativo=uscita) |
| `categoria_raw` | STRING | Categoria originale banca |
| `sottocategoria_raw` | STRING | Sottocategoria originale |
| `categoria_normalizzata` | STRING | Categoria normalizzata |
| `sottocategoria_normalizzata` | STRING | Sottocategoria normalizzata |
| `tipo_movimento` | STRING | Tipo movimento (es. "BONIFICO A VOSTRO FAVORE", "INCASSO TRAMITE P.O.S.") |
| `codice_identificativo_banca` | STRING | CRO / riferimento banca |
| `etichette` | STRING | Tag manuali |
| `note` | STRING | Note |
| `data_ingresso` | DATE | Data caricamento BQ |
| `file_sorgente` | STRING | File origine |
| `riga_sorgente` | INTEGER | Riga nel file originale |

**Tipi movimento frequenti**: (09) POS, (26) Disposizione, (48) Bonifico in entrata, (78) Versamento contante, Commissioni, Bonifico

---

### `f_budget_mensile`
**Fonte**: MAPPATURA DEI COSTI_v_2.xlsx (fogli budget_F_ORTI, budget_F_INTUR) + Incidenza_costi_personale.xlsx
**Righe**: 837 · **Anno**: 2026
**Pattern**: DELETE-INSERT per anno + fonte (idempotente)
**Pipeline**: `pipelines/amministrativa/ingest_budget_costi.py`

| Colonna | Tipo | Note |
|---|---|---|
| `societa_id` | STRING REQUIRED | ORTI \| INTUR |
| `anno` | INTEGER REQUIRED | 2026 |
| `mese` | INTEGER REQUIRED | 1-12 |
| `codice_conto` | STRING REQUIRED | Codice conto **con punti** (es. `57.09.13`) |
| `descrizione` | STRING | Descrizione voce di costo |
| `tipo_costo` | STRING | F=Fisso, V=Variabile, P=Personale, X=Oneri finanziari |
| `categoria_ce` | STRING | Categoria Conto Economico |
| `business_unit_id` | STRING | HOTEL \| RESIDENCE \| CVM \| LIDO \| HQ |
| `importo` | FLOAT | Importo mensile (€), distribuzione 1/12 uniforme |
| `fonte` | STRING | MAPPATURA \| INCIDENZA |
| `data_caricamento` | TIMESTAMP | Timestamp caricamento |

**Copertura attuale** (anno 2026):
- ORTI: 1.543.295 €/anno (Costi fissi 368K + Acquisti 15K + Personale 1.158K + Oneri fin. 1.2K)
- INTUR: 305.601 €/anno (Costi fissi 238K + Personale 68K)

**Nota**: `codice_conto` usa formato **con punti** (diverso da `f_movimenti_contabili`). La view `v_piano_finanziario_mensile` normalizza via `REPLACE(codice_conto, '.', '')` prima del LIKE.

---

### `f_piano_finanziario_input`
**Fonte**: Input manuale per voci prospettiche (budget ricavi, scadenziario mutui)
**Righe**: 142 · **Anni**: 2026-2027
**Dedup key**: MD5(societa_id | voce_id | anno | mese | fonte)
**Pattern**: WRITE_APPEND con hash dedup

| Colonna | Tipo | Note |
|---|---|---|
| `hash_riga` | STRING | Dedup key |
| `societa_id` | STRING REQUIRED | ORTI \| INTUR |
| `voce_id` | STRING REQUIRED | FK → `d_voci_piano_finanziario.voce_id` |
| `anno` | INTEGER REQUIRED | Anno |
| `mese` | INTEGER REQUIRED | Mese (1-12) |
| `importo` | FLOAT | Importo (€) |
| `fonte` | STRING | SCADENZIARIO \| BVA_2026 \| (altro) |
| `note` | STRING | Note libere |
| `file_sorgente` | STRING | File di origine |
| `data_caricamento` | TIMESTAMP | Timestamp caricamento |

**Fonti attive**:
- `SCADENZIARIO`: rate mutui ORTI + INTUR (voce USCITE_MUTUI, USCITE_MUTUI_SEMESTRALE), anni 2026-2027
- `BVA_2026`: ricavi budget 2026 (ENTRATE_HOTEL, ENTRATE_CVM, ENTRATE_SPIAGGIA_ORTI, ENTRATE_SPIAGGIA, ENTRATE_AFFITTI_INTUR)

**Voci NON ancora mappate** (da aggiungere al dizionario):
- ORTI Ricavi Angelina (ristorante)
- ORTI Ricavi Affitti a terzi
- INTUR Ricavi Hotel
- INTUR Ricavi CVM

---

### `f_bilancino`
**Fonte**: Bilancio di verifica Esolver (export periodico)
**Righe**: 110

| Colonna | Tipo | Note |
|---|---|---|
| `hash_riga` | STRING REQUIRED | Dedup key |
| `societa_id` | STRING REQUIRED | ORTI \| INTUR |
| `mese` | STRING REQUIRED | Formato "YYYY-MM" |
| `codice_conto` | STRING REQUIRED | Codice conto |
| `descrizione` | STRING | Descrizione conto |
| `tipo_conto` | STRING | Tipo conto |
| `sezione` | STRING | Sezione CE/SP |
| `dare` | FLOAT | Totale Dare periodo |
| `avere` | FLOAT | Totale Avere periodo |
| `saldo` | FLOAT | Saldo (Dare - Avere) |
| `business_unit_id` | STRING | BU |
| `categoria` | STRING | Categoria |
| `file_sorgente` | STRING | File origine |
| `data_ingresso` | STRING | Data ingresso |

---

### `f_accodamenti`
**Fonte**: Esolver accodamenti (movimenti banca lato Esolver)
**Righe**: 63 · **Periodo**: 2026-01-01 → 2026-01-22

| Colonna | Tipo | Note |
|---|---|---|
| `id_registrazione` | STRING | ID registrazione |
| `societa_id` | STRING | ORTI \| INTUR |
| `business_unit_id` | STRING | BU |
| `funzione_id` | STRING | Funzione |
| `location_id` | STRING | Sede |
| `oggetto_id` | STRING | Oggetto |
| `banca_id` | STRING | Banca |
| `data_registrazione` | DATE | Data registrazione |
| `descrizione` | STRING | Descrizione |
| `importo` | FLOAT | Importo netto |
| `importo_dare` | FLOAT | Importo Dare |
| `importo_avere` | FLOAT | Importo Avere |
| `divisa` | STRING | Valuta |
| `riferimento_registrazione` | STRING | Rif. (es. "PNC n X") |
| `documento` | STRING | Documento |
| `riferimenti_iva` | STRING | Riferimenti IVA |
| `centro_imputazione` | STRING | Centro di costo |
| `data_ingresso` | DATE | Data caricamento |
| `file_sorgente` | STRING | File origine |
| `riga_sorgente` | INTEGER | Riga nel file |
| `hash_riga` | STRING | Dedup key |

---

### `f_mastrino_consolidato`
**Fonte**: `Costi Ricavi 2025-2026 Budget.xlsx`, foglio `mastrino_consolidato`
**Righe**: 901
*(NB: questo non è il mastrino banca Esolver — è il mastrino di gestione consolidata)*

---

## Tabelle Dimensione (d_*)

### `d_voci_piano_finanziario`
**Fonte**: `bq/dimensioni/d_voci_piano_finanziario.csv` (manuale, WRITE_TRUNCATE)
**Righe**: 29
**Ruolo**: dizionario centrale che mappa voci piano finanziario ↔ codici conto Esolver ↔ movimenti bancari

| Colonna | Tipo | Note |
|---|---|---|
| `voce_id` | STRING | PK — identificatore voce (es. `ENTRATE_HOTEL`, `USCITE_SALARI`) |
| `voce_label` | STRING | Label leggibile |
| `sezione` | STRING | ENTRATE \| USCITE |
| `categoria` | STRING | Categoria (Ricavi, Personale, Utenze, Finanziario...) |
| `societa_id` | STRING | NULL = entrambe, ORTI \| INTUR = specifica |
| `fonte` | STRING | ESOLVER \| BANCHE \| MANUALE |
| `cod_conto_pattern` | STRING | Prefisso conto per LIKE match (senza punti) |
| `cod_conto_pat2` | STRING | Pattern alternativo 2 |
| `cod_conto_pat3` | STRING | Pattern alternativo 3 |
| `banca_tipo_pat` | STRING | Pattern LIKE su `tipo_movimento` in `f_banche_movimenti` |
| `ord` | INTEGER | Ordine di visualizzazione |
| `bu_filter` | STRING | Filtra per BU specifica (es. LIDO) |
| `categoria_ce` | STRING | Categoria Conto Economico |
| `tipo_costo` | STRING | F \| V \| P \| X \| IP |

**Come funziona il match**:
- `fonte=ESOLVER` → join su `f_movimenti_contabili.cod_conto LIKE CONCAT(cod_conto_pattern, '%')`
- `fonte=BANCHE` → join su `UPPER(f_banche_movimenti.tipo_movimento) LIKE CONCAT('%', banca_tipo_pat, '%')`
- `fonte=MANUALE` → `f_piano_finanziario_input` usa direttamente `voce_id`

**Voci attive per sezione**:
- ENTRATE (11 voci): ENTRATE_HOTEL, ENTRATE_RESIDENCE, ENTRATE_CVM, ENTRATE_SPIAGGIA_ORTI, ENTRATE_SPIAGGIA, ENTRATE_AFFITTI_INTUR, ENTRATE_AFFITTI_MINORI, ENTRATE_SUPERMERCATO, ENTRATE_CAPARRE, ENTRATE_CAPARRE_INTUR, ENTRATE_RIENTRO_SOSPESI
- USCITE (18 voci): USCITE_SALARI, USCITE_UTENZE_ENERGIA/ACQUA/GAS/TEL/CONNETTIVITA, USCITE_MATERIE_PRIME, USCITE_TASSE, USCITE_MUTUI, USCITE_MUTUI_SEMESTRALE, USCITE_SPESE_BANCARIE, USCITE_CONSULENZE, USCITE_GODIMENTO_BENI, USCITE_COMMISSIONI, USCITE_CANONI, USCITE_CANONE_PASSIVO, USCITE_VARIE, USCITE_VARIE_EXT

---

### `d_piano_conti`
**Fonte**: Piano dei conti Esolver
**Righe**: 2.103

| Colonna | Tipo | Note |
|---|---|---|
| `codice_conto` | STRING REQUIRED | PK — codice conto (senza punti, 6-8 cifre) |
| `descrizione` | STRING | Descrizione conto |
| `tipo_conto` | STRING | **C**=Cliente, **F**=Fornitore, **B**=Banca, **S**=Cespite |
| `sezione` | STRING | CE (Conto Economico) \| SP (Stato Patrimoniale) |
| `partitario` | STRING | Tipo partitario |
| `business_unit_id` | STRING | BU associata |

---

### `d_budget_costi_fissi`
**Fonte**: MAPPATURA DEI COSTI_v_2.xlsx
**Righe**: 43 — snapshot annuale (non mensile) dei costi fissi per BU

| Colonna | Tipo | Note |
|---|---|---|
| `societa_id` | STRING REQUIRED | ORTI \| INTUR |
| `codice_conto` | STRING REQUIRED | Codice conto con punti |
| `descrizione` | STRING | Descrizione voce |
| `tipo` | STRING | Tipo costo |
| `actuals_2025` | FLOAT | Consuntivo 2025 |
| `budget_2026` | FLOAT | Budget 2026 annuale |
| `hotel` | FLOAT | Quota BU HOTEL |
| `residence` | FLOAT | Quota BU RESIDENCE |
| `cvm` | FLOAT | Quota BU CVM |
| `spiaggia` | FLOAT | Quota BU LIDO |
| `hq` | FLOAT | Quota BU HQ |

---

### `d_personale_mensile`
**Fonte**: Incidenza_costi_personale.xlsx
**Righe**: 78

| Colonna | Tipo | Note |
|---|---|---|
| `divisione` | STRING REQUIRED | MANAGEMENT, ROOM DIVISION, F&B, SPIAGGIA, AMM/ECO... |
| `anno` | INTEGER REQUIRED | Anno |
| `mese` | STRING REQUIRED | "Gen", "Feb"... |
| `mese_num` | INTEGER | Mese numerico 1-12 |
| `importo` | FLOAT | Costo personale mensile per divisione (€) |

---

### `d_categorie_conti`
**Fonte**: `Costi Ricavi 2025-2026 Budget.xlsx`, foglio `CATEGORIE`
**Righe**: 167 — mapping conti → categorie gestionali

---

### `d_periodi_apertura`
**Fonte**: Configurazione manuale
**Righe**: 3 — calendario apertura per BU e anno

| Colonna | Tipo | Note |
|---|---|---|
| `societa_id` | STRING REQUIRED | ORTI \| INTUR |
| `business_unit_id` | STRING REQUIRED | HOTEL \| LIDO \| RESIDENCE |
| `anno` | INTEGER REQUIRED | Anno |
| `data_apertura` | DATE REQUIRED | Data apertura stagione |
| `data_chiusura` | DATE | Data chiusura stagione |
| `notti_apertura` | INTEGER | Numero notti apertura |
| `note` | STRING | Note |

---

## Viste (v_*)

### `v_piano_finanziario_consuntivo`
**Tipo**: aggregazione consuntivo per voce piano finanziario
**Fonti**: `f_movimenti_contabili` (ESOLVER) + `f_banche_movimenti` (BANCHE)
**Join key**: `d_voci_piano_finanziario` via LIKE pattern

**Output columns**: societa_id, voce_id, voce_label, sezione, categoria, anno, mese, periodo, importo

**Sign convention**:
- ENTRATE: `imp_avere - imp_dare` → positivo = entrata
- USCITE: `imp_dare - imp_avere` → positivo = uscita
- BANCHE ENTRATE: `importo_netto` (già corretto)
- BANCHE USCITE: `-importo_netto`

---

### `v_piano_finanziario_mensile`
**Tipo**: Budget vs Consuntivo, finestra rolling 18 mesi (-6m → +12m)
**Fonti**: scaffold × `d_voci_piano_finanziario` × `mesi` × `societa` + 3 LEFT JOIN:
1. `v_piano_finanziario_consuntivo` → `importo_consuntivo`
2. `f_budget_mensile` → `importo_budget` (via LIKE su codice_conto normalizzato)
3. `f_piano_finanziario_input` → `importo_manuale` (via voce_id diretto)

**Output columns**: societa_id, voce_id, voce_label, sezione, categoria, ord, anno, mese, periodo, tipo_periodo, importo_consuntivo, importo_budget, scostamento, scostamento_pct

**tipo_periodo**: CONSUNTIVO (mese < mese corrente) | BUDGET (mese >= mese corrente)

**Normalizzazione codice_conto per join budget**:
```sql
REPLACE(f_budget_mensile.codice_conto, '.', '') LIKE CONCAT(v.cod_conto_pattern, '%')
```

---

### `v_cashflow_mensile`
Vista cashflow mensile aggregato.

### `v_incassi_per_canale`
Vista incassi per canale (POS, bonifico, contante...).

### `v_pl_movimenti`
Vista P&L movimenti contabili.

### `v_ultima_data`
Vista con ultima data disponibile per fonte dati.

---

## Relazioni Chiave

```
f_movimenti_contabili.cod_conto
    LIKE d_voci_piano_finanziario.cod_conto_pattern + '%'
    → v_piano_finanziario_consuntivo

f_banche_movimenti.tipo_movimento
    LIKE '%' + d_voci_piano_finanziario.banca_tipo_pat + '%'
    → v_piano_finanziario_consuntivo

f_budget_mensile.codice_conto (normalizzato senza punti)
    LIKE d_voci_piano_finanziario.cod_conto_pattern + '%'
    → v_piano_finanziario_mensile (importo_budget)

f_piano_finanziario_input.voce_id
    = d_voci_piano_finanziario.voce_id
    → v_piano_finanziario_mensile (importo_manuale, addendo a importo_budget)

f_movimenti_contabili.cod_conto
    → d_piano_conti.codice_conto (lookup descrizione/tipo)
```

---

## Convenzioni Critiche

### Codici conto
| Contesto | Formato | Esempio |
|---|---|---|
| `f_movimenti_contabili.cod_conto` | **Senza punti** | `570913` |
| `f_budget_mensile.codice_conto` | **Con punti** | `57.09.13` |
| `d_voci_piano_finanziario.cod_conto_pattern` | **Senza punti** (prefisso) | `570913` |
| Esolver export raw | Con punti | `57.09.13.01` |

**Normalizzazione**: `REPLACE(codice_conto, '.', '')` per confronti cross-sistema.

### `tipo_conto` in `d_piano_conti`
| Codice | Significato |
|---|---|
| C | Cliente |
| F | Fornitore |
| B | Banca |
| S | Cespite |

### Business Unit
| ID | Descrizione |
|---|---|
| HOTEL | Hotel ricettivo |
| RESIDENCE | Residence |
| CVM | Casa Vacanza / Mini appartamenti |
| LIDO | Spiaggia / Stabilimento balneare |
| HQ | Direzione / Amministrazione |

### Sign convention (viste)
- Importi **ENTRATE** → positivo = entrata di cassa
- Importi **USCITE** → positivo = uscita di cassa
- `importo_netto` in `f_banche_movimenti` → positivo = entrata, negativo = uscita

### Dedup pattern
Tutte le tabelle fatto usano `hash_riga` MD5 per idempotenza. Le pipeline fanno `WRITE_APPEND` filtrando gli hash già presenti, oppure `DELETE + INSERT` per snapshot (f_budget_mensile).

---

## Pipeline di Ingestione

| Pipeline | File | Target BQ | Fonte |
|---|---|---|---|
| `ingest_movimenti_contabili.py` | ORTI/INTUR_LISTAMOVCONT.XLS | f_movimenti_contabili | Esolver export manuale |
| `ingest_budget_costi.py` | MAPPATURA DEI COSTI_v_2.xlsx + Incidenza_costi_personale.xlsx | f_budget_mensile | Excel locale |
| `ingest_piano_finanziario_input.py` | CSV manuale | f_piano_finanziario_input | CSV input |
| `ingest_voci_piano_finanziario.py` | bq/dimensioni/d_voci_piano_finanziario.csv | d_voci_piano_finanziario | CSV dizionario |
| `ingest_bilancino.py` | Bilancio di verifica XLS | f_bilancino | Esolver export |
| `ingest_piano_conti.py` | Piano dei conti XLS | d_piano_conti | Esolver export |
| `run_banca.sh` | rclone + pipeline banca | f_banche_movimenti + f_accodamenti | Drive datahub |

**Datahub Drive**: `mywork:00_hotelops_datahub/ingresso/`
**Mount locale**: `/Users/stefanodellapietra/Library/CloudStorage/GoogleDrive-stefano@panoramagroup.it/My Drive/hotelops_datahub/`

---

## Query di Riferimento

### Budget vs Consuntivo ORTI 2026
```sql
SELECT mese, voce_id, importo_consuntivo, importo_budget, scostamento, scostamento_pct
FROM `hotelops-suite.hotelops.v_piano_finanziario_mensile`
WHERE anno = 2026 AND societa_id = 'ORTI'
  AND (importo_consuntivo != 0 OR importo_budget != 0)
ORDER BY mese, ord;
```

### Movimenti contabili per conto (ORTI, anno corrente)
```sql
SELECT data_registrazione, cod_conto, rag_sociale, causale_contabile,
       imp_dare, imp_avere, (imp_dare - imp_avere) AS saldo_mov
FROM `hotelops-suite.hotelops.f_movimenti_contabili`
WHERE societa_id = 'ORTI' AND anno = 2026
ORDER BY data_registrazione;
```

### Movimenti banca MPS ORTI
```sql
SELECT data_operazione, banca_id, tipo_movimento, descrizione,
       importo_credito, importo_debito, importo_netto
FROM `hotelops-suite.hotelops.f_banche_movimenti`
WHERE societa_id = 'ORTI' AND banca_id = 'MPS'
ORDER BY data_operazione;
```

### Verifica foglie vs padri (no double-counting)
```sql
-- Tutti i cod_conto in f_movimenti_contabili sono foglie
-- Nessun conto padre ha movimenti (verificato)
SELECT cod_conto, COUNT(*) as n_movimenti
FROM `hotelops-suite.hotelops.f_movimenti_contabili`
WHERE societa_id = 'ORTI'
GROUP BY cod_conto ORDER BY n_movimenti DESC LIMIT 20;
```
