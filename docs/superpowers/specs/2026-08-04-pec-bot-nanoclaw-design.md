# Bot PEC su NanoClaw — digest giornaliero su WhatsApp — Design

**Data:** 2026-08-04 · **Stato:** approvato da Stefano (sessione 2026-08-04)
**Predecessori:** `2026-07-17-pec-multicasella-pannello-ceo-design.md` (classify,
pannello, digest) · `2026-07-31-pec-fetch-automatico-design.md` (job notturno IMAP)

## Contesto e obiettivo

Il tubo PEC è costruito fino a metà. `pec-fetch` gira ogni notte alle 04:00 su Cloud
Run e scarica le tre caselle societarie in GCS + `f_pec_messages`. Da lì in poi non si
muove più niente da solo: `classify` e `digest` esistono come comandi CLI ma non sono
schedulati da nessuna parte.

Lo stato al 2026-08-04, verificato:

| tabella | righe |
|---|---|
| `f_pec_messages` | 2.751 |
| `f_pec_classificazioni` | 2.711 (backfill manuale) |
| `f_pec_panel_projections` | 450 |
| `f_pec_digest_runs` | **non esiste** |

Le 2.711 classificazioni sono un backfill fatto a mano. Sui messaggi arrivati dal job
notturno, invece:

| giorno di carico | messaggi | senza classificazione |
|---|---|---|
| 2026-08-01 | 27 | 27 |
| 2026-08-03 | 7 | 7 |

Il digest non è mai stato eseguito: la tabella di checkpoint non esiste e la cartella
`AMM_CEO/_digest/` non è mai stata creata.

Il costo non è che manchi un report. È che **una PEC che conta può restare in
BigQuery per settimane senza che nessuno la guardi** — la stessa dinamica che ha
motivato il fetch automatico: un passo che dipende da un gesto umano non avviene.

Obiettivo: chiudere il tubo fino alla notifica. Ogni mattina, su WhatsApp, un
messaggio che dice cosa è arrivato e se il sistema è vivo.

## Scope

Dentro: `classify` in cloud dopo il fetch; una `scheduled_task` NanoClaw che esegue
`digest --format json` e manda un messaggio WhatsApp; il contratto di formattazione
del messaggio; il grant IAM che lo rende possibile.

Fuori: modifiche al parser, al classificatore o al ruleset; il pannello CEO
(`sync-panel` resta manuale); il markdown del digest su Drive (**esplicitamente non
voluto**); notifiche in tempo reale sulla singola PEC; la casella
`STEFANO_PERSONALE`, che il job non fetcha già oggi.

## Decisioni

### D1 — Digest giornaliero, non allarme per singola PEC

Il bot manda un riassunto una volta al giorno. Un allarme per singola PEC
richiederebbe un polling più frequente delle 04:00, cioè un secondo fetcher: costo
sproporzionato al volume reale (poche PEC a settimana).

### D2 — Messaggio sempre, anche quando non c'è niente

Il caso normale è "nessuna PEC rilevante". Se in quel caso il bot tace, il silenzio
diventa indistinguibile dal bot morto, e siccome il silenzio è la maggioranza dei
giorni non te ne accorgi finché non serve. Il messaggio arriva sempre; nei giorni
tranquilli è due righe.

Corollario vincolante: **anche il fallimento diventa un messaggio.** In un design dove
il silenzio è normale, un errore silenzioso è invisibile. Il silenzio deve significare
una cosa sola: NanoClaw non gira.

### D3 — WhatsApp porta il segnale, non la diagnostica

Il digest ha sette sezioni e due nature: "cosa è arrivato che conta" (importanti) e
"come sta la pipeline" (errori di parsing, ambigui, non classificati, allegati non
proiettati). Su WhatsApp va solo la prima, più **una riga** di salute con i conteggi.
Chi vuole il dettaglio interroga BigQuery.

### D4 — Il checkpoint sta con chi notifica

`f_pec_digest_runs` significa "già notificato", non "già calcolato". Se il digest lo
eseguisse il cloud, consumerebbe la finestra e il bot troverebbe sempre vuoto:
servirebbe un secondo stato per "mandato su WhatsApp", e due stati che descrivono lo
stesso fatto prima o poi si contraddicono. Quindi `classify` in cloud (idempotente,
senza semantica di finestra) e `digest` in NanoClaw.

Conseguenza accettata: col Mac spento non parte nessuna notifica, ma il dato continua
ad aggiornarsi in cloud e al ritorno la finestra copre il buco. Si perde tempestività,
mai contenuto.

### D5 — `classify` concatenato al fetch nello stesso job

Non un secondo Cloud Run Job con scheduler alle 04:30: `pec-fetch` ha
`task-timeout=3600s` proprio perché una giornata pesante si allunga, e un job separato
partirebbe a fetch ancora in corso. Concatenare nello stesso container è l'unico modo
di garantire l'ordine senza inventare un segnale tra job.

### D6 — Niente markdown su Drive

Già supportato senza modifiche al codice: in `run_digest` la scrittura del file avviene
**solo** nel ramo `fmt == "markdown"`. Con `--format json` si ottiene il payload e il
checkpoint, nessun file.

## Architettura

```
04:00  Cloud Run "pec-fetch"   fetch ─▶ GCS + f_pec_messages
       (SA drive-audit@)       classify ─▶ f_pec_classificazioni

07:00  NanoClaw gruppo hotelops  digest --format json ─▶ f_pec_digest_runs
       (SA hotelops-nanoclaw@)                        └─▶ messaggio WhatsApp
```

Il cloud non sa che esiste WhatsApp; NanoClaw non sa come si scarica una PEC. L'unico
contratto tra i due è BigQuery.

### Componente 1 — job cloud

`scripts/cloud/70_pec_fetch.sh`: il job passa da un singolo comando a due in sequenza,
con `&&` — se il fetch fallisce, `classify` non gira su dati parziali.

```
python -m ingest.pec_fetch --all && python -m cli pec classify
```

`classify` è **rule-based** (`core/pec_ruleset.yaml`, regex su mittente/oggetto/nomi
allegati): nessuna chiamata LLM, nessuna API key, nessun costo per messaggio, esito
deterministico e ripetibile. Scrive su `f_pec_classificazioni` via
`bq_write_validated`; `drive-audit@` ha già i permessi perché scrive già
`f_pec_messages`.

### Componente 2 — task NanoClaw

Gruppo **`aziende`**, jid `120363426493586217@g.us`, cron `0 7 * * *` (Europe/Rome).

Non `hotelops`, che pure avrebbe già tutti i mount pronti: `aziende` monta già
`gmail-intur`, `gmail-orti`, `gmail-vigna` — la sua identità *è* la posta delle tre
società, e la PEC è la stessa materia con un altro protocollo. `hotelops` è il
cruscotto finanziario: mandarci le notifiche PEC mescola due conversazioni diverse.
Un gruppo dedicato (`PECS`) si giustificherebbe solo se cambiasse il **pubblico** —
per esempio Rosa o Antonio nelle notifiche PEC ma non nelle Gmail societarie — non
perché cambia l'argomento.

Il prezzo è che `aziende` oggi ha solo i tre tool Gmail e nessun mount. Vanno aggiunti,
in `containerConfig`:

- repo hotelops → `hotelops-repo`, `readonly: true`
- `~/.config/hotelops/hotelops-nanoclaw-key.json` → `secrets/hotelops-nanoclaw-key.json`,
  **`readonly: true`** — l'allowlist ha quel root con `allowReadWrite: false`, quindi un
  mount rw verrebbe rifiutato
- tool `bq`, che inietta `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`,
  `PYTHONPATH`

Fatti verificati lato NanoClaw (non serve riaprire quel repo):

- l'immagine `nanoclaw-agent:latest` è **unica per tutti i gruppi** e il suo
  `python-requirements.txt` ha già `google-cloud-bigquery`, `pydantic`, `pyyaml` — le
  dipendenze non sono un rischio, lo smoke test verifica rete e auth
- **nessun flag di rete per gruppo**: la connettività è identica ovunque
- `registeredGroups` è una **cache in memoria**: dopo l'UPDATE della configurazione
  serve un kickstart del processo, altrimenti il container gira con i mount vecchi

Nota: `groups/hotelops/group_config.yaml` **non è letto da NanoClaw** — nessun
riferimento nel sorgente. I mount veri vengono da `containerConfig.additionalMounts`
in `store/messages.db`. Quel file è documentazione, e il suo `internet: false` non
descrive il comportamento reale.

Comando eseguito dal task:

```
cd /workspace/extra/hotelops-repo && python -m cli pec digest --format json
```

### Componente 3 — contratto del messaggio

Con PEC rilevanti:

```
PEC 04/08 — 2 da guardare
• INTUR [FISCO] Avviso bonario 2024 — da Agenzia Entrate
• ORTI [LEGALE] Diffida — da avv. Rossi
9 nuove (INTUR 6, ORTI 3) · 1 non classificata
```

Senza:

```
PEC 04/08 — niente di rilevante
3 nuove (INTUR 2, ORTI 1) · 0 non classificate
```

Regole: una riga per messaggio importante, **massimo 8**, poi `…e altre N`; la riga di
salute chiude sempre, con i conteggi da `totali_per_casella` e `non_classificati`;
nessun commento, interpretazione o consiglio aggiunto dall'agente.

Il prompt del task è il contratto. Tre vincoli espliciti, ognuno contro un
comportamento probabile dell'agente:

| Vincolo nel prompt | Comportamento che previene |
|---|---|
| "esegui il comando una volta sola" | il riflesso di ritentare un comando dall'output scarno — con il checkpoint consumato, ritentare *cancella* la notifica |
| "manda solo il messaggio, niente commenti" | l'agente che aggiunge consigli e in un mese rende il digest illeggibile |
| "se fallisce manda l'errore, mai silenzio" | il fallimento silenzioso, indistinguibile da una giornata tranquilla (vedi D2) |

## Errori

| Situazione | Comportamento |
|---|---|
| `digest` esce non-zero (BQ irraggiungibile, permessi, crash) | messaggio `PEC gg/mm — digest fallito: <prima riga errore>`; il checkpoint resta `FAILED` e la finestra non avanza |
| `RuntimeError: un digest è già RUNNING` (guardia `_run_aperto`, run precedente crashato) | il bot lo riporta come fallimento e **non** ritenta: va sbloccato a mano marcando il run `FAILED` |
| Mac spento | nessun messaggio; al risveglio la finestra copre il buco |
| Cloud `classify` fallito | il digest gira lo stesso e le PEC del giorno finiscono nel conteggio `non classificate` — visibile nella riga di salute |

## Prerequisiti, in ordine

L'ordine è vincolante: invertirlo fa fallire il primo giro alle 07:00.

1. **Cloud**: aggiungere `classify` al job. Senza, i messaggi nuovi restano non
   classificati (i 34 del 1 e 3 agosto lo sono adesso) e il digest ha zero importanti
   con tutto in "da rivedere".
2. **Primo run da locale** con `--da` esplicito. Serve perché `run_digest` senza
   SUCCESS precedenti cade sul default `EPOCA_CORPUS = 2018-01-01`: il primo messaggio
   conterrebbe otto anni di PEC. Il run crea `f_pec_digest_runs` e pianta il
   checkpoint.
3. **IAM**: grant di scrittura su `f_pec_digest_runs` (che a quel punto esiste) alla SA
   `hotelops-nanoclaw@hotelops-suite.iam.gserviceaccount.com`, che oggi ha solo
   `bigquery.dataViewer` + `bigquery.jobUser`. **A livello di tabella**, non
   `dataEditor` sul dataset: quest'ultimo aprirebbe in scrittura tutto il pool `f_*` a
   un agente conversazionale.
4. **Configurare il gruppo `aziende`** (mount del repo + chiave, tool `bq`) e fare il
   **kickstart** di NanoClaw: `registeredGroups` è cache in memoria, senza riavvio il
   container gira con i mount vecchi.
5. **Registrare il task** su NanoClaw dal gruppo Aziende.

## Test

- **Formattatore**: payload JSON finto → messaggio atteso. Casi: zero importanti; uno;
  nove (verifica il troncamento a 8 + `…e altre N`); `totali_per_casella` vuoto.
- **`digest --format json --dry-run`**: non scrive il checkpoint, quindi si può
  lanciare a mano quante volte serve per vedere il payload reale prima del primo run
  vero.
- **Job cloud**: `gcloud run jobs execute pec-fetch --wait` e verifica che i 34
  messaggi non classificati passino a classificati.
- **Gate di lettura**: il primo messaggio WhatsApp reale va visto da Stefano prima di
  considerare il lavoro chiuso. Un digest che quadra ma non si legge sul telefono è un
  digest fallito (regola "pagine hub" del CLAUDE.md, applicata al canale).

## Cosa resta aperto dopo questo lavoro

- `sync-panel` continua a girare a mano: gli allegati importanti non finiscono su
  AMM_CEO da soli. La riga "allegati non sincronizzati" del digest esiste per questo,
  ma qui non arriva su WhatsApp.
- La casella `STEFANO_PERSONALE` resta fuori dal fetch.
- Nessun canale di risposta: il bot notifica, non accetta comandi tipo "archivia" o
  "questa non è importante". La riclassificazione umana resta via override su BQ.
