# Motore di identificazione content-first — Design

**Data:** 2026-08-03 · **Stato:** approvato da Stefano (sessione 2026-08-03)
**Prossimo progetto (separato):** parser `NUMEROCAMERACLIENTI` → `f_ricavi_camera_anno`

## Contesto e obiettivo

Il 3 agosto Stefano ha passato tre file — `Data from Power BI (3).xlsx`,
`Data from Power BI (2).xlsx`, `data.xlsx` — chiedendo quale fosse quale e se
fossero già in casa. Erano tre `Produzione Netta Dashboard` di luglio 2026,
già in `f_ricavi_fb` dal 1° agosto, numeri identici al centesimo.

Il costo non è il download rifatto: è che **l'identità del file è dentro il file
e il sistema chiede all'umano di ridigitarla**. Ogni export Power BI porta in
fondo la cella `Applied filters` con struttura, anno e mese, e in prima riga la
firma delle colonne che dice quale report è. Il nome del file, invece, è rumore
generato dal browser.

Obiettivo: far riconoscere al sistema i report che oggi non sa riconoscere,
**senza toccare gli ingest che funzionano**.

## Stato di partenza (verificato, non assunto)

| | |
|---|---|
| Sources in `core/source_registry.yaml` | 46 (+2 fuori dal blocco `sources:`) |
| Sources con `detector_category` | 46 / 46 |
| Categorie distinte | 32 |
| Categorie con un detector scritto | 11 |
| Categorie senza detector | 21 |

La catena `classify → intake → promote` **esiste già** ed è cablata in
`hotelops capture`. Verificata in sessione su due file:

```
$ hotelops capture ~/Downloads/data.xlsx --dry-run
  classify:  type=ricavi_fb category=ricavi_fb lifecycle=SNAPSHOT (confidence: 95%)
  source:    POWERBI_RICAVIFB_ORTI_SNAPSHOT (table=f_ricavi_fb, policy=AUTO)

$ hotelops capture ~/Downloads/MPS_ORTI_Elenco_movimenti_03082026144122.xls
  classify:  type=banca_mps category=banca banca=MPS societa=ORTI (confidence: 85%)
  → f_banche_movimenti: 404 righe, 30/06 → 31/07
```

Il motore non manca. Manca la **copertura**: 11 categorie su 32.

### Il difetto centrale

`core/registry.yaml` contiene già 11 `file_types` con firme dichiarative in
cinque grammatiche (`sheets`, `columns`, `structure`, `filename`, `content`):

```yaml
ricavi_fb:
  signatures:
    - type: sheets
      required: ["Export"]
    - type: structure
      header_0_2: ["Classe", "Codice", "Descrizione Addebito"]
```

Il suo header dichiara: *«classify.py e orchestrate.py leggono da qui. Aggiungi
un tipo? Modifica SOLO questo file.»*

**È falso.** `grep` su tutto il repo: nessun riferimento a `core/registry.yaml`
nel codice — solo un commento in `ingest/banca/ingest.py` e uno script di
freshness. Le stesse firme sono riscritte a mano dentro le 11 funzioni Python
di `classify.py`. Due verità da tenere allineate a mano, e una delle due è già
morta.

Il layer dichiarativo è stato progettato una volta e mai collegato. Questo
design non lo inventa: **attacca il filo**.

### Il precedente che regge il design

Il commit `9a5e6ec` (2026-08-01) ha già applicato questa forma a mano su un
parser solo:

> *Gli export Power BI per struttura non hanno il prefisso struttura nel nome
> (sono tutti "Data from Power BI (N).xlsx"): detect_bu sul filename falliva.
> La BU si legge ora dalla cella "Applied filters" → CodiceHotel; il filename
> resta come fallback.*

Content-first dal contenuto, filename come rete. Senza motore, quella toppa va
riscritta dodici volte.

### Le firme sono distinguibili — verificato

15 report campionati da GCS, uno per source. L'header li separa tutti:

| Report | Foglio | Prefisso header |
|---|---|---|
| `andamento_prenotazioni` | Export | Giorno · CodiceHotel · Tipologia Venduta |
| `bookings_tipologia` | Export | Giorno · Tipologia Venduta · Camere |
| `dettaglio_prenotazioni` | Export | Giorno · Camere · ARB |
| `numero_camera_clienti` | Export | Camera · Volte · ARB |
| `occupazione_pms` | Export | Data · Cam. Totali · OOO |
| `produzione_pms` | Export | Classe · 01ROOM · 02FB |
| `ricavi_fb` | Export | Classe · Codice · Descrizione Addebito |
| `menu_engineering` | Export | M · Tipo · Sala |
| `consprev_mensile` | Export | Anno · Mese · Classe |
| `consprev_pax` | Export | Anno · Mese · Tipo |
| `consumi_powerbi` | Export | Data-Anno · Data-Mese · Data-Giorno · **Reparto** |
| `vendite_fb` | Export | Data-Anno · Data-Mese · Data-Giorno · **Sala** |

Nessuna collisione tra le 12 categorie vive. `consumi_powerbi` e `vendite_fb`
condividono le prime tre colonne e divergono alla quarta — vincolo che decide
la grammatica (§Decisione 1).

Un apparente conflitto è stato escluso: `POWERBI_BUDGETFORECAST_ORTI_APPEND` ha
lo stesso header a 23 colonne di `POWERBI_CONSPREV_ORTI_SNAPSHOT`, ma **non è una
source viva** — non esiste nel registry. È uno dei quattro nomi orfani rimasti
in `f_raw_objects` da maggio 2026 (§Fuori scope).

## Architettura

Un solo pezzo nuovo: un **valutatore di firme** che legge `core/registry.yaml`.

```
classify(path)
  ├─ 1. valutatore YAML   → match? → ClassificationResult
  ├─ 2. DETECTORS Python  → match? → ClassificationResult      (rete, invariata)
  └─ 3. unknown
```

Tre conseguenze volute:

**Il YAML vince.** Se una firma dichiarativa matcha, il detector Python della
stessa categoria non viene mai raggiunto. Migrare una categoria = scrivere la
firma in YAML e cancellare la funzione, in due passi separati e reversibili. In
questo giro non ne migriamo nessuna.

**Gli 11 detector contabili restano bit-per-bit come sono.** Il percorso che ha
ingerito l'estratto MPS continua a passare da lì. Se il valutatore nuovo ha un
bug, l'unica cosa che si rompe sono i Power BI, che oggi non funzionano comunque.

**`core/registry.yaml` smette di mentire.** Da configurazione morta che dichiara
di essere letta, diventa letta davvero. Le 11 firme già scritte lì restano
inerti finché la loro categoria non migra, ma non più contraddittorie: sono la
specifica di dove si sta andando.

## Componenti

### `ingest/signatures.py` (nuovo)

Tre responsabilità, nessuna in più:

1. caricare `core/registry.yaml` (`file_types`);
2. valutare le firme di una entry contro un file;
3. restituire la `detector_category` che matcha, o `None`.

**Non legge file da solo.** `classify.py` ha già `_read_xlsx_sample`,
`_read_xls_sample`, `_read_csv_sample`, `_cols_upper`, `_has_columns`, con un
comportamento definito su fogli mancanti e celle vuote. Il valutatore li riusa.
Scriverne di nuovi darebbe due modi diversi di leggere la prima riga di un xlsx
— il difetto che il design toglie.

**Tutte le firme di una entry devono matchare** perché la entry vinca.

### `classify.py` (modificato, additivo)

`classify()` prova il valutatore prima del loop `DETECTORS`. Le 11 funzioni
esistenti non vengono toccate.

Il `ClassificationResult` del percorso YAML si costruisce **derivando** da
`source_registry.yaml` per `detector_category`, non duplicando campi:

- `lifecycle` e parser dalla source risolta;
- `societa`: se tutte le source di quella categoria condividono la stessa
  società, la prende (i 12 Power BI sono tutti ORTI); se sono più d'una — come
  `banca`, 5 source su 2 società — resta `None` e decide la logica esistente;
- `confidence`: 0.95 fissa. Un match su foglio più prefisso d'header non è più
  debole di quello che `detect_ricavi_fb` già dichiara 0.95, e una manopola per
  entry non avrebbe nessuno che la gira.

### `core/registry.yaml` (esteso)

**11 entry nuove.** I report Power BI vivi sono 12, ma `ricavi_fb` ha già la sua
entry (è una delle 11 legacy) e resta com'è. Le nuove portano **solo le firme**:

```yaml
numero_camera_clienti:
  formats: [.xlsx]
  signatures:
    - type: sheets
      required: ["Export"]
    - type: structure
      header_prefix: ["Camera", "Volte", "ARB", "Infant"]

vendite_fb:
  formats: [.xlsx]
  signatures:
    - type: sheets
      required: ["Export"]
    - type: structure
      header_prefix: ["Data - Anno", "Data - Mese", "Data - Giorno", "Sala"]
```

Niente `lifecycle`, `bq_table`, `pipeline`, `dest_folder`: vivono già in
`source_registry.yaml` sotto lo stesso `detector_category`. Le 11 entry legacy
li duplicano perché precedono la separazione dei due file; non estendiamo la
duplicazione a 12 casi nuovi.

Catena di risoluzione:

```
firma → detector_category → source_resolver(categoria, società) → source_name → policy
```

## Decisioni

### 1. `header_prefix` di lunghezza libera, non `header_0_2`

La grammatica esistente codifica la lunghezza nel nome della chiave e si ferma a
tre colonne. Tre non bastano: `consumi_powerbi` e `vendite_fb` condividono le
prime tre e divergono alla quarta. È l'unica aggiunta alla grammatica, e serve a
un caso reale.

`header_0_2` resta supportato per la entry `ricavi_fb` esistente.

### 2. Nessun tipo di firma `footer`

Proposto e poi **ritirato**: verificato che l'header separa tutti e 12 i report
vivi. Un tipo di firma per un caso che non esiste sarebbe speculativo.

### 3. Il footer resta lavoro del parser

Struttura, anno e mese servono a chi scrive le righe, non a chi identifica il
file — e `ingest_occupazione_pms` e `ingest_ricavi_fb` già lo leggono così. Il
classificatore risponde *«che report è»*; il parser risponde *«di quale
struttura e quale periodo»*. Due domande, due posti.

### 4. Due entry che matchano lo stesso file sono un errore

Non un tie-break silenzioso, non il primo che vince: un errore esplicito. Se un
giorno due report diventano indistinguibili, il sistema si ferma e lo dice.

### 5. Fallback ai detector Python, non rimpiazzo

Il fallback non è una scorciatoia provvisoria: è la definizione onesta di «il
motore nuovo non ha ancora coperto quel caso». Un big-bang che migra tutte e 11
le categorie rischierebbe un ingest contabile funzionante per un guadagno che
il fallback dà comunque.

## Test

Quattro, e due verificano la **configurazione**, non il codice.

**Fixture sintetiche, non file reali.** Un xlsx generato al volo con il nome
foglio e la sola riga d'header è esattamente ciò che la firma legge. Una fixture
da poche righe per entry, invece di quindici xlsx di produzione nel repo: il
test descrive il contratto invece di trascinarsi dietro dati veri.

**Nessuna ambiguità nel registry.** Per ogni entry, la sua fixture sintetica non
deve matchare nessun'altra entry. È il test che vale di più: fallisce il giorno
in cui si aggiunge un report indistinguibile da uno esistente, invece di
lasciarlo scoprire in produzione.

**Ogni categoria risolve a una source.** Ogni `detector_category` in
`registry.yaml` deve trovare almeno una source in `source_registry.yaml`. Questo
test, se fosse esistito, avrebbe mostrato i quattro nomi orfani a maggio.

**Regressione sugli 11 legacy.** Per ogni categoria contabile, il file campione
continua a classificarsi come prima. È la prova che la rete regge — cioè la
premessa dell'intero design.

## Fuori scope (dichiarato)

- **I detector Python non si toccano.** Nessuna migrazione in questo giro.
- **I 4 `source_name` orfani** in `f_raw_objects` (`POWERBI_BUDGETFORECAST_ORTI_APPEND`
   6 obj, `POWERBI_BOOKINGS_ORTI_APPEND` 3, `POWERBI_PRODUZIONE_ORTI_APPEND` 3,
  `MANUAL_BUDGET_ORTI_SNAPSHOT` 1, tutti fermi a maggio 2026): debito reale, altra
  sessione.
- **I due blocchi `ESOLVER_PARTITE_APERTE_*` a colonna 0** invece che dentro
  `sources:` — config morta, invisibile al resolver. I vivi sono
  `ESOLVER_PARTITE_*_SNAPSHOT` e funzionano. Cosmetico.
- **I campi legacy delle 11 entry** (`dest_folder`, `split_by_societa`, `bq_table`)
  restano dove sono.
- **`orchestrate.py` e il percorso rclone**, che hanno il loro cutover pendente.
- **I parser dei report identificati.** Questo design fa riconoscere i file, non
  li scrive in tabella. `NUMEROCAMERACLIENTI` è qui una delle dodici firme; il suo
  parser è il progetto successivo.

## Conseguenze

**Aggiungere il tredicesimo report diventa un blocco YAML** invece di una
funzione Python più un blocco YAML che nessuno legge.

**I parser fermi su #87** (`DETTAGLIOPRENOTAZIONI`, `CONSPREVPAX`, `STAMPACASSA`)
perdono metà del lavoro: identificazione e risoluzione della source arrivano
gratis, resta solo la scrittura in tabella.

**`hotelops capture` diventa la porta d'ingresso vera.** Si passano N file e il
sistema dice cosa sono; il dedup MD5 all'intake dice se ci sono già. Il caso che
ha aperto la sessione — tre file riscaricati inutilmente — smette di poter
accadere in silenzio.

## Riferimenti

- Sessione: `vault/HotelOps/sessions/2026-08-03_bp32_atterraggio_camere_nuove_ingest.md`
- Precedente content-first: commit `9a5e6ec`
- Workstream: `vault/HotelOps/workstreams/INGEST_CHIUSURE.md`
- Invariante toccata: nessuna (`loop_targets == [] ⇔ RAW_ONLY` resta intatta —
  questo design non promuove nulla)
