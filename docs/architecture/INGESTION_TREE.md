# INGESTION_TREE — mappa delle fonti dati HotelOps

**Last update:** 2026-06-09 · **Status:** mappa concettuale viva

> Questo è l'**albero concettuale** delle fonti che HotelOps ingerisce: come sono
> organizzate per gruppo-origine, quale lente temporale alimentano, cosa aspettarsi
> da ciascun file, dove finisce in BigQuery. Serve a riconoscere un file quando arriva
> ("dove va, cosa devo farci") e a riconciliare la tassonomia umana col registry tecnico.
>
> ⚠️ **Questo doc NON è la SSOT tecnica.** La verità tecnica di policy/parser/lifecycle è
> `core/source_registry.yaml` (governance) + `core/registry.yaml` (signature detector) + lo
> schema BigQuery live. Se questo albero diverge da quei file, **vincono loro**. Qui l'albero
> è curato per gli umani; lì è eseguibile dal sistema.

---

## 1. Albero macro

Quattro macro-gruppi "roba grossa" oggi, due famiglie future. Ogni gruppo è ancorato a una
**lente** del modello a 3 dimensioni temporali (vedi `LE_3_DIMENSIONI.md`): COMPETENZA, CASSA,
IMPEGNO — più la dimensione **COMMERCIALE** (cosa accade nelle operazioni, a monte dei numeri).

```
HOTELOPS INGEST
│
├─ 🛒 HOTELCUBE ........... COMMERCIALE   (produzione / PMS / PowerBI / RistoCube)
│
├─ 📒 ESOLVER ............. COMPETENZA    (contabilità / partite / bilancino)   [+ IMPEGNO]
│
├─ 🏦 BANCHE .............. CASSA         (movimento reale del soldo in banca)
│
├─ 🧾 ACCODAMENTI ......... CASSA / PONTE (PMS → contabile; spina dorsale cash)
│        gruppo separato di proposito: tecnicamente è HotelCube, ma concettualmente
│        alimenta il cash spine (riconciliazione cassa giornaliera), non il commerciale.
│
├─ 🔜 GOOGLE WORKSPACE .... FUTURO        (API-driven via domain-wide delegation:
│                                          Drive / Gmail / Calendar / journal)
│
└─ 🔮 FUTURE SOURCES ...... FUTURO        (fatture, contratti, altri verticali)
```

---

## 2. Dettaglio per ramo

Legenda stato: ✅ canonical attiva · 🟠 RAW_ONLY (grezzo, mai promosso) · ❌ gap (non registrata).

### 🛒 HOTELCUBE — lente COMMERCIALE

Tutto ciò che racconta *cosa è successo nelle operazioni*: produzione, ricavi, consumi, comande.
Origine: export dal PMS HotelCube, sia nativi sia via semantic-layer PowerBI, più il POS RistoCube.

| Sotto-ramo | Esempio file | Target BQ | Lifecycle | Policy | Stato |
|---|---|---|---|---|---|
| **powerbi/CONSUMI** | `Consumptions F&B Data*.xlsx` (sheet `Export`, header `Data - Anno`/`CodiceArticolo`/`Importo`) | `f_consumi_economato` | APPEND | AUTO | ✅ |
| **powerbi/PRODUZIONE** | `Daily Production Report` (Imponibile) | `f_produzione_pms` | SNAPSHOT | AUTO | ✅ |
| **powerbi/RICAVIFB** | `Produzione Netta` (sheet `Export`, header `Classe`/`Codice`/`Descrizione Addebito`) | `f_ricavi_fb` | SNAPSHOT | AUTO | ✅ |
| **powerbi/CRUSCOTTO** | cruscotto PMS | `f_pms_statistiche` | APPEND | RAW_ONLY | 🟠 |
| **powerbi/SEMANTICMODEL** | dump semantic model | `f_pms_statistiche` | APPEND | RAW_ONLY | 🟠 |
| **ristocube/ORDERS** | `Orders Report RISTOCUBE*.xlsx` (struttura annidata comanda→items) | `f_ristocube_orders` | APPEND | AUTO | ✅ |
| **ristocube/vendite_fb** | export vendite giorno×sala×articolo | `f_vendite_fb` | APPEND | — | ❌ non registrata |
| **hotelcube/COPERTI** | coperti giornalieri per BU/tipo_ospite | `f_coperti_giornalieri` | APPEND | AUTO | ✅ |

> Famiglia **PowerBI-Export**: tutte le fonti `powerbi/*` condividono il pattern xlsx sheet `Export`,
> mese testuale IT, righe `read_only` ragged, riga "Total" da saltare. È un contratto-template
> condiviso (astrazione guadagnata da 5 istanze) — vedi gaps §6.

### 📒 ESOLVER — lente COMPETENZA (+ IMPEGNO)

Il mondo contabile: quanto consumo/genero per competenza, indipendentemente da quando il soldo si muove.

| Sotto-ramo | Esempio file | Target BQ | Lifecycle | Policy | Stato |
|---|---|---|---|---|---|
| **MOVIMENTI** | prima nota `LISTAMOVCONT` (ORTI + INTUR) | `f_movimenti_contabili` | APPEND | AUTO | ✅ |
| **BILANCINO** | bilancio di verifica, leaf nodes | `f_bilancino` | SNAPSHOT | AUTO | ✅ |
| **BUDGET** | Gasparotto "Master Completo" | `f_budget_mensile` | SNAPSHOT | AUTO | ✅ |
| **PARTITE** ◀ IMPEGNO | partite aperte fornitori (ORTI + INTUR) | `f_partite_aperte_fornitori` | SNAPSHOT | AUTO | ✅ |
| **PF** | piano finanziario input | `f_piano_finanziario_input` | SNAPSHOT | AUTO | ✅ |
| **SCHEDA** | registro saldi banca end-of-day | `f_saldi_banca_snapshot` | APPEND | AUTO | ✅ |

> **PARTITE = dimensione IMPEGNO**: il debito è preso (fattura ricevuta) ma non ancora pagato.
> Vive in Esolver per origine, ma temporalmente è il terzo asse, distinto da COMPETENZA e CASSA.

### 🏦 BANCHE — lente CASSA

Il movimento reale del soldo. Origine: estratti homebanking per banca × società.

| Banca | Società | Target BQ | Lifecycle | Policy | Stato |
|---|---|---|---|---|---|
| **MPS** | ORTI + INTUR | `f_banche_movimenti` | APPEND | AUTO | ✅ |
| **INTESA** | ORTI + INTUR | `f_banche_movimenti` | APPEND | AUTO | ✅ |
| **SELLA** | INTUR | `f_banche_movimenti` | APPEND | AUTO | ✅ |
| **MPS_KROSS** | ORTI | `f_banche_movimenti` | APPEND | — | ❌ non registrata |
| **BCP** | INTUR | `f_banche_movimenti` | APPEND | — | ❌ non registrata |

### 🧾 ACCODAMENTI — lente CASSA / PONTE PMS↔contabile

Gruppo separato per scelta concettuale: l'origine tecnica è HotelCube, ma il ruolo è alimentare la
**riconciliazione cassa giornaliera** (corrispettivi, caparre, fatture attive) — è la spina dorsale
che lega ciò che il PMS ha incassato a ciò che la contabilità/banca registrano.

| Sotto-ramo | Esempio file | Target BQ | Lifecycle | Policy | Stato |
|---|---|---|---|---|---|
| **ACCODAMENTI** | TXT pipe-delimited `H_/R_/C_` × `Corr/Mov/Fatt` | `f_accodamenti` | APPEND | AUTO | ✅ |

### 🔜 GOOGLE WORKSPACE — futuro, API-driven

Non ancora ingerito. Via **domain-wide delegation** diventa una sorgente API invece che file-drop:
Drive (documenti), Gmail (email/comunicazioni), Calendar, journal operativo. È il canale "morbido"
del contesto umano attorno ai numeri.

### 🔮 FUTURE SOURCES — futuro

Fatture (passive/attive in formato strutturato), contratti, e le fonti dei prossimi verticali.
Si registrano quando il flusso dati reale esiste — niente fonti speculative.

---

## 3. Flow: Drive → GCS raw → BQ canonical

```
  ┌─────────┐  scarico/   ┌──────────────────────┐  intake  ┌────────────────────┐  promote  ┌──────────────┐
  │ ORIGINE │  drop file  │ DRIVE                │  registro │ GCS RAW            │  parser   │ BIGQUERY     │
  │ (PMS/   │ ──────────▶ │ organizzo per umani  │ ───────▶ │ gs://hotelops-raw  │ ────────▶ │ f_* canonical│
  │  banca/ │             │ (cartelle leggibili) │          │ immutabile+versioni│  + gate   │ il fatto     │
  │  Esolver)             └──────────────────────┘          └────────────────────┘           └──────────────┘
        │                                                     f_raw_objects (identity)
        │                                                     f_lineage_events (stato)
        └─ comandi: `hotelops intake <file> --source-name X`  →  `hotelops promote --raw-object-id Y`
```

Percorsi raw per fonte (`raw_storage.path_template` in `source_registry.yaml`), es.:
`powerbi/consumi/ORTI` · `homebanking/ORTI/MPS` · `economato` · `powerbi/produzione/ORTI`.

Il **policy gate** (`core/lineage/policy_gate.py`) blocca la promozione a canonical se la fonte
non ha `loop_targets` (invariante: `loop_targets == [] ⇔ promotion_policy == RAW_ONLY`).

---

## 4. Regola dei tre piani

| Piano | Cos'è | Per chi | Verità |
|---|---|---|---|
| **Drive** | dove organizzo i file in cartelle leggibili | **umani** | comodità, non canonical |
| **GCS `gs://hotelops-raw`** | il raw immutabile, versionato, per-oggetto | **lineage** | memoria storica intatta |
| **BigQuery `f_*`** | il fatto canonico osservato dal twin | **sistema** | SSOT dei fatti |

Sintesi: **Drive per gli umani · GCS per il raw immutabile (lineage) · BigQuery per il sistema.**
Questo è l'enforcement concreto dell'invariante I9 (GCS è il boundary obbligatorio dell'ingest).

---

## 5. Warning — questo è concettuale, non tecnico

Questo albero è una **mappa curata per gli umani**. La SSOT tecnica resta:

- `core/source_registry.yaml` — policy per fonte (lifecycle, promotion_policy, loop_targets, parser_module, raw_storage). **Vince questo per i fatti tecnici.**
- `core/registry.yaml` — signature detector (sheets/columns/filename) per il riconoscimento.
- schema BigQuery live — la forma reale delle tabelle.

Se l'albero diverge dai file sopra, **i file vincono** e l'albero va aggiornato.

---

## 6. Gaps immediati (stato 2026-06-09)

1. **`ristocube/vendite_fb` non registrata.** La tabella `f_vendite_fb` e il parser
   `ingest.flussi.ingest_vendite_fb` esistono, ma **non c'è una fonte in `source_registry.yaml`**.
   Flusso fermo (ultimo dato 2026-04-29). → registrare la fonte.
2. **`MPS_KROSS` (ORTI) e `BCP` (INTUR) non registrate.** CLAUDE.md le elenca tra le banche, ma
   mancano dal registry. Un estratto di quelle banche oggi non ha una fonte dichiarata.
3. **`classify.py` non legge `registry.yaml`.** Esistono **due sistemi di recognition indipendenti**
   che possono driftare: i `detect_*()` imperativi in `classify.py` e le `signatures:` dichiarative in
   `registry.yaml`. Il refactor "scientifico" (un solo motore che legge le signature dichiarative)
   risolve questo — ma è lavoro separato, non urgente.
4. *(minore)* `POWERBI_CONSUMI_ORTI_APPEND.detector_category` = `pms_statistiche` (errato, dovrebbe
   essere `economato`); non corretto perché tocca il routing — da sanare nel refactor.

---

## 7. Next action

> **Dopo questo doc: torna al cash spine, non partire col refactor registry.**

Il refactor del recognition (gap #3) e la spec source-contract sono reali ma **non sono la priorità**.
La priorità operativa resta il loop minimo del **cash control / cassa** end-to-end. L'albero serviva a
sapere *dove va cosa*; ora che la mappa c'è, il valore è nel chiudere lo spine cassa, non
nell'ingegnerizzare l'ingest.

---

## Related

- `docs/architecture/LE_3_DIMENSIONI.md` — COMPETENZA / CASSA / IMPEGNO
- `docs/architecture/INVARIANTS.md` — I5 (classify deterministico), I9 (GCS boundary)
- `docs/architecture/AI_INSTRUCTIONS.md` — layer model, canonical truth registry
- `core/source_registry.yaml` · `core/registry.yaml` — SSOT tecnica
- spec lineage: `docs/superpowers/specs/2026-05-05-ingest-lineage-gcs-design.md`
- decision (PROPOSED): "Source-Contract Ingest Model" (vault)
