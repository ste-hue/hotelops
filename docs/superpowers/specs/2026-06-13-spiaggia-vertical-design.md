# Vertical Spiaggia — design

**Data:** 2026-06-13
**Stato:** approvato (design), pre-implementazione
**Autore:** Stefano + Claude

## Contesto

Spiagge.it (gestionale prenotazioni della concessione balneare) esporta un dump JSON
completo del database di booking. Il file di partenza:
`Booking Settings Panorama Beach June 13 2026.json` (~17.5 MB), 5 tabelle sotto prefisso
`it-sa-84010-panorama-beach_`:

| Tabella sorgente | Righe | Colonne | Note |
|---|---|---|---|
| reservations | 33.805 | 82 | prenotazioni ombrellone/lettino |
| cash_flows | 12.979 | 10 | movimenti cassa (incassi/storni) |
| receipts | 3.756 | — | ricevute — **fase 2** |
| res_service | 7.251 | — | servizi su prenotazione — **fase 2** |
| spots | 187 | — | mappa postazioni (136 ombrelloni + 51 elementi) |

Ogni tabella è `{"columns":[...], "rows":[[...]]}`.

**Totali verificati** (cash_flows con coercion stringa→float): somma reale 532.904 €
(method 14 = 300.472; method 1 = 252.092; None = −20.651 storni). receipts.total = 126.715 €.

**Insight noto:** le prenotazioni hotel-linked sono ~0 nel 2020-21 e quasi tutte dal 2022+
(la spiaggia è stata bundlata nei soggiorni hotel da quell'anno).

## Obiettivo

`spiaggia` diventa il **3° vertical** di hotelops (dopo `condges` e `reviews`):

1. **Dati canonici in BigQuery** — i dump Spiagge.it organizzati e interrogabili.
2. **App interna cercabile** — Streamlit vestito Panorama Beach, per Stefano/direzione,
   per trovare prenotazioni (cliente/email/ombrellone/periodo) e leggere KPI.
3. **Routine dedup/update** — quando Stefano dumpa un JSON nuovo, il sistema dedupa
   (file identico = no-op) e aggiorna (dump nuovo = nuova verità, full-replace).

### Scope

- **In scope (Core 3):** `reservations`, `cash_flows`, `spots` → canonical.
- **Fuori scope (fase 2):** `receipts`, `res_service` — restano nel raw JSON in GCS,
  promuovibili più avanti senza re-intake.

## Decisioni bloccate

| Decisione | Scelta |
|---|---|
| Artefatto | Viste BQ `v_spiaggia_*` (data layer) + app Streamlit |
| Audience | Interna (Stefano/direzione) — tool operativo |
| Stack app | Streamlit, CSS custom "vestito Panorama Beach" (non il Design System web reale) |
| Modello dump | Sempre completo (ogni export = DB intero) |
| Lifecycle | SNAPSHOT full-replace per tabella |
| Promozione | **MANUAL** (full-replace distruttivo → promote esplicito) |
| Dimensioni | societa=`INTUR`, business_unit=`LIDO`, location=`LIDO`, oggetto=`spot_name`, funzione=`null` |
| Fan-out | 1 file → 1 parser → 3 tabelle canonical |

## Architettura

```
JSON dump (Spiagge.it, completo)
   │ hotelops intake --source-name SPIAGGEIT_SPIAGGIA_INTUR_SNAPSHOT
   ▼
GCS gs://hotelops-raw/SPIAGGEIT_SPIAGGIA_INTUR_SNAPSHOT/YYYY/MM/   + f_raw_objects (content-hash dedup)
   │ hotelops promote --raw-object-id <id>   (MANUAL)
   ▼
ingest/flussi/ingest_spiaggia.py   (1 parser, fan-out 1→3, full-replace)
   ├─► f_spiaggia_reservations   (natural key: id)
   ├─► f_spiaggia_cash_flows      (natural key: id)
   └─► f_spiaggia_spots           (natural key: id)
   │
   ▼
viste  v_spiaggia_prenotazioni / _cassa / _occupazione / _kpi
   │
   ▼
verticals/spiaggia/app.py   (Streamlit interna, Panorama Beach)
```

**Separazione di responsabilità:**
- Parser in `ingest/flussi/ingest_spiaggia.py` — coerente con gli altri parser lineage,
  invocabile via `python -m ingest.flussi.ingest_spiaggia` (richiesto da `promote`).
- Logica vertical (app, eventuali helper di query) in `verticals/spiaggia/`.

## 1. Lineage / source registry

Nuova entry in `core/source_registry.yaml`:

```yaml
SPIAGGEIT_SPIAGGIA_INTUR_SNAPSHOT:
  system: SPIAGGEIT
  dataset: SPIAGGIA
  dataset_label: "Dump completo prenotazioni Spiagge.it (Panorama Beach)"
  societa: INTUR
  business_unit: LIDO
  lifecycle: SNAPSHOT
  canonical_table: f_spiaggia_reservations   # primaria; il parser scrive anche cash_flows + spots
  parser_module: ingest.flussi.ingest_spiaggia
  natural_key: [id]
  loop_targets: [cash_control]               # la cassa spiaggia alimenta il controllo cassa INTUR
  promotion_policy: MANUAL
  detector_category: spiaggia_dump
  raw_storage:
    backend: gcs
    bucket: hotelops-raw
    path_template: "spiaggeit/spiaggia/INTUR"
```

- `loop_targets` non vuoto ⇒ **non RAW_ONLY** ⇒ può promuovere (invariante hard rispettata:
  `loop_targets == [] ⇔ promotion_policy == RAW_ONLY`).
- `canonical_table` dichiara la primaria; il fan-out a 3 tabelle è legittimo perché `promote`
  verifica solo l'exit code del parser, non quale tabella scrive.

## 2. Tabelle canonical (fan-out 1→3, full-replace)

Tutte e 3 SNAPSHOT full-replace, ogni riga porta le 5 dimensioni + `raw_object_id` FK.

**Full-replace semantics:** dato che ogni dump è il DB completo, il parser **tronca e
reinserisce** ogni tabella (DELETE totale scoped alla source + INSERT di tutte le righe del
dump). Niente merge per-id incrementale: il dump nuovo sostituisce integralmente il vecchio.
Il conteggio righe pre/post è loggato e verificato (§6) per evitare over-delete silenzioso.

### f_spiaggia_reservations (natural key: `id`)

Colonne canoniche (sottoinsieme curato delle 82 sorgenti):

- **identità:** `id`, `license_code`
- **postazione:** `spot_type`, `spot_name`
- **stato:** `status`, `seasonal` (bool), `deleted` (bool), `online` (bool)
- **periodo:** `start_date` (unix→DATE), `end_date` (unix→DATE)
- **composizione:** `beds`, `chairs`
- **cliente:** `first_name`, `last_name`, `email`, `phone`
- **prezzi:** `list_total`, `paid_total`, `gross_booking_value`, `discount`
- **link hotel:** `hotel` (bool/id), `hotel_room`
- **canale:** `utm_source`, `utm_medium`, `utm_campaign`
- **fattura:** i campi invoice presenti nelle 82 colonne sorgente (flag fatturazione +
  riferimento documento); il set esatto si fissa nel piano profilando le colonne `invoice*`
- **audit:** `created_at`, `updated_at` (unix→TIMESTAMP)
- **dimensioni:** `societa_id=INTUR`, `business_unit_id=LIDO`, `location_id=LIDO`,
  `oggetto_id=spot_name`, `funzione_id=NULL`, `raw_object_id`

### f_spiaggia_cash_flows (natural key: `id`)

- `id`, `reservation_id` (FK → reservations.id)
- `method` (codice intero grezzo), `method_label` (decodificato via `d_spiaggia_metodi`)
- `amount` (stringa→FLOAT, **segno preservato**: negativo = storno)
- `date` (unix→DATE), `receipt_id`, `invoice_id`, `deleted` (bool)
- `created_at`, `updated_at`
- dimensioni come sopra (`oggetto_id` ereditato dalla reservation collegata o `NULL` se assente)

### f_spiaggia_spots (natural key: `id`)

Tabella-dimensione (la mappa fisica della spiaggia):

- `id`, `uuid`, `name`, `type`, `sector`, `price_list_id`, `pos_x`, `pos_y`
- dimensioni come sopra (`oggetto_id=name`)

### Dimensione di supporto: d_spiaggia_metodi

`method` arriva come codice intero (osservati: 1, 14, 2, 3). La legenda Spiagge.it non è nota.

- Si crea `d_spiaggia_metodi` (codice → label) come CSV in `core/bq/dimensioni/`,
  inizialmente con i codici osservati e label `TBD`/best-guess.
- `v_spiaggia_cassa` mostra il codice grezzo finché la mappa non è confermata.
- Riempire la legenda è un follow-up (chiedere a Spiagge.it o dedurre dai receipts in fase 2).

## 3. Viste BQ `v_spiaggia_*`

| Vista | Contenuto |
|---|---|
| `v_spiaggia_prenotazioni` | reservations arricchite: join `spots` per `sector`, ricavo calcolato, notti (`end-start`), flag `online`/`hotel`, stagione. Esclude `deleted`. |
| `v_spiaggia_cassa` | cash_flows per giorno × `method_label`, somma netta (storni inclusi col segno). Esclude `deleted`. |
| `v_spiaggia_occupazione` | occupazione postazioni per giorno: esplode i range `[start_date, end_date]` × `spots`, % occupazione su 136 ombrelloni. |
| `v_spiaggia_kpi` | KPI mensili: occupazione %, ricavo, cassa incassata, scontrino medio, quota `online %`, quota `hotel-linked %`. |

Le viste filtrano le righe spazzatura (date fuori range plausibile, es. 1970/2010) e
`deleted=TRUE` per le metriche operative. Il raw resta in tabella canonical col flag.

## 4. App Streamlit `verticals/spiaggia/app.py`

Interna, "vestita Panorama Beach" via injection CSS (approssimazione, non il Design System web).

- **Brand CSS:** sky cyan `#57c1e8`, navy `#003764`, ivory `#fbf9f5`; font Cinzel /
  Cormorant Garamond / Jost via Google Fonts.
- **Header KPI** (da `v_spiaggia_kpi`): occupazione, cassa, ricavo, online %, hotel-linked %.
- **Ricerca/filtri** (da `v_spiaggia_prenotazioni`): cliente (nome/email/telefono),
  ombrellone (`spot_name`), periodo (date range), stato, canale → tabella cercabile/paginata.
- **Grafici minimi:** trend occupazione (`v_spiaggia_occupazione`), cassa per metodo
  (`v_spiaggia_cassa`), ricavo per settore (`v_spiaggia_prenotazioni`).
- Read-only, query cached (`@st.cache_data` ttl=300), pattern allineato a
  `audit_consumi_dashboard.py` / `reviews/app.py`.
- Lancio: `streamlit run verticals/spiaggia/app.py`.

## 5. Routine dedup / update

1. **Nuovo dump** → `hotelops intake <file.json> --source-name SPIAGGEIT_SPIAGGIA_INTUR_SNAPSHOT`
   - Dedup file-level via content-hash MD5 in `f_raw_objects`: file byte-identico = `deduped`
     (no-op, nessun reprocessing).
2. **`hotelops promote --raw-object-id <id>`** (MANUAL) → parser full-replace delle 3 tabelle.
   - Il dump nuovo è la nuova verità: sostituisce integralmente il precedente.
3. **Verifica §6**.

## 6. Verifica (output-based, post-promote)

```sql
-- FK coverage: ogni riga DEVE avere raw_object_id
SELECT COUNT(*) tot, COUNTIF(raw_object_id IS NOT NULL) con_fk
FROM `hotelops-suite.hotelops.f_spiaggia_reservations`;
-- atteso: tot == con_fk, tot ≈ 33.805 (al netto deleted/junk del dump)

-- Integrità FK cash_flows → reservations
SELECT COUNTIF(r.id IS NULL) orfani
FROM `hotelops-suite.hotelops.f_spiaggia_cash_flows` c
LEFT JOIN `hotelops-suite.hotelops.f_spiaggia_reservations` r ON c.reservation_id = r.id;

-- Quadratura cassa: somma amount ≈ 532.904 € sul dump di riferimento
SELECT ROUND(SUM(amount),0) FROM `hotelops-suite.hotelops.f_spiaggia_cash_flows`;

-- Stato lineage: atteso PROMOTED
SELECT * FROM `hotelops-suite.hotelops.v_raw_objects_current` WHERE raw_object_id = '<id>';
```

Row count pre/post DELETE loggato dal parser per escludere over-delete.

## Caveat noti

- **Legenda metodi pagamento** non confermata (`d_spiaggia_metodi` con label TBD).
- **CASSA, non COMPETENZA:** `cash_flows` è dimensione CASSA. Non si riconcilia ancora
  automaticamente con Esolver INTUR — è un loop futuro (`cash_control` è il loop_target
  dichiarato, ma il bridge effettivo è fase successiva).
- **Righe spazzatura** (date 1970/2010, record isolati): incluse in canonical con flag,
  filtrate nelle viste operative.
- **receipts + res_service** restano nel raw GCS: promuovibili in fase 2 senza re-intake.

## Fasi

1. **Fase 1 (questo spec):** registry entry + parser fan-out 1→3 + 3 tabelle canonical +
   `d_spiaggia_metodi` + 4 viste + app Streamlit + verifica end-to-end sul dump del 2026-06-13.
2. **Fase 2 (futuro):** promuovere `receipts` + `res_service`; confermare legenda metodi;
   bridge cassa spiaggia → `cash_control` INTUR.
