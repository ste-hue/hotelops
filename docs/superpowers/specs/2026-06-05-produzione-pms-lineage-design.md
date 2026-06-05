# Produzione PMS Ingest (lineage era) — Design Spec

**Date:** 2026-06-05
**Owner:** Stefano
**Status:** Draft → user review → writing-plans
**Supersedes:** `docs/superpowers/specs/2026-04-29-produzione-pms-ingest-design.md` (mai implementato; precede l'era GCS/lineage)

---

## TL;DR

Ingest del HotelCube Power BI **Daily Production Report** (taglio per classe di ricavo,
**Imponibile**) in una nuova fact table `f_produzione_pms`, grana **giorno × struttura ×
classe**, attraverso il **layer lineage esistente** (`hotelops intake` → `f_raw_objects`
+ `gs://hotelops-raw`, poi `hotelops promote` → parser → tabella canonica con
`raw_object_id` FK).

Lifecycle **SNAPSHOT** con natural_key `(business_unit_id, anno)`: ogni ri-export di una
struttura × anno **rimpiazza** quella fetta. È il modo corretto di gestire una fonte
**rivedibile** (gli storni cambiano giorni passati): evita sia il doppio conteggio
(APPEND con importo nell'hash) sia il dato stale (APPEND con dedup senza importo).

Questo spec **modernizza** la bozza del 2026-04-29 su tre assi:
1. **Ingest path**: dal legacy `classify.py`/`registry.yaml`/insert diretto → al lineage
   (`source_registry.yaml` + intake/promote + FK I9).
2. **business_unit_id riempito** dai file **per struttura** (HOTEL/RESIDENCE/CVM) che
   prima non avevamo — risolve il debito "BU NULL" del vecchio spec.
3. **Lifecycle SNAPSHOT** (era APPEND) — robusto agli storni.

Obiettivo guida invariato: *"i miei dati nel mio data warehouse, dedupati, senza
ri-estrarli mai più"*. Lenti, mapping classe→BU/conto, dashboard arrivano dopo.

---

## Filosofia GCS vs BigQuery (articolata 2026-06-05)

- **GCS = drop & store.** Ogni file estratto (entrambi i tagli — occupazione *e* classi
  — per ogni struttura × anno) viene depositato in `gs://hotelops-raw`, versionato
  (Object Versioning) e immutabile. Una volta lì, non si ri-estrae mai più.
- **BigQuery = il file unico pulito.** Una tabella canonica che accumula i vari file,
  deduplicata, sempre con l'ultima verità.

La produzione cade in questo modello: i raw (giornalieri, entrambi i tagli) vivono in
GCS per sempre; la tabella canonica espone i ricavi per classe, deduplicati via SNAPSHOT.

---

## Source

**File input:** HotelCube Power BI "Daily Production Report", esportato **per struttura**
e **per anno**, taglio **classe di ricavo**, `Descrizione = Imponibile`.

Per ogni struttura × anno esistono **due tagli** (due file distinti):
- **Taglio classe** (questo spec promuove questo): colonne = classi di ricavo
  (`01ROOM`, `02FB`, …), righe = giorni. È quello con il dettaglio ricavo.
- **Taglio occupazione** (raw-only per ora — vedi §Occupazione): colonne = metriche
  camere/pax (`Cam. Occupate`, `Adulti`, …) + `Importo` totale giornaliero.

**Format:** xlsx, sheet unico `Export`. I metadati periodo (`CodiceHotel`, `Anno`,
`Descrizione`) vivono nell'ultima cella `Applied filters`, non nelle righe dati.

### Struttura del file taglio-classe

```
Sheet: "Export"
Row 0:  ["Classe", (None opz.), "01ROOM", "02FB", "03PARK", ..., "Total"]
Row 1:  ["Data", "Importo", "Importo", ...]          (riga label, skip)
Row 2+: [datetime(YYYY,M,D), <importo per classe>, ..., <total>]
...
Row N:  ["Total", <somme colonna>]                    (skip)
Row N+1: blank
Row N+2: ["Applied filters:\n... CodiceHotel is PANORAMAHT ... Descrizione is
          Imponibile ... Anno is 2026"]
```

- Il **set di classi varia per struttura**: HOTEL ha
  `01ROOM 02FB 03PARK 07DIV 11FITTO 80AFFITT 99ACC`; RESIDENCE aggiunge/omette alcune;
  CVM ha solo `01ROOM 02FB 03PARK`. Lo storico 2025 espone anche `04BEALL`, `10BEBAR`
  (beverage). Il parser **non hardcoda** l'elenco: rileva le colonne-classe via regex
  `^\d{2}[A-Z]+$` nella riga header.
- Colonna `Total` = somma riga, derivata → **non** si scrive in BQ.
- Celle vuote/`None` = nessun ricavo per quella classe quel giorno → si scartano.
- **I valori negativi si tengono** (storni/rettifiche legittime).

### CodiceHotel → business_unit_id

```python
HOTEL_TO_BU = {
    "PANORAMAHT": "HOTEL",
    "ANGELINARES": "RESIDENCE",
    "HOMEHOLIDAY": "CVM",
}
```

### Cosa NON è questo file

- ❌ Non è `f_ricavi_fb` (mensile, solo drill-down di `02FB`, export "Produzione Netta",
  altra dashboard). **Overlap parziale sul 02FB** → debito di riconciliazione (§Debiti).
- ❌ Non è `f_pms_statistiche` (Cruscotto, RAW_ONLY, room/occupancy/ADR — è il taglio
  occupazione di un altro export).
- ❌ Non è `f_accodamenti` (scritturale: corrispettivi/caparre/fatture HotelCube).
- ❌ Non è `f_movimenti_contabili` (Esolver prima nota, COMPETENZA registrata).

---

## Decisione di dominio: cutover INTUR → ORTI

Invariata dallo spec 2026-04-29. Fino al **2025-03-31** l'operativa HotelCube
(Hotel+Residence+CVM) era di **INTUR**; dal **2025-04-01** è passata a **ORTI**.

```python
# core/schemas.py
from datetime import date
OPERATIONS_CUTOVER_DATE = date(2025, 4, 1)
```

`societa_id` è derivata deterministicamente: `INTUR` se `data < cutover`, altrimenti
`ORTI`. Nei file 2025 questo significa che lo **stesso file** (es. HOTEL 2025) produce
righe INTUR (gen–mar) e righe ORTI (apr–dic). Lo SNAPSHOT-replace resta scoped per
`(business_unit_id, anno)` — il replace cancella entrambe le società di quella
struttura×anno, perché provengono dallo stesso export.

**Caveat noto (non risolto qui):** i ricavi spiaggia (`04BEALL`/`10BEBAR`/…) possono
essere intercompany (ospiti hotel ORTI che usano il Lido INTUR). Si gestisce nelle lenti
future, non in ingest.

---

## Naming lineage & GCS

Source name (grammar `<SYSTEM>_<DATASET>_<SOCIETA>_<LIFECYCLE>`):
**`POWERBI_PRODUZIONE_ORTI_SNAPSHOT`**.

> Nota: la `<SOCIETA>` nel nome del source è `ORTI` (entità operativa corrente, come
> per `POWERBI_RICAVIFB_ORTI_SNAPSHOT`). La società *per-riga* resta derivata dal
> cutover e può essere INTUR per le date pre-2025-04-01.

Raw storage:
```yaml
raw_storage:
  backend: gcs
  bucket: hotelops-raw
  path_template: "powerbi/produzione/ORTI"
```
URI effettivi sotto `gs://hotelops-raw/POWERBI_PRODUZIONE_ORTI_SNAPSHOT/<anno>/<mese>/…`,
con Object Versioning (i re-export sovrascrivono la stessa generation logica, lo storico
resta nelle versioni GCS + in `f_lineage_events`).

I file **taglio occupazione** si depositano nello stesso source via intake (raw-only),
**ma non vengono promossi** ora (vedi §Occupazione).

---

## Source registry entry

```yaml
# core/source_registry.yaml
  # ── Produzione PMS giornaliera per classe — SNAPSHOT ──────────────────────
  POWERBI_PRODUZIONE_ORTI_SNAPSHOT:
    system: POWERBI
    dataset: PRODUZIONE
    dataset_label: "Produzione giornaliera per classe (Daily Production Report, Imponibile)"
    societa: ORTI
    business_unit: null
    lifecycle: SNAPSHOT
    canonical_table: f_produzione_pms
    parser_module: ingest.flussi.ingest_produzione_pms
    natural_key: [business_unit_id, anno]
    loop_targets: [monthly_close, budget_vs_consuntivo]
    promotion_policy: AUTO
    detector_category: produzione_pms
    raw_storage:
      backend: gcs
      bucket: hotelops-raw
      path_template: "powerbi/produzione/ORTI"
```

L'invariante del `source_resolver` (`loop_targets != [] ⇔ promotion_policy != RAW_ONLY`)
è rispettato: ci sono loop target → policy `AUTO`.

---

## Schema BigQuery — `f_produzione_pms`

Grana: **giorno × struttura × classe**, importo **imponibile**.

| col | tipo | mode | semantica |
|---|---|---|---|
| `societa_id` | STRING | REQUIRED | `ORTI`/`INTUR`, derivata via cutover |
| `business_unit_id` | STRING | REQUIRED | `HOTEL`/`RESIDENCE`/`CVM`, da CodiceHotel |
| `data` | DATE | REQUIRED | data riga (partition DAY) |
| `anno` | INT64 | REQUIRED | da `Applied filters` |
| `mese` | INT64 | REQUIRED | derivato da `data` |
| `classe` | STRING | REQUIRED | codice opaco (`01ROOM`…`99ACC`) |
| `importo_imponibile` | NUMERIC | REQUIRED | valore cella |
| `file_sorgente` | STRING | REQUIRED | nome file per audit |
| `hash_riga` | STRING | REQUIRED | `md5(business_unit_id, anno, data, classe)` |
| `raw_object_id` | STRING | NULLABLE | FK a `f_raw_objects` (I9), stampato da `promote` |
| `data_caricamento` | TIMESTAMP | REQUIRED | quando è entrato in BQ |

**Partitioning:** `data` (DATE). **Clustering:** `(business_unit_id, classe)`.

**Lifecycle:** `SNAPSHOT`, `natural_key=[business_unit_id, anno]`. Il write
DELETE-INSERT cancella le righe delle `(business_unit_id, anno)` distinte presenti nel
batch e reinserisce — un file = una struttura × anno → rimpiazza esattamente quella fetta.

`F_PRODUZIONE_PMS = _t("f_produzione_pms")` in `core/config.py`.

### 5-Dimensions governance — debito esplicito (invariato)

Le altre tre dimensioni canoniche (`funzione_id`, `location_id`, `oggetto_id`) restano
fuori schema per ora. La derivazione `classe → categoria_ce / cod_conto` è demandata a
una futura `d_classi_produzione` (TBD in STATUS.md). Decisione YAGNI: store first,
classify later. `business_unit_id` invece **ora c'è** (era il debito principale del
vecchio spec).

---

## Pydantic schema

```python
# core/schemas.py
class ProduzioneRow(BaseModel):
    """Schema for f_produzione_pms — daily production by struttura × classe.

    Source: HotelCube Power BI Daily Production Report (taglio classe, Imponibile),
    one file per struttura × anno. Grana giorno × struttura × classe.

    Pattern: SNAPSHOT, natural_key (business_unit_id, anno). Re-export di una
    struttura×anno rimpiazza quelle righe (robusto agli storni).

    societa_id derivata da `data` vs OPERATIONS_CUTOVER_DATE.
    raw_object_id = FK a f_raw_objects, stampato dal path `promote`.
    """
    societa_id: SocietaId
    business_unit_id: BusinessUnitId
    data: date
    anno: int
    mese: int
    classe: str
    importo_imponibile: Decimal
    file_sorgente: str
    hash_riga: str
    raw_object_id: Optional[str] = None
    data_caricamento: datetime

    @field_validator("mese")
    @classmethod
    def mese_range(cls, v: int) -> int:
        if not 1 <= v <= 12:
            raise ValueError(f"mese fuori range: {v}")
        return v

    @field_validator("classe")
    @classmethod
    def classe_not_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("classe vuoto")
        return v

    @model_validator(mode="after")
    def societa_matches_cutover(self) -> "ProduzioneRow":
        expected = "INTUR" if self.data < OPERATIONS_CUTOVER_DATE else "ORTI"
        if self.societa_id != expected:
            raise ValueError(
                f"societa_id={self.societa_id!r} incoerente con cutover "
                f"{OPERATIONS_CUTOVER_DATE} per data {self.data}"
            )
        return self

    @model_validator(mode="after")
    def anno_matches_data(self) -> "ProduzioneRow":
        if self.data.year != self.anno or self.data.month != self.mese:
            raise ValueError(
                f"anno/mese ({self.anno}/{self.mese}) incoerenti con data {self.data}"
            )
        return self
```

---

## Parser `ingest/flussi/ingest_produzione_pms.py`

Modellato su `ingest_ricavi_fb.py` (stesso contratto: `--file`, `--raw-object-id`,
`--dry-run`; invocato da `hotelops promote`).

### Responsabilità

1. **Read** sheet `Export`.
2. **Period**: parse `Applied filters` → `CodiceHotel` (→BU via `HOTEL_TO_BU`) + `Anno`.
   Verifica `Descrizione is Imponibile` (rifiuta i file Lordo con errore chiaro).
3. **Rileva colonne-classe**: nella riga header, colonne il cui valore matcha
   `^\d{2}[A-Z]+$` (esclude `Total`, `Data`, label vuote). Niente lista hardcoded.
4. **Unpivot wide→long**: per ogni `(riga-giorno, colonna-classe)` con valore non-null,
   emetti una riga. Skippa righe `Total`/blank e celle vuote. Tieni i negativi.
5. **Derive** `societa_id` (cutover su `data`), `mese` (da `data`).
6. **hash_riga** = `make_hash(business_unit_id, str(anno), data.isoformat(), classe)`.
7. **Validate** via `validate_batch(rows, ProduzioneRow, context=...)`.
8. **Write** SNAPSHOT: `bq_write_validated(F_PRODUZIONE_PMS, rows, mode="snapshot",
   natural_key=["business_unit_id", "anno"])`.

`--dry-run` fa parse+validate senza scrivere e logga `BU anno : N righe (M classi × D giorni)`.

---

## Occupazione → raw-only ora, promote deferred (YAGNI)

I file taglio-occupazione (camere/pax + `Importo` totale) si depositano in GCS via
`intake` (raw-only, stesso source), ma **non si promuovono**. L'`Importo` giornaliero
totale dell'occupazione è la somma delle classi → il ricavo è già interamente in
`f_produzione_pms`. Il contributo esclusivo dell'occupazione (camere occupate, pax) serve
solo a KPI camere (occupazione %, RevPAR, ADR), che oggi non sono richiesti.

Quando emergerà quel bisogno: nuova tabella `f_produzione_occupazione`
(giorno × struttura) + secondo parser. Non in questo spec.

---

## Cleanup: 3 file lordo orfani

In `f_raw_objects` esistono 3 oggetti con `source_name = POWERBI_PRODUZIONE_ORTI_APPEND`
(i file LORDO del 17/05, copertura → 16/05), ma quel source **non è nel registry** →
oggetti RAW non promovibili e nome di source diverso (`_APPEND` vs `_SNAPSHOT`).

Azione: emettere un `LineageEvent` di **REJECTED** sui 3 oggetti (restano in GCS per
audit, marcati come non-canonical). Motivazione registrata: superseded da export
Imponibile + source rinominato a `_SNAPSHOT`.

---

## Backfill iniziale

Via `hotelops intake` + `hotelops promote` dei file **taglio-classe** già estratti
(in `~/Downloads`), per struttura × anno:
- 2026: HOTEL, RESIDENCE, CVM (→ 04/06)
- 2025: HOTEL, RESIDENCE, CVM (anno intero)

I file taglio-occupazione: solo `intake` (raw-only).

**Criterio di successo del backfill** (verificabile): per ogni struttura × anno, la
somma `importo_imponibile` in `f_produzione_pms` deve combaciare con il `Total` del file
taglio-occupazione corrispondente (riconciliazione già verificata a mano in sessione:
HOTEL 2026 = 954.494,19; ANG = 107.820,96; CVM = 53.588,04; HOTEL 2025 = 3.282.683,39;
ecc.).

---

## Test plan (`tests/test_ingest_produzione_pms.py`)

Il plan TDD produrrà la lista ordinata. Test mandatori:

1. **Applied filters parse** — estrae (BU, anno) da CodiceHotel/Anno; rifiuta
   `Descrizione is Lordo`; rifiuta CodiceHotel sconosciuto.
2. **Rilevamento colonne-classe variabile** — fixture HOTEL (7 classi, con col blank in
   pos.1) e CVM (3 classi, senza blank) → entrambe rilevano le classi giuste; `Total`
   mai inclusa.
3. **Unpivot wide→long** — 3 giorni × 3 classi con alcune celle vuote → solo le celle
   valorizzate diventano righe; conteggio atteso.
4. **Negativi tenuti** — cella `-43,00` → riga con importo negativo, non scartata.
5. **Cutover boundary** — `data=2025-03-31` → societa INTUR; `2025-04-01` → ORTI;
   Pydantic raise se incoerente.
6. **hash determinismo** — stesse chiavi → stesso hash; cambia `classe` o `data` → hash
   diverso.
7. **SNAPSHOT scope-replace** (mock BQ) — caricare HOTEL-2026 due volte con un giorno
   rivisto (storno) → 1 riga per (giorno, classe), valore = ultimo export, nessun doppio;
   ANG-2026 caricata prima resta intatta.
8. **anno/mese coerenti con data** — Pydantic raise se `data.year != anno`.

---

## Files to modify / create

| File | Azione |
|---|---|
| `core/schemas.py` | + `OPERATIONS_CUTOVER_DATE`, + `ProduzioneRow`, esporre in `validate_batch` |
| `core/config.py` | + `F_PRODUZIONE_PMS` |
| `core/source_registry.yaml` | + entry `POWERBI_PRODUZIONE_ORTI_SNAPSHOT` |
| `core/bq/` (DDL/creazione tabella) | + `f_produzione_pms` (partition `data`, cluster `business_unit_id, classe`) |
| `ingest/flussi/ingest_produzione_pms.py` | nuovo parser |
| `tests/test_ingest_produzione_pms.py` | nuovo file (≥8 test) |
| `docs/superpowers/specs/2026-04-29-produzione-pms-ingest-design.md` | header "Superseded by 2026-06-05…" |
| `CLAUDE.md` | + riga `f_produzione_pms` in fact tables; + source nel registry list |
| `STATUS.md` | aggiorna thread produzione; voce `d_classi_produzione TBD` |

---

## Out of scope (YAGNI)

- ❌ `f_produzione_occupazione` (camere/pax) — raw-only ora, promote quando serve RevPAR.
- ❌ `d_classi_produzione` (mapping classe → BU/conto/categoria_ce).
- ❌ View / lenti / dashboard sulla produzione.
- ❌ Riconciliazione `f_produzione_pms` ↔ `f_ricavi_fb` (overlap 02FB) ↔ `f_accodamenti`.
- ❌ `detect_produzione_pms` nel classifier legacy — il flusso è intake/promote, non
   classify/orchestrate.
- ❌ Cloud Functions / Dataflow / Composer — l'orchestrazione è la CLI esistente.

---

## Debiti annotati (espliciti, non risolti qui)

1. **Overlap 02FB con `f_ricavi_fb`** — entrambe espongono ricavo F&B (qui giornaliero
   aggregato a classe 02FB; là mensile per ~20 codici). Riconciliazione futura, non un
   join meccanico ora. Da annotare in STATUS.md.
2. **Mapping `d_classi_produzione`** — classe → BU/categoria_ce/cod_conto. TBD.
3. **Intercompany spiaggia** (BE* classes) — ORTI/INTUR ambiguo per ospiti hotel al Lido.
   Risolto nelle lenti.

---

## Invariants compliance check

| Invariant | Status |
|---|---|
| **I1** (Pydantic gate) | ✅ `ProduzioneRow` + `validate_batch` |
| **I2** (lifecycle) | ✅ SNAPSHOT, natural_key `(business_unit_id, anno)` |
| **I3** (ontology SSOT) | ✅ `societa_id`/`business_unit_id` già canonici, nessuna entità nuova |
| **I4** (dimensioni) | ⚠️ COMPETENZA implicita (revenue accrual). 5-dim: societa+BU riempite, altre 3 debito esplicito |
| **I8** (locality row-selection) | ✅ nessuna row-selection cross-fonte; SNAPSHOT replace |
| **I9** (lineage FK) | ✅ `raw_object_id` stampato da `promote` su ogni riga |

---

## Next step

Dopo user-review di questo spec, invocare `superpowers:writing-plans` per generare il
plan TDD eseguibile.
