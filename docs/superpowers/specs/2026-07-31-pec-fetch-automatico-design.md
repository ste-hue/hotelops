# PEC fetch automatico (IMAP) — Design

**Data:** 2026-07-31 · **Stato:** approvato da Stefano (sessione 2026-07-31)
**Predecessore:** `2026-07-17-pec-multicasella-pannello-ceo-design.md`
**Chiude:** la voce *Fuori scope (MVP)* di quel design — *"ingest automatico dalla
webmail (l'export resta manuale)"*.

## Contesto e obiettivo

Il registro PEC multi-casella è progettato e in parte in produzione: parser unico,
`f_pec_messages` + `f_pec_allegati`, classificazione, pannello CEO. Manca il primo
metro del tubo: **oggi l'mbox lo scarica Stefano a mano dalla webmail**.

Il costo non è il tempo dello scarico — è che un passo manuale non avviene. Il caso
concreto che ha aperto la sessione: la richiesta di Plan Italia dell'E/C AMALFI COAST
del II trimestre, ferma dal 16 luglio, non perché nessuno l'avesse letta ma perché
nessun processo la sorvegliava.

Obiettivo: sostituire il gesto umano con un job notturno, **senza toccare nulla a
valle**.

## Scope

Dentro: connessione IMAP alle quattro caselle PEC, download delle buste nuove,
consegna a `hotelops intake`.

Fuori: parser, classificazione, pannello, digest (già progettati in `2026-07-17`);
invio PEC; ingresso di VIGNA in `SocietaId`/contabilità (resta fuori — vedi sotto).

## Le quattro caselle

| `entity_id` | Casella | Host IMAP | Porta |
|---|---|---|---|
| `INTUR` | `in.tur@pec.it` | `imaps.pec.aruba.it` | 993 SSL |
| `ORTI` | `orti@pec.it` | `imaps.pec.aruba.it` | 993 SSL |
| `VIGNA` | `vineyardamalficoast@pec.it` | `imaps.pec.aruba.it` | 993 SSL |
| `STEFANO_PERSONALE` | `stefanojunior.dellapietra@mpspec.it` | *da rilevare* | *da rilevare* |

Tre su Aruba nonostante il dominio `pec.it`; la quarta su provider diverso. Host e
porta sono **config per casella**, mai costanti nel codice: il caso `mpspec.it`
dimostra che l'assunzione "tutte Aruba" sarebbe falsa.

`STEFANO_PERSONALE` viene ingerita nel registro ma **mai proiettata sul pannello
CEO**, coerentemente con `2026-07-17` (che ha già un test dedicato a questo
isolamento).

## Architettura

```
4 caselle PEC (IMAP, sola lettura)
  → ingest/pec_fetch.py          # NUOVO: fetch buste nuove → mbox
  → hotelops intake              # invariato — GCS raw + f_raw_objects (dedup MD5)
  → hotelops promote             # invariato — gate policy
  → ingest/flussi/ingest_pec_mbox.py   # invariato
  → f_pec_messages + f_pec_allegati
```

**La scelta portante:** il fetcher produce lo stesso artefatto che oggi Stefano
scarica a mano, e lo consegna alla pipeline esistente. Il fetcher sa di IMAP e non
sa nulla di PEC; il parser sa di PEC e non sa nulla di come è arrivato il file.

Modellato su `ingest/drive_fetch.py`, che fa già questo per i corrispettivi spiaggia:
pull da fonte viva, consegna al lineage.

## Sola lettura — vincolo, non preferenza

La connessione IMAP è **read-only**, senza il permesso tecnico di modificare la
casella. Nessun flag, nessun `\Seen`, nessuna label lato server.

Motivo: sono caselle con valore probatorio. Un processo automatico che marca i
messaggi interferisce con la lettura umana, e "il sistema ha modificato la casella
PEC" è una frase che in un contenzioso costa più di quanto valga il risparmio.

SMTP (`smtps.pec.aruba.it:465`) **non viene configurato**. Un ingest non invia. Una
macchina che può spedire atti con valore legale è rischio senza beneficio.

## Idempotenza: due meccanismi, due lavori

1. **Watermark UID** (efficienza) — per ogni casella si conserva l'ultimo UID visto;
   il giro successivo chiede solo `UID > watermark`. Stato in BQ/GCS, mai solo
   locale, coerente col principio di autorità di `2026-07-17`.
2. **Content-hash all'intake** (correttezza) — `f_raw_objects` deduplica su MD5 del
   contenuto; `filter_new_rows_by_hash` protegge a valle.

Non sono ridondanti. Se un watermark si perde o una casella va riletta da capo, il
giro riscarica — e l'hash impedisce che questo sporchi i dati. Il rischio è reale e
recente: l'ultimo commit del repo documenta la trappola dedup su re-export con
finestre sovrapposte.

**Il test che conta:** stesso messaggio pescato due volte non produce due righe.

## Dove gira

Cloud Run Job + Cloud Scheduler, come `spiaggia-corrispettivi-daily`. Cadenza
giornaliera notturna.

Le quattro password PEC in **Secret Manager**, non su disco: gira in cloud e sono
credenziali di caselle legalmente rilevanti.

## Errori

Una casella irraggiungibile non fa fallire il giro: le altre proseguono, e il run
registra `PARZIALE` con l'elenco di cosa non è stato raggiunto. Nessuno stato
parziale non registrato — stessa regola di `2026-07-17`.

Il silenzio è il modo in cui questi sistemi mentono. Su una casella PEC, mentire è
caro: un giro che non ha letto INTUR deve dirlo, non passare per riuscito.

## Test

- Unit: parsing config per casella; calcolo watermark; connessione read-only
  (tentativo di scrittura → errore, non silenzioso).
- Integrazione: server IMAP finto con buste note; casella irraggiungibile; casella
  vuota; UID non contiguo (messaggi cancellati a mano dalla webmail).
- End-to-end su fixture: fetch → intake → promote → parse, poi **ripetizione
  integrale con zero duplicati**.
- Isolamento fra entity: una casella non contamina il bucket di un'altra.

## Questioni aperte

1. **Host IMAP di `mpspec.it`** — da rilevare dalla configurazione del client di
   Stefano prima dell'implementazione.
2. **Nomi delle nuove sorgenti** — `PEC_MAILBOX_INTUR_APPEND` esiste. Le altre tre
   seguono la grammatica a 4 parti, ma lo slot società ospita un `entity_id`
   (`VIGNA`, `STEFANO`) che non è una società contabile: confermare la convenzione
   con quanto già deciso in `2026-07-17` sui bucket `orti-raw`/`vigna-raw`/`stefano-raw`.
3. **Finestra di sicurezza** — oltre al watermark, conviene rileggere gli ultimi N
   giorni a ogni giro per catturare buste arrivate fuori ordine? Costa poco (l'hash
   protegge) e chiude un buco silenzioso. Proposta: sì, 7 giorni.

## Nota di correzione

In sessione era stato proposto di allargare `SocietaId` a `Literal["ORTI","INTUR",
"VIGNA"]` per far posto alla vigna. **Proposta ritirata:** `2026-07-17` aveva già
risolto con `entity_id`, identità locale al dominio PEC e deliberatamente separata
da `societa_id`. La vigna entra nel registro PEC senza entrare nella contabilità di
gruppo, che è il comportamento corretto. `core/schemas.py:23` non si tocca.
