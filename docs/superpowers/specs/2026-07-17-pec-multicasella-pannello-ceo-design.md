# PEC multi-casella + pannello CEO — Design

Data: 2026-07-17
Stato: approvato con correzioni obbligatorie (recepite in questo documento)
Predecessore: `2026-07-08-pec-mbox-ingestion-design.md` (ingestion INTUR, già in produzione)

## Contesto e obiettivo

Quattro caselle PEC da monitorare, quattro soggetti giuridici distinti:

| entity_id | Casella | Bucket raw | Stato |
|---|---|---|---|
| `INTUR` | in.tur@pec.it | `hotelops-raw` | già ingerita (`PEC_MAILBOX_INTUR_APPEND`) |
| `ORTI` | orti@pec.it | `orti-raw` | export mbox disponibili |
| `VIGNA` | vineyardamalficoast@pec.it | `vigna-raw` | export mbox in `pec/{mandate,ricevute}/` |
| `STEFANO_PERSONALE` | stefanojunior.dellapietra@mpspec.it | `stefano-raw` | 6 .eml disponibili |

Obiettivo: un registro unificato in BigQuery, classificazione spiegabile dei
documenti, proiezione dei documenti importanti sul pannello CEO in Drive
(`My Drive/01_societario/AMM_CEO/`, mirror locale sincronizzato), digest di
monitoraggio azionabile.

**Principio di autorità**: GCS e BigQuery sono il sistema canonico.
`AMM_CEO` su Drive è esclusivamente una *projection* operativa consultabile —
mai una seconda verità documentale. Ogni stato applicativo (sync, checkpoint
digest, classificazioni) vive in BQ/GCS, mai soltanto nel mirror Drive.

## Architettura

```
orti-raw ────────┐
vigna-raw ───────┤   intake → promote → parse (parser unico, contesto da registry)
stefano-raw ─────┤                │
hotelops-raw ────┘                ▼
                    f_pec_messages + f_pec_allegati        (registro unificato)
                                  │
                                  ▼
                    classify (ruleset versionato) → f_pec_classificazioni
                                  │
                     ┌────────────┴────────────┐
                     ▼                         ▼
            pec sync-panel              pec digest
            (projection su Drive,       (checkpoint BQ,
             whitelist entity)           markdown su Drive)
```

Raw separati per soggetto giuridico (confine amministrativo/IAM/blast radius);
pipeline, schema e viste unici; provenienza esplicita per riga; dedup globale.

## Identità: EntityId

Nuovo tipo in `core/schemas.py`:

```python
EntityId = Literal["INTUR", "ORTI", "VIGNA", "STEFANO_PERSONALE"]
```

- `SocietaId` **non viene toccato**: resta `Literal["ORTI", "INTUR"]` e continua
  a governare i flussi contabili/finanziari. L'eventuale ingresso di VIGNA in
  contabilità è una decisione separata, fuori scope.
- `PecMessageRow.societa_id: SocietaId` → sostituito da
  `entity_id: EntityId`. Migrazione BQ additiva: si aggiunge la colonna
  `entity_id` (backfill `entity_id = societa_id` sulle righe esistenti, che sono
  tutte INTUR); `societa_id` resta popolata solo per le società, `NULL` per
  STEFANO_PERSONALE, e viene deprecata nelle query nuove.
- `PecAllegatoRow` eredita l'entity attraverso il join su `msgid`; non duplica
  la colonna.

## Source registry — nuove entry

Tre nuove sorgenti con la stessa grammar di `PEC_MAILBOX_INTUR_APPEND`:

```yaml
PEC_MAILBOX_ORTI_APPEND:
  system: PEC
  dataset: MAILBOX
  entity_id: ORTI            # nuovo campo (per le sorgenti PEC)
  casella: orti@pec.it       # nuovo campo
  input_formats: [mbox]      # nuovo campo: mbox | eml
  lifecycle: APPEND
  canonical_table: f_pec_messages
  parser_module: ingest.flussi.ingest_pec_mbox
  hash_basis: msgid
  promotion_policy: AUTO
  detector_category: pec_mbox
  raw_storage: {backend: gcs, bucket: orti-raw, path_template: "pec/mailbox/ORTI"}

PEC_MAILBOX_VIGNA_APPEND:      # entity_id: VIGNA, casella: vineyardamalficoast@pec.it,
                               # bucket: vigna-raw, formats: [mbox]
PEC_MAILBOX_PERSONALE_APPEND:  # entity_id: STEFANO_PERSONALE,
                               # casella: stefanojunior.dellapietra@mpspec.it,
                               # bucket: stefano-raw, formats: [eml, mbox]
```

Il registry risolve per ogni sorgente: casella (mailbox), entity_id, formati di
input ammessi, bucket + prefix canonico. La *policy di visibilità sul pannello*
NON sta nel registry: sta nella whitelist esplicita della projection (v. sotto),
così una nuova sorgente non entra mai nel pannello per default.

## Parser generalizzato

- `promotion.py` passa al parser un nuovo argomento obbligatorio
  `--source <SOURCE_NAME>`; il parser risolve casella/entity_id/formati dal
  registry. **Nessun default**: senza `--source` il parser esce con errore —
  mai più costanti `CASELLA`/`SOCIETA` nel modulo, mai attribuzioni implicite.
- Supporto `.eml`: un file .eml = un messaggio, stesso modello canonico del
  percorso mbox (stessa anatomia busta/messaggio, stessi artefatti
  `daticert.xml`/`postacert.eml`). Nessun ramo speciale a valle del parsing.
- Dedup invariata nella sostanza e indipendente dal container:
  `hash_riga = md5(msgid)` identifica il messaggio logico. Per messaggi privi
  di Message-ID affidabile: fallback su hash canonico
  `md5(mittente|data_evento|sha256(body))`, marcato con `parse_warning`.

## Classificatore

Tre dimensioni separate, mai confuse:

- `document_category`: `BANCA`, `LEGALE`, `FISCO`, `REGISTRO_IMPRESE`,
  `ASSICURAZIONE`, `PA`, `FORNITORE`, `ALTRO`
- `importance`: `ALTA`, `NORMALE`, `DA_RIVEDERE`
- `document_type`: `CONTRATTO`, `VERBALE`, `BILANCIO`, `DIFFIDA`, `FATTURA`,
  `ATTO_GIUDIZIARIO`, `RICEVUTA_PEC`, `ALTRO`

Stato di classificazione: `CLASSIFICATO` | `NON_CLASSIFICATO` | `AMBIGUO` |
`ERRORE_CLASSIFICAZIONE`.

**Ruleset = configurazione versionata**, non codice: `core/pec_ruleset.yaml`
con campo `version` (semver). Ogni regola: `id`, criteri di match
(dominio mittente, regex oggetto, regex nome allegato), assegnazioni
(category/importance/type), `priority`. Una PEC può matchare più regole: si
conservano **tutti** i match; la categoria primaria emerge dalle priorità
esplicite; match a pari priorità senza vincitore → `AMBIGUO` (nel digest).

Output — nuova tabella `f_pec_classificazioni` (APPEND):

| colonna | contenuto |
|---|---|
| `msgid`, `entity_id` | chiave del messaggio |
| `stato` | CLASSIFICATO / NON_CLASSIFICATO / AMBIGUO / ERRORE_CLASSIFICAZIONE |
| `primary_category`, `importance`, `document_type` | esito |
| `matches` | JSON: tutti gli id regola che hanno fatto match |
| `ruleset_version`, `classified_at` | spiegabilità e riclassificazione |
| `override_source`, `override_note` | NULL oppure HUMAN + nota |

Riclassificare = nuova riga con `ruleset_version` più recente; la vista
`v_pec_classificazione_corrente` espone l'ultima classificazione per msgid,
con precedenza assoluta all'override umano. Nulla si sovrascrive: la storia
delle classificazioni resta interrogabile.

## Projection: pannello CEO (`hotelops pec sync-panel`)

Stato canonico in BQ — nuova tabella `f_pec_panel_projections`:

- `projection_key = md5(msgid | attachment_sha256 | destination_path)` —
  chiave idempotente; lo stesso PDF in due PEC diverse genera due proiezioni
  legittime e distinte.
- colonne: msgid, sha256, entity_id, gcs_uri, destination_path, run_id,
  projected_at, status (`COPIED` | `SKIPPED_EXISTS` | `FAILED`).

Regole:

- **Whitelist esplicita**: `PANEL_ENTITIES = ["INTUR", "ORTI", "VIGNA"]` in
  `core/config.py`. Non è una esclusione di PERSONALE: un'entity nuova NON
  entra nel pannello finché non viene aggiunta qui deliberatamente.
- Destinazione: `AMM_CEO/<ENTITY>/PEC/<Categoria>/<AAAA-MM> - <nome_file>`.
  Si proiettano gli allegati con `importance = ALTA` (criterio iniziale,
  tarabile dal ruleset).
- Sanitizzazione nomi: solo basename, rimozione separatori e `..`, charset
  sicuro, lunghezza limitata. Collisione di path → suffisso `sha256[:8]`.
- Guardia path: il path di destinazione risolto (realpath) DEVE stare sotto il
  root configurato del pannello; altrimenti errore, mai scrittura.
- Limite dimensione allegato (default 100 MB): oltre soglia non si copia, si
  segnala nel digest con il link `gs://`.
- Solo aggiunte, mai cancellazioni o sovrascritture. `--dry-run` disponibile.
- Ordine delle operazioni: copia file riuscita → poi insert riga `COPIED`.
  Crash tra i due passi: il re-run trova il file con la stessa projection_key
  e riconcilia (`SKIPPED_EXISTS`). `pec sync-panel --verify` riconcilia gli
  stati incoerenti nei due sensi (file senza riga, riga senza file) e riferisce.
- Nel pannello può vivere una copia leggibile dell'indice (`_indice.md`),
  informativa e rigenerabile: non è mai l'autorità.

## Digest (`hotelops pec digest`)

Checkpoint tecnico separato dall'output umano — nuova tabella
`f_pec_digest_runs`: run_id, started_at, finished_at, status, from_ts, to_ts,
parametri. Default `--da` = `to_ts` dell'ultimo run `SUCCESS` (primo run:
epoca corpus). Un solo run attivo alla volta (guard sul run aperto).

Flag: `--da DATA`, `--a DATA`, `--casella`, `--entity`, `--solo-anomalie`,
`--format markdown|json`.

Sezioni del report, in quest'ordine (azionabile prima, rumore poi):

1. messaggi importanti nuovi (per entity, con esito proiezione)
2. ricevute PEC anomale o incomplete (non-accettazione, errore-consegna, buste senza ricevuta)
3. errori di parsing (`parse_warning`) e `ERRORE_CLASSIFICAZIONE`
4. allegati importanti NON sincronizzati (oversize, failed) con link gs://
5. classificazioni `AMBIGUO` e `NON_CLASSIFICATO` da rivedere
6. elementi risolti/override dall'ultimo run
7. totali nuovi messaggi per casella

Output: stdout + `AMM_CEO/_digest/AAAA/MM/AAAA-MM-GG.md` + `latest.md`
rigenerato. Il markdown è output umano; lo stato è solo il checkpoint BQ.
STEFANO_PERSONALE compare nel digest (monitoraggio) ma mai nel pannello.

## Bonifica delle copie manuali (one-shot)

Oggetti caricati a mano il 2026-07-16: `gs://orti-raw/pec/**` (5 mbox),
`gs://stefano-raw/pec/**` (6 eml). Vanno rimossi SOLO dopo che uno script
(`scripts/bonifica_pec_manuali.py`) verifica automaticamente, per ogni file:

1. promote `SUCCESS` della sorgente corrispondente;
2. oggetto presente nel path canonico `raw_storage`;
3. hash coincidente (MD5/sha256) tra copia manuale e oggetto canonico;
4. record di lineage persistito in BQ.

Tutte e quattro vere → rimozione + report. Qualunque verifica fallita → il
file resta e finisce nel report. Nessuna cancellazione manuale.
`gs://vigna-raw/pec/**` (preesistente) segue la stessa procedura solo dopo
che VIGNA sarà stata ingerita dal nuovo flusso.

## Invarianti

- **I-PEC-1** Il raw è immutabile: né parser né projection lo modificano mai.
- **I-PEC-2** L'entity di ogni riga deriva dal registry della sorgente, mai dal
  contenuto: una casella non può produrre record attribuiti a un'altra entity.
- **I-PEC-3** STEFANO_PERSONALE non può raggiungere `AMM_CEO` (whitelist
  positiva; test dedicato che DEVE fallire se la whitelist viene aggirata).
- **I-PEC-4** Ripetere qualsiasi passo della pipeline non crea duplicati
  (dedup su msgid; projection_key; checkpoint digest).
- **I-PEC-5** Ogni file del pannello è riconducibile al raw:
  destination_path → `f_pec_panel_projections` → `f_pec_allegati` →
  `raw_object_id`.
- **I-PEC-6** `sync-panel` non scrive mai fuori dal root configurato, anche
  con nomi file malevoli (`../../x.pdf`).
- **I-PEC-7** Un errore su un messaggio non blocca il batch; nessuno skip
  silenzioso: tutto ciò che viene saltato compare nel report/digest.
- **I-PEC-8** Ogni classificazione è spiegabile: regole matchate, versione
  ruleset, timestamp, eventuale override umano.

## Failure modes

| Caso | Comportamento |
|---|---|
| daticert.xml assente/malformato | tipo degradato + `parse_warning` (già esistente) |
| MIME annidati, encoding degeneri | estrazione best-effort, warning, mai crash del batch |
| msgid assente | fallback hash canonico + `parse_warning` |
| crash tra copia file e insert riga projection | re-run riconcilia via projection_key (`SKIPPED_EXISTS`) |
| stato incoerente pannello/BQ | `sync-panel --verify` riconcilia e riferisce, mai cancella |
| allegato oversize | non copiato, segnalato nel digest con link gs:// |
| Drive per Desktop spento | si scrive comunque sul mirror; il digest segnala se il root pannello non esiste |
| run digest concorrente | secondo run rifiutato finché il primo è aperto |
| GCS/BQ irraggiungibili | run `FAILED` nel checkpoint; nessuno stato parziale non registrato |

## Testing

Fixture: .eml normale; .eml con allegati; PEC completa con postacert.eml;
ricevuta di accettazione; ricevuta di consegna; encoding/MIME degeneri; nome
allegato con path traversal; allegato oversize; messaggio senza msgid.

- Unit: classificatore (multi-match, priorità, AMBIGUO, versioning ruleset,
  override), sanitizzazione + costruzione path, projection_key.
- End-to-end su fixture: intake → promote → parse → classify → sync-panel →
  digest; poi ripetizione integrale della pipeline (zero duplicati);
  isolamento tra entity; STEFANO_PERSONALE mai nel pannello; retry dopo
  errore parziale; manifest/stato incoerente; collisioni di nome.
- Log strutturati su tutta la pipeline: `run_id`, `source_id`, `msgid`,
  `entity_id`.

## Fuori scope (MVP)

Classificazione LLM (fase 2), notifiche push, retention/cancellazioni, OCR dei
contenuti, vista Streamlit dedicata, ingest automatico dalla webmail (l'export
resta manuale), ingresso di VIGNA in `SocietaId`/contabilità.

## Questioni aperte

1. **VIGNA senza originali locali**: gli mbox esistono solo in
   `gs://vigna-raw/pec/`. Proposta: download locale → intake normale (lineage
   pulita), poi bonifica delle copie GCS preesistenti. Alternativa: intake con
   sorgente GCS diretta (più lavoro sul CLI).
2. **Priorità tra categorie** (es. LEGALE > BANCA quando matchano entrambe):
   default nel ruleset v1, da tarare con l'uso reale.
3. **Nomi cartella categoria nel pannello**: enum tecnico (`BANCA`) o italiano
   leggibile (`Banca`)? Proposta: leggibile, con mapping nel config.
4. **Soglia di proiezione**: `importance = ALTA` basta, o si proiettano anche
   categorie intere (es. tutto REGISTRO_IMPRESE)? Proposta iniziale: solo ALTA.
