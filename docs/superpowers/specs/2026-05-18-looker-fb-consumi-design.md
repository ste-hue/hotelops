# Looker F&B — Consumi, Pasti, Ricavi — Design Spec

**Date:** 2026-05-18
**Owner:** Stefano
**Status:** Draft → user review → writing-plans
**Branch / worktree:** `worktree-looker-fb`

---

## TL;DR

Una Looker (Looker Studio su BigQuery) per controllare il F&B del Gruppo Panorama
incrociando tre asset che già esistono o stanno per essere ingeriti:

1. **Costo merce** — `f_consumi_economato` (già in BQ) — *globale, una cucina sola*.
2. **Ricavi F&B** — `f_ricavi_fb` (**tabella nuova**, da ingerire dai 24 file
   "Produzione Netta Dashboard") — *per business unit*.
3. **Pasti** — `f_coperti_giornalieri` (già in BQ) — *per business unit*.

Output: 1 pipeline d'ingest + 4 viste BQ filtrabili. La Looker si auto-aggiorna a
ogni nuova ingestione perché legge le viste, non snapshot.

Asimmetria di fondo che governa tutto il design: **il costo è globale, ricavi e
pasti sono per BU.** Quindi il €/pasto e l'incidenza % sono KPI **mensili globali
livello cucina-hotel**; lo scontrino medio è invece calcolabile **per BU**.

---

## Obiettivi (dai requisiti utente)

| # | Requisito | Dove vive |
|---|---|---|
| R1 | Totale pasti con split HOTEL / RESIDENCE / CVM | `v_fb_pasti` |
| R2 | Confronto YoY (valore + %) — periodo X vs stesso X anno prima | tutte le viste |
| R3 | Multi-periodo: aprile 2026 vs anno prima / dopo | filtri Looker su anno |
| R4 | Variazione costo **per categoria alimentare** | `v_fb_consumi` |
| R5 | Prezzo medio pagato per categoria, anno su anno | `v_fb_consumi` |
| R6 | Capire se si compra di più o di meno (volume) | `v_fb_consumi` (driver) |
| R7 | Scomporre la variazione costo in **effetto prezzo vs effetto volume** | `v_fb_consumi` |
| R8 | Incidenza costo pasto = food cost % | `v_fb_kpi` |
| R9 | Tutto filtrabile (struttura, mese, categoria, ospite/staff) | dimensioni esposte |

Periodo di analisi: focus **2025–2026**, anni filtrabili. Il 2024 esiste solo
parzialmente (gestione INTUR pre-cutover) — incluso ma non garantito completo.

---

## Decisioni di brainstorming (sessione 2026-05-18, /grill-me)

| # | Branch | Decisione |
|---|---|---|
| D1 | Metrica | Analisi consumi/costo merce + conteggio pasti + incidenza %. |
| D2 | Strutture | Split HP/ANG/CVM **solo su pasti e ricavi**. Costo = blocco unico cucina hotel — non esiste un magazzino separato per Residence/CVM. |
| D3 | HQ / NULL / pasto / categoria | **Dimensioni filtrabili**, non decise in SQL. BU `NULL` esposto come `(non assegnato)`. `HQ` è la mensa staff: esposto con flag, mai sommato alla cieca ai pasti ospiti. |
| D4 | €/pasto e incidenza % | KPI **mensili, livello hotel globale**. Non per-struttura (il costo globale non è attribuibile a una BU senza inventare una ripartizione). |
| D5 | Grana di join | Costo e pasti/ricavi si toccano solo a livello **mese**. Niente spalmatura giornaliera artificiale del costo. |
| D6 | Ricavi | **In scope.** Servono per l'incidenza %. → ingestione dei 24 file in `f_ricavi_fb`. |
| D7 | Scontrino medio | Calcolabile **per BU** (ricavi BU ÷ coperti BU), entrambi per BU. |

---

## Sorgente ricavi: i file "Produzione Netta Dashboard"

**Input:** 24 file xlsx in `~/Downloads/{HP,ANG,CVM}/`, già rinominati
`<STRUTTURA>_<ANNO>-<MESE>.xlsx` (es. `HP_2025-08.xlsx`).

Copertura: HP / ANG / CVM × {apr–ott 2025, apr 2026}. Un file = **una struttura ×
un mese**.

### Struttura del file

```
Sheet: "Export"
Row 0 (header): Classe | Codice | Descrizione Addebito | Netto | Netto A.P. |
                Diff A.-A.P. | % A. vs A.P. | Netto A.P.P. | Diff A.-A.P.P. |
                % A. vs A.P.P. | Lordo | Lordo A.P. | Lordo A.P.P.
Row 1..N:       02FB | <codice> | <descrizione> | <netto> | ... | <lordo> | ...
Row "Total":    Total | None | None | <somma> | ...        ← scartata (derivata)
Row finale:     "Applied filters:\n...CodiceHotel is X\nAnno is Y\nMese is Z..."
```

- **Period metadata** (anno, mese, struttura) NON è nelle righe dati: si estrae
  parsando l'ultima riga "Applied filters" — `CodiceHotel`, `Anno`, `Mese`.
- `CodiceHotel`: `PANORAMAHT`→HOTEL, `ANGELINARES`→RESIDENCE, `HOMEHOLIDAY`→CVM.
- Colonne `A.P.` / `A.P.P.` (anno precedente / due anni prima) sono YoY
  pre-calcolato dal PowerBI → **non si ingeriscono**, il YoY lo fanno le viste
  sui dati reali della tabella.
- Si ingeriscono solo: `codice`, `descrizione`, `netto`, `lordo`.

### Distinzione dal file `Daily Production Report`

Esiste già lo spec `2026-04-29-produzione-pms-ingest-design.md` (tabella
`f_produzione_pms`, **non implementata**). Quel file è il *Daily Production
Report*: `02FB` come **aggregato unico giornaliero**. I file "Produzione Netta
Dashboard" di questo spec sono il **drill-down di `02FB`** nei ~20 codici pasto
(`SCBKFBB`, `RISLFOOD`, `DINFOOD`, ...), per mese e struttura. Tabelle distinte,
nessuna fusione.

---

## Lineage / GCS staging (direttiva utente 2026-05-18)

L'ingestione **parte sempre da GCS** col layer lineage esistente — niente load
diretto da `~/Downloads/`. Flusso canonico, identico a tutte le 13 sorgenti già
in `core/source_registry.yaml`:

```
hotelops intake <file> --source-name POWERBI_RICAVIFB_ORTI_SNAPSHOT
   → carica in gs://hotelops-raw, registra in f_raw_objects (source label),
     emette RAW_INGESTED + SOURCE_RESOLVED → stato CLASSIFIED
hotelops promote --raw-object-id <id>
   → invoca il parser_module → ingest_ricavi_fb stampa raw_object_id su ogni
     riga canonica → f_ricavi_fb → stato PROMOTED
```

Nuova source in `core/source_registry.yaml` (grammatica 4-token
`<SYSTEM>_<DATASET>_<SOCIETA>_<LIFECYCLE>`):

```yaml
POWERBI_RICAVIFB_ORTI_SNAPSHOT:
  system: POWERBI
  dataset: RICAVIFB
  dataset_label: "Produzione Netta F&B (export Power BI HotelCube)"
  societa: ORTI
  business_unit: null            # HOTEL/RESIDENCE/CVM derivata per-file
  lifecycle: SNAPSHOT
  canonical_table: f_ricavi_fb
  parser_module: ingest.flussi.ingest_ricavi_fb
  natural_key: [business_unit_id, anno, mese]
  loop_targets: [food_cost, monthly_close]
  promotion_policy: AUTO
  detector_category: ricavi_fb
  raw_storage:
    backend: gcs
    bucket: hotelops-raw
    path_template: "powerbi/ricavi_fb/ORTI"
```

Distinta da `POWERBI_CONSUMI_ORTI_APPEND` (quella è consumi → `f_consumi_economato`).

## Tabella nuova: `f_ricavi_fb`

| col | tipo | mode | semantica |
|---|---|---|---|
| `societa_id` | STRING | REQUIRED | `ORTI` (post 2025-04-01) / `INTUR` (pre) via `OPERATIONS_CUTOVER_DATE` |
| `business_unit_id` | STRING | REQUIRED | `HOTEL` / `RESIDENCE` / `CVM`, da `CodiceHotel` |
| `anno` | INT64 | REQUIRED | dal filtro |
| `mese` | INT64 | REQUIRED | dal filtro |
| `codice` | STRING | REQUIRED | codice opaco: `SCBKFBB`, `RISLFOOD`, `DINFOOD`, ... |
| `descrizione` | STRING | NULLABLE | "Risto Lunch Food", ... |
| `netto` | FLOAT64 | REQUIRED | ricavo netto |
| `lordo` | FLOAT64 | REQUIRED | ricavo lordo |
| `file_sorgente` | STRING | REQUIRED | nome file per audit |
| `hash_riga` | STRING | REQUIRED | md5 `(business_unit_id\|anno\|mese\|codice)` |
| `raw_object_id` | STRING | NULLABLE | FK a `f_raw_objects` — lineage (stampato dal `promote`) |
| `data_caricamento` | TIMESTAMP | REQUIRED | quando è entrato in BQ |

**Lifecycle: SNAPSHOT** con `natural_key = (business_unit_id, anno, mese)`.
Motivazione: ogni file è uno snapshot completo di una struttura-mese. Ricaricare
lo stesso mese (es. dopo un addebito tardivo) deve **rimpiazzare** quelle righe,
non accodare. APPEND+md5 produrrebbe doppioni quando il `netto` cambia.

Write via `bq_write_validated(mode="snapshot", natural_key=[...])` — gate I1.

**Partitioning:** nessuno (tabella piccola, ~20 righe × 24 file ≈ 500 righe).
**Clustering:** `(business_unit_id, anno, mese)`.

`tipo_pasto` e `categoria_fb` **non** si materializzano in tabella: il `codice`
resta opaco, la classificazione vive nella vista `v_fb_ricavi` (store first,
classify in view — coerente con la filosofia di `f_produzione_pms`).

### Pydantic — `RicaviFbRow` (`core/schemas.py`)

Campi come schema sopra. Validator:
- `netto`, `lordo` ≥ 0 non richiesto (resi/storni possono essere negativi) →
  nessun vincolo di segno.
- `business_unit_id` ∈ `{HOTEL, RESIDENCE, CVM}`.
- `societa_id` coerente con cutover: `mese/anno` < 2025-04 ⇒ INTUR (nei dati
  attuali sempre ORTI, ma il validator resta esplicito).
- `codice` non vuoto.

---

## Mapping codice → tipo_pasto (nelle viste, non in tabella)

| codici | `tipo_pasto` | `categoria_fb` |
|---|---|---|
| `SCBKF%`, `BRK%` | COLAZIONE | — |
| `RISLFOOD`, `RISLBEV%`, `RISTLUNC` | PRANZO | FOOD/BEVERAGE da suffisso |
| `RISDFOOD`, `RISDBEV`, `RISTDINN`, `DINFOOD`, `DINBEV` | CENA | FOOD/BEVERAGE da suffisso |
| `BAR`, `RISBFOOD` | BAR | — |
| `BAN`, `PASQ%`, `FERR%` | EVENTI | — |
| `ROOMSERV` | ALTRO | — |

Implementato come `CASE` in `v_fb_ricavi`. Se i codici crescono, il `CASE` si
estende lì; un codice non mappato cade in `tipo_pasto = '(da mappare)'` —
visibile, non silenzioso.

---

## Le 4 viste

### 1. `v_fb_consumi` — costo merce per categoria + driver prezzo/volume

**Fonte:** `f_consumi_economato`, filtrata ai reparti F&B
(`BRK`, `CUCINA`, `CANTINA`, `BANCHETTI`, `BAR_HOTEL`, `EVENTO`).
**Grana:** `anno × mese × reparto_id × classe × categoria_prodotto × codice_prodotto`.

Misure base: `quantita`, `costo` (= `importo`), `prezzo_unitario` =
`SAFE_DIVIDE(costo, quantita)`.

YoY su stesso `(mese, reparto, categoria, codice_prodotto)`, `LAG` su `anno`:
`costo_ap`, `quantita_ap`, `prezzo_unitario_ap`.

**Scomposizione driver** (price/volume variance, classica):
```
delta_costo     = costo - costo_ap
effetto_prezzo  = (prezzo_unitario - prezzo_unitario_ap) * quantita
effetto_volume  = (quantita - quantita_ap) * prezzo_unitario_ap
```
Identità di controllo: `effetto_prezzo + effetto_volume ≈ delta_costo` (residuo
= termine misto Δprezzo·Δquantità, trascurabile o esposto come `residuo`).
→ risponde a R6/R7: "il costo è salito perché Mario ha pagato di più
(effetto_prezzo) o perché abbiamo consumato di più (effetto_volume)?"

Filtri esposti: `classe` (FOOD/BEVERAGE/VARIE/...), `categoria_prodotto`,
`reparto_id`, `anno`, `mese`.

Nota: 2.029 righe hanno `categoria_prodotto` vuota → esposte come
`(non classificato)`. Pulizia a monte è data-quality, non blocca la vista.

### 2. `v_fb_pasti` — conteggio pasti per BU

**Fonte:** `f_coperti_giornalieri`.
**Grana:** `data_servizio × anno × mese × societa_id × business_unit_id ×
tipo_pasto × tipo_ospite`.

Misura: `n_coperti`.
Derivata: `is_staff` = `business_unit_id = 'HQ'` (mensa dipendenti).
`business_unit_id` NULL → esposto come `(non assegnato)`.

YoY: aggregato mensile, `LAG` su `anno` per stesso
`(mese, business_unit_id, tipo_pasto)` → `coperti_ap`, `var_pct`.

Filtri: struttura/BU, `tipo_pasto`, `tipo_ospite`, `is_staff`, anno, mese.

### 3. `v_fb_ricavi` — ricavi F&B per BU + scontrino medio

**Fonte:** `f_ricavi_fb` (nuova) + `f_coperti_giornalieri` (denominatore).
**Grana:** `anno × mese × business_unit_id × codice × tipo_pasto × categoria_fb`.

Misure: `netto`, `lordo`.
Join ai coperti mensili per BU → `coperti_bu` (stesso valore per ogni codice del
BU-mese), e `ricavo_per_coperto` = `SAFE_DIVIDE(netto, coperti_bu)`.

YoY su `(mese, business_unit_id, codice)`, `LAG` su `anno`.

Filtri: struttura, `tipo_pasto`, `categoria_fb`, anno, mese.

### 4. `v_fb_kpi` — bridge mensile globale: €/pasto + incidenza %

**Fonte:** tre CTE aggregate a `(anno, mese)`:
- costo cucina globale = `Σ importo` da `f_consumi_economato` reparti
  `(BRK, CUCINA, CANTINA)` — la cucina-hotel "piena" del pasto;
- coperti hotel = `Σ n_coperti` da `f_coperti_giornalieri`
  `business_unit_id = 'HOTEL'`;
- ricavi F&B totali = `Σ netto` da `f_ricavi_fb` (tutte le BU).

**Grana:** `anno × mese` (un valore globale per mese).

Metriche:
```
euro_per_pasto = SAFE_DIVIDE(costo_cucina, coperti_hotel)
incidenza_pct  = SAFE_DIVIDE(costo_cucina, ricavi_fb_totali)   -- food cost %
margine_fb     = ricavi_fb_totali - costo_cucina
```
YoY su tutte e tre, `LAG` su `anno` per stesso `mese`.

`BAR_HOTEL`, `EVENTO`, `BANCHETTI` restano **fuori** dal €/pasto (non sono pasti
pensione) ma restano visibili in `v_fb_consumi`.

---

## Collegamento Looker

Looker Studio → 4 data source = le 4 viste. Filtri condivisi `anno` / `mese` /
`business_unit_id` a livello report. Si auto-aggiorna a ogni ingestione perché
legge viste, non estratti.

```
f_consumi_economato ──→ v_fb_consumi ──┐
                     └─→ v_fb_kpi  ←───┤  (3 fonti aggregate a mese)
f_coperti_giornalieri ─→ v_fb_pasti ───┤
                     └─→ v_fb_ricavi ←─┤  (join coperti per scontrino)
f_ricavi_fb (NEW) ─────→ v_fb_ricavi ──┘
                     └─→ v_fb_kpi
```

---

## Pipeline d'ingest `ingest/flussi/ingest_ricavi_fb.py`

Responsabilità:
1. **Read** xlsx, sheet `Export`.
2. **Parse period** dall'ultima riga "Applied filters" (`CodiceHotel`, `Anno`,
   `Mese` italiano → numero). Mappa `CodiceHotel` → `business_unit_id`.
3. **Righe dati**: salta header, salta riga `Total`, salta la riga filtri.
4. Per ogni riga: `codice`, `descrizione`, `netto`, `lordo`.
5. **Derive** `societa_id` (cutover), `hash_riga`, `data_caricamento`.
6. **Stamp** `raw_object_id` (da `--raw-object-id`) su ogni riga.
7. **Pydantic** via `validate_batch(rows, RicaviFbRow, context=...)`.
8. **Write** via `bq_write_validated(mode="snapshot",
   natural_key=["business_unit_id","anno","mese"])`.

CLI: `python -m ingest.flussi.ingest_ricavi_fb --file <path> --raw-object-id <id>`
— è il `parser_module` invocato da `hotelops promote`. `--dry-run` per il parse
senza scrivere. Nessun `--dir`: il batch dei 24 file passa per `hotelops intake`
(→ GCS) + `hotelops promote` (→ parser).

### Classifier (`ingest/classify.py`)

Detector `detect_ricavi_fb`: xlsx, sheet `Export`, header
`row0[0:3] == ['Classe','Codice','Descrizione Addebito']`. Distingue dal
`Daily Production Report` (che ha `row0[0]=='Classe'` ma `Codice` assente e
header di classi `^\d{2}[A-Z]+$`). Va **prima** di `detect_produzione_pms`.

---

## Prerequisito data-quality (fuori dallo scope viste, ma tracciato)

**Netto vs lordo su `f_consumi_economato`.** L'utente richiede che i consumi
siano sul **netto**. L'ingest attuale (`ingest_consumi_economato.py`) prende la
colonna "Importo"/"Primo Per." così com'è — in PowerBI etichettata **lordo**.

Azione richiesta prima di fidarsi dei numeri di costo:
1. Verificare se il file sorgente Consumi F&B ha una colonna netto separata.
2. Se sì: ri-esportare con la colonna netto e adeguare il mapping in
   `ingest_consumi_economato.py`.
3. Se il valore attuale è già netto: correggere solo l'etichetta PowerBI.

Le viste non cambiano (la colonna resta `importo`). Questo è un task separato,
prerequisito alla messa in produzione della Looker, **non** parte di questo plan.

---

## File da creare / modificare

| File | Azione |
|---|---|
| `core/schemas.py` | + `RicaviFbRow` (con `raw_object_id`) |
| `core/config.py` | + `F_RICAVI_FB` table id |
| `core/registry.yaml` | + entry `ricavi_fb` |
| `core/source_registry.yaml` | + source `POWERBI_RICAVIFB_ORTI_SNAPSHOT` |
| `ingest/classify.py` | + `detect_ricavi_fb` + builder, in `DETECTORS` |
| `ingest/flussi/ingest_ricavi_fb.py` | nuovo (parser_module, `--file --raw-object-id`) |
| `core/bq/views/v_fb_consumi.sql` | nuovo |
| `core/bq/views/v_fb_pasti.sql` | nuovo |
| `core/bq/views/v_fb_ricavi.sql` | nuovo |
| `core/bq/views/v_fb_kpi.sql` | nuovo |
| `tests/test_ingest_ricavi_fb.py` | nuovo (≥7 test) |
| `CLAUDE.md` | + `f_ricavi_fb` in fact tables, + 4 viste |

---

## Test plan (`tests/test_ingest_ricavi_fb.py`)

1. **Parse filtri** — estrae `(CodiceHotel, Anno, Mese)` corretti dall'ultima
   riga; mese italiano → numero.
2. **CodiceHotel → BU** — `PANORAMAHT`→HOTEL, `ANGELINARES`→RESIDENCE,
   `HOMEHOLIDAY`→CVM; codice ignoto → errore.
3. **Riga Total esclusa** — mai presente nelle righe prodotte.
4. **Schema** — `netto`/`lordo` numerici; negativi ammessi; `codice` vuoto →
   ValidationError.
5. **hash_riga determinismo** — stesse chiavi → stesso hash; cambia mese → hash
   diverso.
6. **SNAPSHOT idempotente** (mock BQ) — ricaricare lo stesso file due volte
   lascia la tabella identica; un file con `netto` aggiornato rimpiazza il
   BU-mese.
7. **Detector** — `detect_ricavi_fb` matcha un fixture Produzione Netta; NON
   matcha il Daily Production Report; non matcha xlsx generico.

Le viste si verificano con query di smoke (riga di controllo
`effetto_prezzo + effetto_volume ≈ delta_costo`).

---

## Out of scope (YAGNI)

- ❌ Incidenza % e €/pasto **per BU** — il costo è globale, una ripartizione
  sarebbe inventata. Solo globale.
- ❌ Split costo cucina pranzo/cena — il magazzino non tagga la merce per pasto.
- ❌ Allocazione del costo cucina a Residence/CVM — non hanno cucina.
- ❌ Fix del netto/lordo su `f_consumi_economato` — prerequisito tracciato sopra,
  task separato.
- ✅ ~~Caricamento su GCS / lineage~~ — **rientrato in scope** (direttiva 2026-05-18): l'ingestione passa sempre da GCS via `intake`/`promote`.
- ❌ Automazione dell'export PowerBI (API giornaliera, PowerBI Plus) — discusso
  in riunione, è ops, non questo spec.
- ❌ Streamlit dedicato — la Looker è Looker Studio su viste BQ.
- ❌ `d_codici_fb` come dimensione — il mapping vive nel `CASE` di `v_fb_ricavi`
  finché i codici sono ~20.

---

## Invariants compliance

| Invariant | Status |
|---|---|
| **I1** (Pydantic gate) | ✅ `RicaviFbRow` + `bq_write_validated` |
| **I2** (lifecycle) | ✅ SNAPSHOT per `f_ricavi_fb`, natural_key esplicita |
| **I3** (ontology SSOT) | ✅ `societa_id`/`business_unit_id` già canonici |
| **I4** (3 dimensioni) | ⚠️ COMPETENZA implicita (ricavo accrual mensile). 5-dim: `funzione_id`/`location_id`/`oggetto_id` NULL — debito esplicito |
| **I5** (classify deterministico) | ✅ detector regex + sheet/header, no LLM |
| **I6** (stagionalità) | n/a — nessun forecast |
| **I7** (audience umana) | ✅ Looker per CEO/GM/CdG |
| **I8** (locality row-selection) | ✅ SNAPSHOT per chiave, nessuna selezione cross-fonte |

---

## Next step

Dopo user-review di questo spec, invocare `superpowers:writing-plans` per il
plan TDD eseguibile.
