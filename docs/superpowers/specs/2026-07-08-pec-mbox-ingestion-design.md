# PEC/MBOX Ingestion Layer — Design

**Data:** 2026-07-08 · **Stato:** approvato da Stefano (sessione 2026-07-08)
**Scope:** Prompt 1 di 3 — ingestion (mbox → GCS raw → extraction → metadata BQ).
Search, timeline, arricchimento LLM e document graph sono prompt successivi che
consumano quanto prodotto qui.

## Contesto e obiettivo

"Archeologia aziendale" sulla PEC di INTUR: capire cosa è successo, quando, chi ha
scritto a chi, quali allegati sono stati trasmessi, cosa è opponibile (firmato,
certificato). Il corpus censito (2026-07-08):

- **32 file mbox** in `~/Downloads`, ~2,44 GB, una sola casella: `in.tur@pec.it`
- **27 file received** (cartella ricevuta): copertura continua 2021-02-17 → 2026-07-07,
  ~2.700 buste lorde con forti duplicazioni tra export (quadruplicati interi a
  livello file). Stima ~1.500–1.800 buste uniche. Il received parte davvero dal
  2021 (confermato da Stefano — non esiste received precedente).
- **5 file sent** (cartella inviata): 2018-06-23 → 2026-06-30, ~490 messaggi.
- Vuoti di copertura received: 5 finestre da 15–25 giorni, tutte estive (silenzio
  reale, non pagine perse). Restano flaggati nel report.

## Anatomia del dato (verificata sul corpus)

Due forme, distinte SEMPRE dal contenuto (mai dal filename — lezione accodamenti):

1. **Busta di trasporto** (received): `From = posta-certificata@<provider>`.
   Contiene `daticert.xml` (verità certificata: mittente reale, destinatari,
   timestamp opponibile, msgid, tipo, riferimento al messaggio originale per le
   ricevute), `smime.p7s` (firma provider), e `postacert.eml` (il messaggio reale
   con subject/body/allegati veri). Tipi osservati: POSTA CERTIFICATA (messaggio
   in arrivo), ACCETTAZIONE e CONSEGNA (ricevute delle PEC *inviate* — la prova
   opponibile), ANOMALIA/altro. Le ricevute di accettazione spesso NON hanno
   `postacert.eml`: è normale, non è un errore.
2. **Messaggio inviato** (sent): `From = in.tur@pec.it`, nessuna busta, nessun
   daticert. È il messaggio così come partito. Il suo timestamp certificato non è
   nel file: arriva dal link con la ricevuta di ACCETTAZIONE presente nel received.

## Architettura

```
mbox (Downloads, volatile)
  → hotelops intake                    # GCS raw + f_raw_objects (dedup MD5 file-level)
  → hotelops promote                   # gate policy → parser
  → ingest/flussi/ingest_pec_mbox.py   # spacchettamento deterministico
  → f_pec_messages + f_pec_allegati    # BQ, via bq_write_validated (I1)
  → allegati reali → GCS content-addressed
  → v_pec_conversazioni                # vista: inviata → accettazione → consegna
```

### Source registry

```yaml
PEC_MAILBOX_INTUR_APPEND:
  system: PEC
  dataset: MAILBOX
  dataset_label: "PEC in.tur@pec.it — buste ricevute + messaggi inviati (export webmail mbox)"
  societa: INTUR
  lifecycle: APPEND
  canonical_table: f_pec_messages
  parser_module: ingest.flussi.ingest_pec_mbox
  hash_basis: msgid
  loop_targets: [pec_archive]
  promotion_policy: AUTO
  detector_category: pec_mbox
  raw_storage: gcs / hotelops-raw / <SOURCE_NAME>/YYYY/MM
```

Una source per casella: caselle future (es. ORTI) = nuove entry con la stessa
grammar. L'identità della casella viene verificata dal contenuto (To/daticert per
le buste, From per le inviate); mismatch col registry ⇒ errore, non silenzio.

### Dedup (il requisito "ti do tutto e capisci cosa è dedup")

Tre livelli, tutti idempotenti:
1. **File**: l'intake scarta i file byte-identici (MD5 content-hash — già esiste).
2. **Messaggio**: chiave = **envelope `Message-ID` header** del messaggio mbox
   (per-evento, stabile tra re-export), sia per buste che per inviate; fallback
   sha256 del raw message. `filter_new_rows_by_hash` su `hash_riga =
   md5(msgid)` (via `make_hash`). Due export sovrapposti convergono senza doppioni;
   ri-promuovere lo stesso file produce 0 righe nuove.
   ⚠️ Il daticert `<identificativo>` NON è la chiave: è l'id della **catena**
   di ricevute (stesso valore per POSTA_CERTIFICATA + ACCETTAZIONE + CONSEGNA
   di una stessa PEC) — verificato sul corpus Aruba 2026-07-08 (usarlo da solo
   collassava 3 fatti legali distinti in 1, 18/80 righe perse nello smoke).
   Quando l'envelope Message-ID manca, il fallback è l'identificativo
   **composto col tipo** (`identificativo#TIPO`) per disambiguare la catena.
3. **Allegato**: binari su GCS indirizzati per sha256 → lo stesso PDF trasmesso
   5 volte è un solo oggetto (le righe f_pec_allegati restano una per trasmissione).

### Schema BigQuery

**`f_pec_messages`** — una riga per busta ricevuta E per messaggio inviato (le
ricevute sono righe: fatti immutabili, è il punto legale della PEC):

| campo | tipo | note |
|---|---|---|
| msgid | STRING REQ | chiave dedup: envelope Message-ID (per-evento) > daticert identificativo+tipo (fallback, l'identificativo da solo è l'id della catena di ricevute) > sintetico |
| source_folder | STRING REQ | RECEIVED \| SENT — cartella d'origine, derivata dall'anatomia del messaggio (busta ⇒ RECEIVED, raw con From=casella ⇒ SENT), non dal filename |
| tipo | STRING REQ | POSTA_CERTIFICATA \| ACCETTAZIONE \| CONSEGNA \| ANOMALIA \| MESSAGGIO_INVIATO \| ALTRO |
| ref_msgid | STRING | ricevute → msgid del messaggio originale (da daticert) |
| data_evento | TIMESTAMP REQ | certificata (daticert) per buste; Date header per inviate |
| data_certificata | BOOL REQ | true se da daticert |
| mittente | STRING | mittente reale (non la busta) |
| destinatari | STRING | ";"-joined |
| n_destinatari | INT | |
| subject | STRING | del messaggio reale quando esiste (postacert), altrimenti della busta — RFC2047-decodificato |
| body_text | STRING | testo estratto (no HTML raw, no binari) |
| provider | STRING | dominio busta (aruba, legalmail, …) — solo RECEIVED |
| casella | STRING REQ | in.tur@pec.it |
| societa_id | STRING REQ | INTUR (dal contenuto) |
| n_allegati | INT | allegati reali (esclusi daticert/smime/postacert) |
| ha_postacert | BOOL | false normale per accettazioni |
| parse_warning | STRING | anomalie non fatali (daticert malformato, charset…) |
| hash_riga | STRING REQ | md5(msgid) via make_hash |
| raw_object_id | STRING REQ | FK lineage (I9) |
| data_caricamento | DATETIME REQ | |

Nota implementativa (deviazione dichiarata): nel DDL deployato `data_evento` e
`data_caricamento` sono **DATETIME** (wall time Europe/Rome, naive), non
TIMESTAMP come indicato in tabella. `subject` e `nome_file` sono
**RFC2047-decodificati** dal parser (charset dichiarato, fallback latin-1).

**`f_pec_allegati`** — una riga per allegato reale trasmesso:

| campo | tipo | note |
|---|---|---|
| msgid | STRING REQ | FK logica a f_pec_messages |
| nome_file | STRING REQ | |
| mime_type | STRING | |
| size_bytes | INT | |
| sha256 | STRING REQ | |
| is_firmato | BOOL | .p7m o firma rilevata |
| gcs_uri | STRING | gs://hotelops-raw/PEC_MAILBOX_INTUR_APPEND/allegati/<sha256[:2]>/<sha256>/<nome> — NULL solo se estrazione fallita (parse_warning) |
| hash_riga | STRING REQ | md5(msgid \| sha256 \| nome) via make_hash |
| raw_object_id | STRING REQ | |
| data_caricamento | DATETIME REQ | |

Nota governance: fatti documentali, non finanziari — I4 (3 dimensioni temporali)
non applicabile, dichiarato qui. societa_id sempre presente; BU non applicabile.
Schemi Pydantic `PecMessageRow`/`PecAllegatoRow` + `validate_batch`; scrittura solo
via `bq_write_validated` (I1). Nessun LLM nel parser (I5): entità/temi/contenziosi
= prompt successivo col pattern reviews.

**`v_pec_conversazioni`** (vista, I8): per ogni messaggio (tipo
MESSAGGIO_INVIATO o POSTA_CERTIFICATA) aggrega le ricevute via `ref_msgid` →
stato del ciclo (accettata? consegnata? quando?). I consumer non re-implementano
il join. Ogni semantica derivata tipo "direzione" vive qui, non nei fatti.

### No silent skips — report di promotion

Ogni promote stampa e ritorna: buste lette per file, righe nuove vs dedup,
buste senza daticert / senza postacert (contate per tipo: normale vs anomalo),
parse_warning, allegati estratti/riusati, e **coverage mensile della casella con
i vuoti > 14 giorni flaggati**. I malformati diventano righe con `parse_warning`
o conteggi espliciti — mai scartati in silenzio.

### Error handling

- Messaggio non parsabile → conteggiato + msgid sintetico da sha256, riga con
  `parse_warning`, mai abort dell'intero file.
- `daticert.xml` malformato → fallback su header busta + `parse_warning`.
- Charset/RFC2047 → `email` stdlib con fallback latin-1; mai UnicodeDecodeError fatale.
- Allegato non estraibile → riga f_pec_allegati senza gcs_uri + warning.

### Testing

- Fixture sintetiche: busta minima con daticert+postacert costruita ad arte,
  ricevuta di accettazione senza postacert, messaggio inviato, busta malformata.
- Golden test sul parse di daticert (msgid, mittente reale, ref_msgid).
- Idempotenza: stesso file promosso due volte → 0 righe nuove.
- Dedup cross-file: due mbox sovrapposti → nessun doppione su msgid.
- Test allegati: sha256 stabile, esclusione daticert/smime/postacert.

## Fuori scope (Prompt 1)

- Arricchimento LLM (entità, temi, collegamenti a contenziosi/contratti) — Prompt 2.
- Search / timeline / UI hub — Prompt 2/3.
- Document graph sugli allegati — Prompt 3 (il substrato sha256 nasce qui).
- Verifica crittografica delle firme smime/p7m (si registra `is_firmato`, non si valida).
- Caselle diverse da in.tur@pec.it (il pattern le supporta, si aggiungono al bisogno).

## Rischi e mitigazioni

- **Volume BQ**: ~2.200 messaggi + body_text → trascurabile (qualche decina di MB).
- **Allegati duplicati su GCS**: content-addressing li collassa.
- **Export futuri con pagine sovrapposte**: è il caso di design, coperto dal dedup.
- **Privacy**: contenuti sensibili (contenziosi, banche) — restano in GCS/BQ privati;
  qualunque superficie hub futura nasce `sensitive=True` (I10).
