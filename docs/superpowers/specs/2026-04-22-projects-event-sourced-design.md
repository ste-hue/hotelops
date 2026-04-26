# 2026-04-22 — Projects (event-sourced) Step 1 design

**Date:** 2026-04-22
**Status:** Draft v1
**Author:** Stefano + Claude
**Supersedes:** `2026-04-20-projects-mvp-design.md` (da archiviare post-approval)

---

## 0. TL;DR

Step 1 individua il **flow** del progetto: `f_progetto_voci` (identità) + `f_progetto_eventi` (APPEND log) da cui si derivano le **4 domande manageriali** COSA / CHI / QUANTO / QUANDO. Validato su **2 progetti reali** (HPAN25PIANO1 maturo + SPIAGGIA_LOTTO7 early-stage) con 10 voci totali e 5 tipi di evento. Niente UI, CLI, LLM, writeback Drive — quelli sono Fase 2+.

Il principio: *la cassa nasce dall'impegno, non dalla fattura*. Il budget è un numero che cambia nel tempo, tracciato come sequenza di eventi; gli stati si derivano, non si memorizzano.

## 1. Perché event log (non 3 tabelle-per-lente, non 7 entità normalizzate)

Ogni alternativa ragionata contro le 4 domande:

| Approccio | COSA | CHI | **QUANTO** | QUANDO | Verdetto |
|---|---|---|---|---|---|
| Event log (2 tab + view) | ✓ | ✓ | **nativo** (ORDER BY data) | view su latest IMPEGNO | **scelto** |
| 3 tab per lente (concept v1 proposal) | ✓ | serve 4ª tab documenti (fuori-lente) | UNION 3 tabelle | ✓ | tabella in più per scopo non-I4 |
| 7 entità normalizzate (spec S2) | ✓ | ✓ | join 7-way complex | ✓ | scope creep prima del validation |

La domanda decisiva è **QUANTO** (Budget Evolution): concept PROGETTO.md §"Vista C" la definisce come timeline *"da stima orfana → preventivo → contratto → fattura, con tracking delta"*. Questo è letteralmente event log: `ORDER BY data_evento` e hai la timeline.

### Conformità invariants

- **I1** — `ProgettoEvento` base + discriminated union Pydantic su `tipo_evento` (5 sub-model). Validation gate nativo per tipo.
- **I2** — `f_progetto_eventi` APPEND, `f_progetto_voci`+`d_progetti` SNAPSHOT. Legittimo: identità della voce può cambiare attributi (qty, descrizione) senza essere lifecycle; la storia del lifecycle vive negli eventi.
- **I4** — le 3 lenti IMPEGNO / COMPETENZA / CASSA sono **derivate** dagli eventi, non colonne statiche su tabelle separate.
- **I7** — audience Step 1: Stefano Jr (owner CapEx). Audience Fase 2: Rosa (via forward-flow a `v_previsione_cassa`).
- **I8** — row-selection (ultimo IMPEGNO vince, dedup payment schedule, ecc.) vive in `v_progetto_voci_stato`, non nei consumer.

## 2. Schema

### 2.1 `d_progetti` — SNAPSHOT per `progetto_id`

```python
class Progetto(BaseModel):
    progetto_id: str                  # HPAN25PIANO1, SPIAGGIA_LOTTO7
    nome: str                         # "Camere Primo Piano", "Spiaggia Lotto 7 Maiori"
    societa_owner_id: Literal["ORTI", "INTUR"]  # possessore asset finale
    business_unit_id: str             # HOTEL, LIDO
    struttura: str | None             # "Hotel Panorama", "Stabilimento Lido 7"
    budget_cap_eur: Decimal
    data_inizio: date
    data_fine_prevista: date | None
    stato: Literal["PIANIFICATO", "IN_CORSO", "CHIUSO", "ANNULLATO"]
    owner: str                        # "Stefano Della Pietra Jr"
    drive_root_url: str | None        # link root cartella Drive progetto
```

### 2.2 `f_progetto_voci` — SNAPSHOT per `voce_id`

Identità minima di una riga di scope (= riga Excel "cosa da comprare").

```python
class ProgettoVoce(BaseModel):
    voce_id: str                      # composito {progetto_id}.{seq} o UUID
    progetto_id: str                  # FK Progetto
    codice_interno: str               # "001", "002" come nel seed CSV
    descrizione: str                  # "Opere murarie strutturali piano 1"
    categoria: str                    # stringa libera: EDILE, IMPIANTI_EL, PORTE, OMBRELLONI, ...
    qta: Decimal | None
    unita: str | None                 # pz, mq, cad, mq, set
    fornitore_id: str | None          # FK d_anagrafica_fornitori, popolato alla SCELTA
    societa_pagante_id: Literal["ORTI", "INTUR"]  # default INTUR, ORTI per opex (PM fee)
    note: str | None
```

SNAPSHOT legittimo: se una voce cambia qty o descrizione, non è un lifecycle event — è correzione anagrafica.

### 2.3 `f_progetto_eventi` — APPEND immutabile

```python
class ProgettoEvento(BaseModel):
    evento_id: str                    # UUID
    voce_id: str                      # FK ProgettoVoce
    progetto_id: str                  # denorm per query fast
    tipo_evento: Literal[
        "PREVENTIVO",  # preventivo ricevuto da fornitore
        "IMPEGNO",     # commitment firmato (include payment schedule)
        "FATTURA",     # fattura ricevuta
        "PAGAMENTO",   # bonifico uscito
        "DOCUMENTO"    # allegato Drive (qualsiasi tipo, inclusi sopra)
    ]
    data_evento: date                 # quando è accaduto il fatto reale
    data_registrazione: datetime      # quando abbiamo registrato l'evento (audit)
    importo_eur: Decimal | None       # importo rilevante per il tipo (IVA esclusa convenzionalmente)
    fornitore_id: str | None          # denorm; per PREVENTIVO = chi ha quotato; per FATTURA/PAGAMENTO = chi riceve
    metadata: PreventivoMeta | ImpegnoMeta | FatturaMeta | PagamentoMeta | DocumentoMeta  # discriminated union
    file_sorgente: str | None         # drive_url del file che ha generato l'evento (convenience)
```

BigQuery column `metadata` è JSON. La scrittura passa sempre da Pydantic (I1 strict).

## 3. I 5 tipi di evento — schema `metadata`

### 3.1 `PREVENTIVO`

```python
class PreventivoMeta(BaseModel):
    numero_preventivo: str | None     # "SQ221807-2", "25/00392"
    data_preventivo: date | None
    validita_fino_a: date | None
    articolo: str                     # "Sand Desk Brown Inground Wood"
    codice_articolo: str | None       # "NRO510-0611"
    stato_preventivo: Literal["RICEVUTO", "ACCETTATO", "RIFIUTATO", "SCADUTO"]
    note: str | None
```

Una voce può avere **N** eventi PREVENTIVO (confronto offerte). `fornitore_id` sull'evento identifica chi ha quotato.

### 3.2 `IMPEGNO`

```python
class Rata(BaseModel):
    seq: int
    data_prevista: date
    importo_eur: Decimal
    descrizione: str                  # "Acconto 30%", "SAL 40%", "Saldo a 60gg"
    stato: Literal["PIANIFICATA", "EMESSA", "PAGATA", "ANNULLATA"]

class ImpegnoMeta(BaseModel):
    from_preventivo_evento_id: str | None  # quale PREVENTIVO è diventato IMPEGNO
    numero_contratto: str | None      # "864" (Dierre), None per preventivo-verbale
    data_firma: date
    rate: list[Rata]                  # piano pagamento completo
    stato_commitment: Literal["FIRMATO", "IN_CORSO", "CHIUSO", "ANNULLATO"]
    motivo_variazione: str | None     # popolato solo se è un IMPEGNO successivo sulla stessa voce
```

Una voce può avere **più** eventi IMPEGNO. **Latest vince** nella view stato corrente (I8). Casi d'uso:
- **Commitment iniziale** — primo IMPEGNO dopo un PREVENTIVO accettato.
- **Overrun / scope change** — 2° IMPEGNO con `importo_eur` maggiorato (es. AMCN +37K → `motivo_variazione="Overrun amianto, Ft 02-26"`).
- **Riprogrammazione** — 2° IMPEGNO con stesso `importo_eur` ma nuove `rate` (ritardo consegna).

### 3.3 `FATTURA`

```python
class FatturaMeta(BaseModel):
    numero_fattura: str               # "IT00126V0001851", "FPR 31/26"
    data_emissione: date
    data_ricezione: date | None
    tipo_doc: Literal["FT", "FT-RC", "NC"]  # FT=Fattura, FT-RC=Reverse Charge, NC=Nota Credito
    condizioni_pagamento: str         # "Bonifico 30gg", "SDD/RID 60gg", "Bonifico 90gg DF FM"
    data_scadenza: date | None
    movimento_row_hash: str | None    # hash riga f_movimenti_contabili (UNIQUE lì); None se fattura non ancora in Esolver
    copre_rate: list[int]             # seq rate IMPEGNO che questa fattura sta fatturando (può essere vuoto)
```

`movimento_row_hash` linka a `f_movimenti_contabili` **senza duplicare** la fattura: la canonical resta lì (I8 rispetta `f_movimenti_contabili` come SSOT per movimenti contabili).

### 3.4 `PAGAMENTO`

```python
class PagamentoMeta(BaseModel):
    data_valuta: date
    metodo: Literal["BONIFICO", "SDD", "RID", "ASSEGNO", "CASSA"]
    importo_pagato_eur: Decimal       # ridondante con evento.importo_eur, esplicito qui per leggibilità
    copre_fatture: list[str]          # lista evento_id FATTURA coperti da questo pagamento
    banca_movimento_hash: str | None  # hash riga f_banche_movimenti
```

Un PAGAMENTO può coprire 1..N fatture. `banca_movimento_hash` linka a `f_banche_movimenti` quando la pipeline bancaria ha già catturato il movimento (canonical CASSA).

### 3.5 `DOCUMENTO`

```python
class DocumentoMeta(BaseModel):
    tipo_doc: Literal["PREVENTIVO", "CONTRATTO", "ORDINE", "FATTURA", "SAL", "PLANIMETRIA", "EMAIL", "ALTRO"]
    drive_url: str                    # "https://drive.google.com/..."
    file_name: str
    file_hash_md5: str                # dedup
    correlato_evento_id: str | None   # es. il PDF preventivo che ha generato l'evento PREVENTIVO
```

Un DOCUMENTO è allegato a una voce; opzionalmente correlato a un altro evento. Non è "una lente I4" — è evidenza documentale. Risposta nativa a "CHI / con quale evidenza?".

## 4. Le 4 domande manageriali → view derivate

### COSA — `v_progetto_voci_stato` (Register)

Per voce: stato derivato + fornitore scelto + totali impegnato/fatturato/pagato.

```sql
CREATE OR REPLACE VIEW v_progetto_voci_stato AS
WITH latest_impegno AS (
  SELECT voce_id, importo_eur, data_evento, evento_id, metadata
  FROM (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY voce_id ORDER BY data_evento DESC, data_registrazione DESC) AS rn
    FROM `hotelops-suite.hotelops.f_progetto_eventi`
    WHERE tipo_evento = 'IMPEGNO'
  ) WHERE rn = 1
),
totali_fattura AS (
  SELECT voce_id, SUM(importo_eur) AS importo_fatturato_eur, COUNT(*) AS n_fatture
  FROM `hotelops-suite.hotelops.f_progetto_eventi`
  WHERE tipo_evento = 'FATTURA' GROUP BY voce_id
),
totali_pagamento AS (
  SELECT voce_id, SUM(importo_eur) AS importo_pagato_eur
  FROM `hotelops-suite.hotelops.f_progetto_eventi`
  WHERE tipo_evento = 'PAGAMENTO' GROUP BY voce_id
),
n_preventivi AS (
  SELECT voce_id, COUNT(*) AS n_preventivi
  FROM `hotelops-suite.hotelops.f_progetto_eventi`
  WHERE tipo_evento = 'PREVENTIVO' GROUP BY voce_id
)
SELECT
  v.voce_id,
  v.progetto_id,
  v.codice_interno,
  v.descrizione,
  v.categoria,
  v.fornitore_id AS fornitore_scelto_id,
  v.societa_pagante_id,
  li.importo_eur AS importo_impegnato_eur,
  li.data_evento AS data_impegno,
  COALESCE(tf.importo_fatturato_eur, 0) AS importo_fatturato_eur,
  COALESCE(tp.importo_pagato_eur, 0) AS importo_pagato_eur,
  COALESCE(li.importo_eur, 0) - COALESCE(tf.importo_fatturato_eur, 0) AS residuo_impegno_eur,
  COALESCE(tf.importo_fatturato_eur, 0) - COALESCE(li.importo_eur, 0) AS delta_overrun_eur,
  COALESCE(np.n_preventivi, 0) AS n_preventivi,
  COALESCE(tf.n_fatture, 0) AS n_fatture,
  CASE
    WHEN li.importo_eur IS NOT NULL
         AND COALESCE(tp.importo_pagato_eur, 0) >= li.importo_eur THEN 'CHIUSO'
    WHEN COALESCE(tf.importo_fatturato_eur, 0) > 0 THEN 'IN_CORSO_FATTURATO'
    WHEN li.importo_eur IS NOT NULL THEN 'IMPEGNATO'
    WHEN COALESCE(np.n_preventivi, 0) > 0 THEN 'IN_VALUTAZIONE'
    ELSE 'IDENTIFICATO'
  END AS stato
FROM `hotelops-suite.hotelops.f_progetto_voci` v
LEFT JOIN latest_impegno li USING (voce_id)
LEFT JOIN totali_fattura tf USING (voce_id)
LEFT JOIN totali_pagamento tp USING (voce_id)
LEFT JOIN n_preventivi np USING (voce_id)
```

### CHI — `v_progetto_preventivi` (Documents — Fase 2)

Per voce: tutti i PREVENTIVO + fornitore + DOCUMENTO allegati. Non ancora in Step 1 (derivabile con query ad-hoc sugli eventi).

### QUANTO — `v_progetto_timeline` (Budget Evolution — Fase 2)

Event log filtrato e arricchito con running total per voce.
```sql
SELECT voce_id, data_evento, tipo_evento, importo_eur,
       SUM(CASE WHEN tipo_evento='IMPEGNO' THEN importo_eur ELSE 0 END)
         OVER (PARTITION BY voce_id ORDER BY data_evento, data_registrazione) AS impegno_cumulato_eur
FROM f_progetto_eventi ORDER BY voce_id, data_evento, data_registrazione
```

### QUANDO — `v_progetto_payment_schedule` (Payment Planning — Fase 2)

Esplode `metadata.rate` dall'ultimo IMPEGNO per voce, raggruppa per `(societa_pagante × mese)`. Bridge a `f_piano_finanziario_input` fonte=PROGETTI.

**Fase 2 roadmap**: le 3 view sopra + forward-flow solver.

## 5. Seed: 10 voci su 2 progetti

**Validation criterion**: lo *stesso* schema copre HPAN25PIANO1 (maturo, commitment+fatture) e SPIAGGIA_LOTTO7 (early-stage, solo preventivi in valutazione). Se il flow regge entrambi → trovato.

### 5.1 HPAN25PIANO1 — 5 voci

Progetto: `societa_owner=INTUR, bu=HOTEL, cap=1.200.000, drive_root=investimenti2026/HPAN25PIANO1/`

| voce_id | descrizione | categoria | societa_pag | eventi seed |
|---|---|---|---|---|
| `HPAN25PIANO1.001` | Opere murarie strutturali piano 1 (AMCN) | EDILE | INTUR | 1 PREVENTIVO → 1 IMPEGNO(375K) → 1 IMPEGNO(413K, motivo=overrun amianto) → 3 FATTURA (FPR 23/24/31) → 0 PAGAMENTO |
| `HPAN25PIANO1.002` | Impianti elettrici (STE) | IMPIANTI_EL | INTUR | 1 PREVENTIVO → 1 IMPEGNO(107K) → 1 FATTURA parziale |
| `HPAN25PIANO1.008` | Direzione lavori (Amalia Pisacane) | CONSULENZA | INTUR | 1 PREVENTIVO solo (PREVENTIVO_PENDING da walkthrough) |
| `HPAN25PIANO1.010` | Project Management (Hospitality Project) | CONSULENZA | **ORTI** | 1 PREVENTIVO solo (testa multi-società) |
| `HPAN25PIANO1.013` | Falegnameria armadi (Rino Cuomo) | ARREDI_CUSTOM | INTUR | 0 eventi (voce con stima ma nessun preventivo ricevuto) |

**Casi testati**: happy path commitment→fattura (V2), overrun via 2° IMPEGNO (V1), preventivo sospeso (V3), multi-società (V4, ORTI invece di INTUR), voce orfana senza eventi (V5).

### 5.2 SPIAGGIA_LOTTO7 — 5 voci

Progetto: `societa_owner=INTUR, bu=LIDO, cap=~490.000 (stima scenario MAX da v2), drive_root_url=null` (struttura Drive verrà creata in Fase 2 reversed; per Step 1 i PDF stanno in `~/Desktop/WORK/metodo-progetti/spiaggia_progetto/PREVENTIVI/`)

| voce_id | descrizione | categoria | societa_pag | eventi seed |
|---|---|---|---|---|
| `SPIAGGIA_LOTTO7.001` | Ombrelloni Pagoda 164pz | OMBRELLONI | INTUR | **4 PREVENTIVO** (Armagi 31.3K, Magnani 35.6K, Maffei 37.6K, Azzolini 122K) — testa confronto offerte |
| `SPIAGGIA_LOTTO7.002` | Arredo Ethimo (cabane+sedie+tavolini+lampade) | ARREDI | INTUR | 1 PREVENTIVO (84.8K) + 1 DOCUMENTO (PDF scansionato) — testa DOCUMENTO allegato a PREVENTIVO |
| `SPIAGGIA_LOTTO7.005` | Giochi da spiaggia (Kompan) | GIOCHI | INTUR | 1 PREVENTIVO (13.5K) con `metadata.note = "50% conferma + 50% a 30gg"` — testa cond. pagamento catturata già in preventivo |
| `SPIAGGIA_LOTTO7.011` | Vela motorizzata (Similis) | STRUTTURA | INTUR | 1 PREVENTIVO (26.1K) — caso base voce singola |
| `SPIAGGIA_LOTTO7.012` | Buvette | STRUTTURA | INTUR | 0 eventi (voce con stima ma nessun fornitore) |

**Casi testati**: confronto N offerte stessa voce (S1), DOCUMENTO correlato a PREVENTIVO (S2), termini pagamento già nel preventivo pre-commitment (S3), happy path singolo preventivo (S4), voce orfana no fornitore (S5).

### 5.3 Totale seed

- 2 righe in `d_progetti`
- 10 righe in `f_progetto_voci`
- 19 righe in `f_progetto_eventi`:
  - HPAN25PIANO1 (11 eventi): 4 PREVENTIVO + 3 IMPEGNO + 4 FATTURA + 0 PAGAMENTO + 0 DOCUMENTO
  - SPIAGGIA_LOTTO7 (8 eventi): 7 PREVENTIVO + 0 IMPEGNO + 0 FATTURA + 0 PAGAMENTO + 1 DOCUMENTO

**Smoke test finale**: `v_progetto_voci_stato` torna 10 righe con stati correttamente derivati.

### 5.4 Multi-progetto: generalizzazione

Lo schema regge N progetti **senza modifiche** di tabelle, view, modelli Pydantic. Aggiungere un nuovo progetto post-Step 1 = INSERT in `d_progetti` + INSERT in `f_progetto_voci` + INSERT in `f_progetto_eventi`. Nessuna migration, nessun deploy, nessun codice nuovo.

#### Progetti futuri (esempi concreti)

| progetto_id (proposta) | nome | societa_owner | bu | aspetti differenti vs Step 1 |
|---|---|---|---|---|
| `LIDO_2026_BANDO7` | Spiaggia Lotto 7 Maiori (= SPIAGGIA_LOTTO7 ridenominato) | INTUR | LIDO | bu=LIDO (nuovo); possibile multi-società pagante (gestione lido) |
| `HPAN_2027_TERRAZZA` | Terrazza Hotel Panorama | INTUR | HOTEL | scope strutturale, planimetria dedicata, ~30-50 voci |
| `HPAN_2027_52CAMERE` | Ristrutturazione 52 camere | INTUR | HOTEL | scala 5× HPAN25PIANO1; ~150-200 voci; possibile sub-fasi |
| `RESIDENCE_2027_X` | Rinnovamento Residence (futuro) | ORTI? | RESIDENCE | bu RESIDENCE mai usato; ownership da chiarire |

Nessun cambio di schema necessario per ognuno.

#### Convenzione naming `progetto_id` (non vincolante in schema, raccomandata)

`{STRUTTURA_CODE}_{ANNO}_{SCOPE_SLUG}`:
- struttura code: `HPAN`, `LIDO`, `RESIDENCE`, `CVM`
- anno: anno di kickoff (`2026`, `2027`)
- scope slug: `PIANO1`, `BANDO7`, `TERRAZZA`, `52CAMERE`

Il `HPAN25PIANO1` esistente è grandfathered (formato pre-convenzione). Convivono. Lo schema accetta `progetto_id` come stringa libera.

#### Cosa **non** generalizza senza migration

| Cambiamento | Tipo migration | Rarità attesa |
|---|---|---|
| 6° tipo di evento (es. `CONSEGNA`, `COLLAUDO`, `RIFIUTO_LAVORO`) | aggiorna `Literal` su `tipo_evento`, aggiungi sub-model `XxxMeta`, aggiorna view stato | media (probabile in Fase 2+) |
| 3ª società pagante (es. nuova legal entity gruppo) | aggiorna `Literal["ORTI","INTUR",...]` su `Progetto.societa_owner_id` e `ProgettoVoce.societa_pagante_id` | bassa (gruppo stabile) |
| Schema `metadata` di un evento esistente (campo nuovo o rimosso) | aggiorna sub-model Pydantic; verifica retro-compatibilità di eventi storici (BQ JSON è permissivo) | media (evolverà naturalmente in Fase 2-3) |
| Nuovo `tipo_doc` su `DOCUMENTO` (es. `EMAIL_FORNITORE`, `CRONOPROGRAMMA`) | aggiorna `Literal` di `DocumentoMeta.tipo_doc` | bassa (set chiuso ragionevole) |
| Nuovo `metodo` di `PAGAMENTO` (es. `PAYPAL`, `CARTA_CREDITO`) | aggiorna `Literal` di `PagamentoMeta.metodo` | bassa |

Tutti sono "evolution events" gestibili con migration di una riga ciascuna. Lo schema Step 1 è progettato per non richiederne nei prossimi N progetti CapEx come quelli sopra.

#### Cosa è **fuori scope per design** (non si vuole generalizzare)

- **OpEx ricorrente** (utenze, salari, commissioni mensili) — vive in CONDGES, non in `progetti/`. Vedi `concepts/PROGETTO.md` §"Scope iniziale".
- **Progetti commerciali/marketing** senza CapEx dedicato — fuori scope.
- **Sostituto del piano finanziario 28 voci** — il PF resta lente aggregata; il Progetto è granulare e ortogonale.

## 6. Step 1 — scope esatto

### IN

1. **Pydantic models** in `core/schemas.py`:
   - `Progetto`, `ProgettoVoce`, `ProgettoEvento` (base)
   - `PreventivoMeta`, `ImpegnoMeta` (+`Rata`), `FatturaMeta`, `PagamentoMeta`, `DocumentoMeta` (discriminated union)
2. **Table IDs** in `core/config.py`: `D_PROGETTI`, `F_PROGETTO_VOCI`, `F_PROGETTO_EVENTI`.
3. **DDL BigQuery** via nuovo script `core/bq/load/create_progetti_tables.py` (idempotent, CREATE TABLE IF NOT EXISTS).
4. **Seed loader** `core/bq/load/seed_progetti_step1.py`:
   - Dati inline hardcoded (nessun parsing Excel in Step 1).
   - Popola le 10 voci + ~17 eventi.
   - Idempotente: DELETE dove `progetto_id IN ('HPAN25PIANO1', 'SPIAGGIA_LOTTO7')`, poi INSERT.
5. **View** `core/bq/views/v_progetto_voci_stato.sql` — implementa §4 COSA.
6. **Tests** `tests/test_progetti_schema.py`:
   - Validazione Pydantic per ogni sub-model metadata.
   - Discriminated union: `tipo_evento='IMPEGNO'` accetta solo `ImpegnoMeta`.
   - Roundtrip JSON ↔ model.
   - Happy path di un evento per ogni tipo.

### OUT (Fase 2+)

- View `v_progetto_timeline` (budget evolution), `v_progetto_payment_schedule` (QUANDO), `v_progetto_preventivi` (CHI)
- Forward-flow a `f_piano_finanziario_input` fonte=PROGETTI → `v_previsione_cassa`
- CLI `hotelops progetti {overview,voci,eventi,add-preventivo,...}`
- Streamlit app (4 viste di PROGETTO.md)
- LLM extraction PDF → eventi
- Writeback Drive (crea Excel template + cartelle)
- Agent loop drop→map
- Parsing automatico Excel attuali (HPAN25PIANO1_CapEx_Controllo.xlsx, SPIAGGIA_budget_lotto7.xlsx) → eventi

## 7. Roadmap multi-fase

| Fase | Scope | Direzione I/O | Durata target |
|---|---|---|---|
| **Fase 1** (questa) | Flow + backend legge-solo | Drive manuale → BQ eventi | 1-2 giorni |
| **Fase 2** (reversed) | hotelops crea Excel template + struttura cartelle Drive + forward-flow CONDGES | BQ eventi → Drive + Excel + `f_piano_finanziario_input` | 1-2 settimane |
| **Fase 3** (agent loop) | Agente LLM con loop specifico: user droppa PDF → agent estrae + mappa → eventi | Drop user → agent → BQ eventi | 2-3 settimane post-Fase 2 |

Step 1 valida il flow. Se i 10 seed entrano puliti e `v_progetto_voci_stato` ritorna i numeri attesi → flow trovato, si passa a Fase 2.

## 8. Mapping esplicito Excel → eventi (per futura automazione)

Per trasparenza del flow, come i 2 Excel attuali si mapperebbero a eventi (Fase 3, non Step 1):

### HPAN25PIANO1_CapEx_Controllo.xlsx

- **Sheet "Fornitori" (28 righe)** → `d_anagrafica_fornitori` (upsert) + `f_progetto_voci` (1 voce per riga + categoria + `fornitore_id` se già scelto)
- **Sheet "Preventivi" (3 righe C-001/002/003)** → 1 evento `IMPEGNO` per riga + `metadata.numero_contratto`, `rate` da "Termini Pagamento" parsato
- **Sheet "Dati Fatture" (28 righe)** → 1 evento `FATTURA` per riga + `movimento_row_hash` se match con `f_movimenti_contabili` + 0/N eventi `PAGAMENTO` (colonna "Importo Pagato" > 0)

### SPIAGGIA_budget_lotto7_v2.xlsx

- **Sheet "Riepilogo Preventivi" (7 righe)** → 7 eventi `PREVENTIVO` (uno per fornitore/offerta) + `metadata.articolo`, `numero_preventivo`, `data_preventivo`
- **Sheet "Comparativa Pagoda" (4 righe)** → 4 eventi `PREVENTIVO` stessa voce `SPIAGGIA_LOTTO7.001`, fornitori diversi
- **Sheet "1-Similis Vela" … "7-Casamica Talenti"** → 7 eventi `DOCUMENTO` (tipo=PREVENTIVO, drive_url=link PDF), `correlato_evento_id` → evento PREVENTIVO corrispondente
- **Sheet "Pagamenti" (vuoto)** → 0 eventi `PAGAMENTO`

Questo mapping è **solo documentazione del flow**, non codice Step 1. Serve a convincere che lo schema regge i 2 Excel senza perdere informazione.

## 9. Impact sul lavoro vault / spec esistente

- **`concepts/PROGETTO.md`** — aggiornare §"Il fatto economico è un thread" (capture fine sessione): rimuovere proposta "3 fact tables per lente", sostituire con "1 event log con 5 tipi evento + 2 SNAPSHOT". Resto del concept (I4 esteso, 4 domande, doppia macchina, substrate/projection/face, boundary reconciler/engine) resta valido al 100%.
- **`decisions/2026-04-21_Progetto_First_Class_Dimension.md`** — amendment (capture fine sessione): "§Implementation approach: Binario A = 3 tabelle event-sourced (d_progetti, f_progetto_voci, f_progetto_eventi), non 8 normalizzate". Il rationale originale (flat prima, normalizza dopo) è rinforzato, non contraddetto — 3 tab event-sourced è *più* flat di 8 normalizzate.
- **`docs/superpowers/specs/2026-04-20-projects-mvp-design.md`** — archiviare in `docs/superpowers/specs/archive/` post-approval. La sua logica di forward-flow e integrazione con `f_piano_finanziario_input` resta valida per Fase 2.

## 10. Anti-goals Step 1 (espliciti)

| Fuori scope Step 1 | Motivo |
|---|---|
| UI (Streamlit) | Validation del flow, non user experience |
| CLI `hotelops progetti` | Seed hardcoded basta per Step 1 |
| LLM extraction | Fase 3 |
| Parsing Excel attuali | Fase 3 — seed inline evita dipendenza da xlsx format |
| Forward-flow a `f_piano_finanziario_input` | Fase 2 |
| Multi-utente / permessi | Single user Stefano Jr |
| Watermark / staleness detection | Fase 2 |
| Tagging retroattivo `progetto_id` su `f_movimenti_contabili` | H2 della spec S2, non ora |
| Scope packages / WBS gerarchico | KISS — categoria stringa libera su `f_progetto_voci` |
| Bank reconciliation automatica | Fase 2 via `banca_movimento_hash` opzionale |

## 11. Related

- `vault/INVARIANTS.md` — I1 (validation gate), I2 (APPEND/SNAPSHOT), I4 (3 lenti), I7 (audience), I8 (row selection in view canonica)
- `vault/concepts/PROGETTO.md` — concept autoritativo (4 domande, 5 stati lifecycle, doppia macchina, substrate/projection/face)
- `vault/decisions/2026-04-21_Progetto_First_Class_Dimension.md` — ADR padre (da emendare post-approval)
- `docs/progetti/HPAN25PIANO1-walkthrough.md` — fonte seed HPAN25PIANO1 + 11 model refinements validati
- `docs/progetti/HPAN25PIANO1-seed-data.md` — importi reali da Excel baseline
- `docs/progetti/seed/f_progetto_stato_corrente_seed.csv` — flat subledger precedente (28 righe), rappresentato qui come `v_progetto_voci_stato` vista derivata dagli eventi
- `vault/ontology/projects/CamerePrimoPiano.md` — ontologia progetto (da aggiornare post-approval con cap 1.2M)
- **SPIAGGIA xlsx** (`~/Desktop/WORK/metodo-progetti/spiaggia_progetto/SPIAGGIA_budget_lotto7_v2.xlsx`) — fonte seed SPIAGGIA_LOTTO7
- **HPAN25PIANO1 xlsx** (`~/Desktop/WORK/metodo-progetti/camere-nuove/HPAN25PIANO1_CapEx_Controllo.xlsx`) — esempio Excel maturo per validazione mapping

## 12. Implementation (post-approval)

- Branch: `projects-event-sourced-step1`
- Plan: da generare tramite `superpowers:writing-plans` skill post-approval
- Target Step 1: 3 CREATE TABLE eseguite + 10 voci + ~17 eventi seed in BQ + `v_progetto_voci_stato` ritorna 10 righe coerenti + tutti i test Pydantic verdi + smoke test `SELECT stato, COUNT(*) FROM v_progetto_voci_stato GROUP BY stato` rende distribuzione plausibile (IN_CORSO_FATTURATO, IMPEGNATO, IN_VALUTAZIONE, IDENTIFICATO).

*Sezione Implementation popolata con commit hashes durante l'esecuzione del plan.*
