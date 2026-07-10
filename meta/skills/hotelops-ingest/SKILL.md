---
name: hotelops-ingest
description: Guided file ingestion for hotelops via the GCS lineage path (intake → promote → verify). Use this skill EVERY time Stefano wants to ingest, load, or register new files into hotelops/BigQuery — triggers on "ingerisci", "carica questi file", "ho nuovi file", "nuovo export", "intake", "promote", or whenever he drops file paths (TXT accodamenti, export Esolver, xlsx Power BI, homebanking, RistoCube) and wants them in BQ. Also use when a file doesn't match any known source and a new source must be defined. This skill OVERRIDES the instinct to call a parser directly with --file or to write to BQ without lineage — that path creates FK-void rows and violates I9.
---

# HotelOps Ingest — lineage-first, sempre

## Perché esiste

Ogni file che entra in BigQuery senza passare da `hotelops intake` produce righe canonical
senza `raw_object_id` (FK-void), file volatili in `/tmp`, e violazioni I9 quando la source
è già `backend: gcs`. È successo: `f_accodamenti` 3.582 righe FK-void (2026-06-10),
`f_movimenti_contabili` 0/3863 con FK. Il riflesso corretto è uno solo:

> **File → GCS (intake) → promote → verifica.** Mai parser diretto a BQ. Pulizia e
> unificazione si fanno DOPO, sui dati tracciati — non prima, sui file sciolti.

Scope: solo il path lineage. Pipeline legacy (orchestrate, loader dimensioni) sono fuori
scope — se il file appartiene a quelle, dillo esplicitamente e segnala il debito I9.

## Il flusso (6 step, sempre nell'ordine)

### 1. IDENTIFICA — guarda dentro il file, non solo il nome

Per ogni file: apri/ispeziona quanto basta per capire **system** (ESOLVER, HOTELCUBE,
POWERBI, MPS/SELLA/INTESA/BCP, RISTOCUBE), **dataset** (cosa rappresenta), **società**
(ORTI/INTUR), **periodo coperto**, **righe stimate**.

⚠️ **Lezione AEGRI**: un file valido può appartenere a una source semanticamente sbagliata.
`AEGRIOR*.XLSX` sembrava "movimenti contabili" ma era una scheda contabile (conto 190101)
→ ingerita nella source sbagliata → doppio conteggio. Il filename non basta: verifica che
il *contenuto* matchi la semantica della source (colonne, conti, struttura).

### 2. MATCH — contro `core/source_registry.yaml`

Il registry (SSOT policy, ~23 source) ha per ogni source: `system`, `dataset`, `societa`,
`lifecycle`, `canonical_table`, `parser_module`, `loop_targets`, `promotion_policy`,
`raw_storage.backend`. Naming grammar: `<SYSTEM>_<DATASET>_<SOCIETA>_<LIFECYCLE>`
(4 parti strict).

- **Match univoco** → step 3.
- **Match ambiguo** (più source plausibili, o contenuto ≠ semantica attesa) → **fermati e
  chiedi**, mostrando le opzioni con la differenza semantica. Mai tirare a indovinare —
  specialmente sulla società (lo storico accodamenti era mislabeled INTUR→ORTI).
- **Nessun match** → step "Nuova source" (sotto).

### 3. PIANO — un blocco unico, poi conferma

Prima di toccare qualsiasi cosa, presenta UN blocco piano e aspetta l'ok:

```
## Piano ingest — <n> file
| file | source | società | periodo | righe ~ |
|---|---|---|---|---|

- Lifecycle: APPEND (dedup hash_riga) | SNAPSHOT (DELETE+INSERT su natural_key: <chiave>)
- ⚠️ Se SNAPSHOT: cosa viene CANCELLATO e con quale scope di DELETE
- GCS dest: gs://hotelops-raw/<SOURCE_NAME>/YYYY/MM/
- Promotion: AUTO | manuale | RAW_ONLY (no canonical)
- Tabella canonical: <f_*> — righe attuali nel periodo: <query rapida prima del piano>
- Sovrapposizioni note col dato esistente: <sì/no, dettaglio>
```

Domande solo sui punti genuinamente ambigui. Una volta confermato il piano, esegui tutto
senza ri-chiedere a ogni step.

### 4. INTAKE — sempre, anche se il parser non esiste ancora

```bash
hotelops intake <file> --source-name <SOURCE_NAME>
# oppure, se classify risolve da solo e vuoi il flusso compatto:
hotelops capture <file> [--source-name X] [--societa ORTI|INTUR] [--no-promote] [--dry-run]
```

- `intake` = raw-only: registra blob GCS + `f_raw_objects` + evento RAW_INGESTED. Non promuove mai.
- `capture` = classify → intake → promote se `promotion_policy: AUTO`. Usa `--dry-run` se
  vuoi mostrare il piano a Stefano col tool stesso.
- Dedup intake: se il content-hash esiste già, intake lo segnala (`deduped`) — non è un errore.
- `HOTELOPS_LINEAGE_GATE` deve restare `required` (default). Mai `disabled` per comodità.
- File in posti volatili (`/tmp`, Desktop, Downloads): l'intake li mette al sicuro in GCS —
  questo è il motivo per cui si fa SUBITO, anche quando la promozione è rimandata.

### 5. PROMOTE — verso canonical, via policy gate

```bash
hotelops promote --raw-object-id <id>
```

- Il gate rifiuta se `loop_targets == []` (RAW_ONLY ⇒ no canonical). Non aggirarlo.
- Se il parser fallisce, il raw object resta in GCS: il file è salvo, si debugga il parser.
  Questo è il comportamento giusto, non un problema.

### 6. VERIFICA — output-based, mai exit-code-based

Dopo ogni promote, esegui e mostra:

```sql
-- a) FK coverage: le righe nuove DEVONO avere raw_object_id
SELECT COUNT(*) tot, COUNTIF(raw_object_id IS NOT NULL) con_fk
FROM `hotelops-suite.hotelops.<canonical_table>`
WHERE <filtro periodo/file appena caricato>;

-- b) Copertura periodo: righe per mese, confronto con attese dal piano
-- c) Stato lineage
SELECT * FROM `hotelops-suite.hotelops.v_raw_objects_current`
WHERE raw_object_id = '<id>';  -- atteso: PROMOTED
```

- **APPEND**: conta righe nuove vs attese; zero doppioni su `hash_riga` nel periodo.
- **SNAPSHOT**: row count post = atteso, nessun periodo orfano cancellato per sbaglio.
- Se non puoi verificare (no credenziali/ambiente): dichiaralo, non claimare successo.

## Nuova source (nessun match nel registry)

Discovery-first → RAW_ONLY. Intervista breve, poi scaffold:

1. Chiedi: system? dataset (cosa rappresenta davvero)? società? il dato è **evento
   immutabile → APPEND** o **fotografia rivedibile → SNAPSHOT**? esiste già un loop che
   lo consuma (`loop_targets`)?
2. Proponi l'entry `source_registry.yaml` con naming grammar 4-parti. Invariante hard:
   `loop_targets: []` ⇔ `promotion_policy: RAW_ONLY`. Senza loop target dichiarato la
   source nasce RAW_ONLY — il parser canonical è lavoro separato, non di questa sessione.
3. ⚠️ **Lezione occupazione**: se il nuovo file è una *variante* di una source esistente
   (stesso sistema, report diverso), NON infilarlo nella source esistente "perché simile".
   Source separata o subtype esplicito — è la ripetizione del caso AEGRI da evitare.
4. Dopo l'edit registry: `hotelops intake` del file. Il dato è in GCS, tracciato, e la
   sessione può chiudersi lì.
5. Nuova source = candidate capture per il vault (decisione/ontologia) — proponila, non
   scriverla in autonomia.

## Trappole note (pagate sul campo)

| Trappola | Regola |
|---|---|
| Export duplicato internamente (Hotel ×2.4, num_doc ripetuti) | Conta i doppioni PRIMA di ingerire. Copie non byte-identiche non si dedup-ano a valle: chiedi un **re-export pulito** |
| DELETE troppo larga su SNAPSHOT/ricostruzioni (over-delete vendite_fb) | Scope DELETE esplicito nel piano, conta le righe che cancellerai PRIMA di farlo |
| Società sbagliata (accodamenti INTUR→ORTI) | H_/R_/C_ = strutture ORTI. Se classify non rileva la società, chiedi — mai default silenzioso |
| Re-label di righe esistenti | Mai UPDATE (hash stale): roundtrip DELETE+reinsert con hash ricalcolato |
| File "simile" a source esistente | Caso AEGRI/occupazione: contenuto ≠ semantica → source separata |
| RistoCube nativo = LORDO IVA, Power BI = imponibile | Per food cost serve imponibile. Verifica la base prima di caricare vendite |
| Drive su account panoramagroup, MCP su account personale | Scarica via token gcloud (Drive API), non via MCP |
| Primo promote su canonical NUOVA = chicken-egg (PEC 2026-07-08): `filter_new_rows_by_hash` fa SELECT su tabella inesistente → VALIDATE_FAIL | Pre-crea SEMPRE le canonical con uno script `core/bq/load/create_*_tables.py` PRIMA del primo promote |
| Contratto promotion reale: `--file X --societa <SOC> --raw-object-id Y` — il docstring dei parser esistenti non mostra `--societa` | Ogni parser nuovo DEVE accettare `--societa` (con check di coerenza sul contenuto), o il promote esce REJECTED exit 2 |
| Nomi allegato/file con control char (RFC2047 multi-riga) → GCS rifiuta l'object name (400 Disallowed unicode) | Sanitizza il componente path (control char → `_`), fedeltà del nome originale nella riga BQ; revive da REJECTED = evento RECLASSIFIED via `emit_event` (non esiste comando CLI) |
| PROMOTED è terminale nella state machine: `hotelops promote` su oggetto già PROMOTED = noop by design (PEC 2026-07-09: truncate+re-promote 32 → 0 righe scritte) | Re-parse di massa dopo un fix parser: truncate scoped della canonical + riusa `_invoke_parser` di `ingest/promotion.py` (stesso download GCS pinnato alla generation, stesso contratto `--societa`/`--raw-object-id`, FK intatta). Mai parser a mano su file locali |

## Anti-goals

- Mai parser diretto (`python -m ingest... --file`) verso canonical quando la source è nel
  registry: il path è intake→promote. Il parser standalone è solo per `--dry-run`/debug.
- Mai BQ write senza che il file sia prima in GCS. "Lo carico ora e faccio l'intake dopo"
  = FK-void garantito.
- Mai inventare source_name fuori grammar, mai creare source nel registry senza i 4 campi
  semantici chiariti con Stefano.
- Mai mediare/fondere file sovrapposti in silenzio: esponi l'overlap nel piano e chiedi
  quale fa fede.
- Mai dichiarare "ingerito" senza la verifica §6 (FK + count + stato PROMOTED).
