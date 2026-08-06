# Reviews Responder — design

**Data:** 2026-08-05 · **Branch:** `feat/reviews-responder` · **Stato:** rev.2, integra la review di Stefano (anti-omologazione)

## Problema

Le recensioni ospiti (Booking, Google, TripAdvisor, Expedia, Trip.com) restano
in gran parte senza risposta. Rispondere bene è revenue capture (rating ↑
correla con revenue +5–9%; response rate medio globale ~40%). Scrivere ogni
risposta a mano, nella lingua giusta e con la voce giusta, non scala.

**Il problema vero non è generare una risposta: è evitare che dopo 100
recensioni sembrino tutte scritte dalla stessa AI.** Tutto il design è
orientato contro l'omologazione.

Ispirazione: agent "review-responder" della guida Officina Turistica
(2026-05). Fuori scope: l'agent "review-trends" (analisi mensile temi).

## Decisioni prese (brainstorming + review 2026-08-05)

1. **Interfaccia: CLI**, non pagina hub (prima si vede la qualità delle
   bozze, la UI eventualmente dopo).
2. **Input manuale**: Stefano incolla il testo della recensione; il sistema
   genera la bozza. Nessuna coda automatica da `f_reviews` in v1.
3. **Firma unica** configurabile, default "Panorama Team" (non nome reale
   del direttore — scelta esplicita di Stefano, difforme dalla guida).
4. **`voice.md` è fatto di VINCOLI, non di manifesto.** Il Manifesto/Valori
   del handbook produce frasi da marketing che il modello ricicla
   ("Crediamo nell'ospitalità autentica…"). La personalità sta tutta in
   `voice.md`; `respond.py` resta quasi stupido.
5. **Estrazione automatica dei temi** da lista fissa; il playbook si applica
   solo ai temi presenti. Oggi un solo playbook (STRUTTURA → ristrutturazione,
   solo HOTEL); i prossimi si aggiungono editando `voice.md`, zero codice.
6. **Pubblicazione sempre manuale** sulla OTA (draft-only). Nessuna tabella
   BQ: le bozze non sono fatti (coerente con la governance "le proiezioni
   non entrano nel pool f_*").

## Interfaccia

Nuovo flag del comando esistente `hotelops reviews`:

```bash
# testo da stdin (incolla + Ctrl-D)
hotelops reviews --rispondi --bu HOTEL

# testo da file, con indicazione una-tantum
hotelops reviews --rispondi --bu RESIDENCE --file rec.txt --nota "menziona la nuova colazione"

# uso tipico su Mac
hotelops reviews --rispondi --bu HOTEL < rec.txt | pbcopy
```

- `--bu HOTEL|RESIDENCE|CVM` **obbligatoria** con `--rispondi` (i playbook
  possono essere vincolati a una BU: ristrutturazione solo HOTEL).
- `--file PATH` alternativa a stdin. Testo vuoto → errore, exit ≠ 0.
- `--nota "..."` facoltativa: indicazione di Stefano per la singola risposta.
- Output: la bozza su stdout, nient'altro (pipe-friendly).

## Componenti

```
verticals/reviews/
  respond.py    <- nuovo: build_response_prompt() + generate_response() + validazioni
  voice.md      <- nuovo: la voce codificata come vincoli (vedi sotto)
  config.py     <- RESPONDER_MODEL = Sonnet (il classificatore resta su Haiku)
  cli_commands.py <- flag --rispondi / --bu / --file / --nota
```

### `voice.md` — vincoli, non manifesto

Committato nel repo, editabile da Stefano. Struttura:

**§ Voce** — vincoli di scrittura, nello spirito di:

```
Scrivi come una persona della reception.
Frasi corte.
Niente linguaggio da marketing.
Mai dire:
- "Siamo lieti"
- "La soddisfazione dell'ospite..."
- "Speriamo di riaverla presto"
Ringrazia solo per qualcosa di concreto.
Se una frase potrebbe andare bene sotto qualsiasi recensione, cancellala.
Non usare più di un aggettivo nella stessa frase.
Non descrivere l'hotel.
Rispondi all'ospite.
```

La blacklist di frasi vietate è viva: quando Stefano vede un tic ricorrente
nelle bozze, aggiunge la frase alla lista.

**§ Temi** — la lista fissa dei temi estraibili:
`PULIZIA, COLAZIONE, PERSONALE, POSIZIONE, RUMORE, PARCHEGGIO, CAMERA,
STRUTTURA, RISTORANTE, SPIAGGIA`.

**§ Playbook** — una sezione per tema, applicata SOLO se il tema è presente
nella recensione. Oggi:
- `STRUTTURA` (solo HOTEL): l'hotel è in fase di ristrutturazione — citarla
  come fatto, non come promessa vaga.

Aggiungere un playbook = aggiungere una sezione markdown.

**§ Firma** — "Panorama Team" (configurabile qui).

### Regole cablate nel prompt

Formulate in modo **verificabile**, mai come aggettivi ("sii specifico" no;
"cita un dettaglio" sì):

1. Risposta **nella lingua della recensione**.
2. **Max 100 parole**. Nessun minimo: non aggiungere testo per arrivare a
   una lunghezza.
3. Il ringraziamento **deve citare almeno un dettaglio presente nella
   recensione**.
4. **Ogni frase deve fare almeno una di queste tre cose**, altrimenti va
   eliminata:
   - rispondere a qualcosa scritto dall'ospite;
   - aggiungere un fatto;
   - descrivere un'azione concreta.
5. Critiche: **se è credibile, cita un'azione concreta** presa o pianificata.
   **Se non puoi citarne una, limita la risposta al riconoscimento del
   problema senza inventare interventi.** Mai promesse non supportate da
   fatti (i fatti citabili stanno nei playbook).
6. Prima estrai i temi della recensione dalla lista in `voice.md`; applica i
   playbook solo per i temi trovati.
7. **Fase di pulizia finale** (nel prompt, prima di restituire):

   ```
   Rileggi il testo.
   Elimina ogni frase che potrebbe essere copiata sotto una recensione diversa.
   Se restano meno di 40 parole va bene.
   Non aggiungere testo per arrivare a una certa lunghezza.
   ```

8. Chiusa con la firma da `voice.md`.

## Flusso

```
stdin/--file → validazione (testo non vuoto, BU valida)
            → prompt = regole + voice.md (vincoli, temi, playbook, firma) + BU + [nota] + testo recensione
            → Claude (RESPONDER_MODEL, Sonnet): estrazione temi → bozza → pulizia
            → bozza su stdout → Stefano rilegge, copia, pubblica sulla OTA
```

Estrazione temi, generazione e pulizia stanno in **una sola chiamata**
(il prompt guida le fasi); si passa a chiamate separate solo se la verifica
a mano mostra che la pulizia in-prompt non basta.

## Error handling

- `ANTHROPIC_API_KEY` mancante o chiamata API fallita → messaggio chiaro su
  stderr, exit ≠ 0 (nessun retry: si rilancia il comando).
- `--rispondi` senza `--bu`, BU sconosciuta, testo vuoto → errore immediato.
- Bozza oltre le 100 parole: warning su stderr, la bozza esce comunque
  (Stefano la rilegge sempre prima di pubblicare).

## Test

- Unit su `build_response_prompt()`: vincoli/temi/playbook/firma inclusi,
  nota propagata quando presente, playbook STRUTTURA presente solo con
  `bu=HOTEL`, regole verificabili (lingua, 100 parole, tre-funzioni-per-frase,
  fase di pulizia) presenti nel prompt.
- Unit sulla CLI: stdin e `--file`, errori su testo vuoto / BU mancante,
  modello mockato.
- Verifica finale a mano sulle bozze reali, contro la checklist della DoD.

## Definition of done

Il thread è chiuso quando, su un set di recensioni reali (almeno: una
positiva, una "hotel datato", una in inglese, una molto negativa senza
azione citabile), **ogni bozza passa questa checklist**:

- [ ] nessuna frase generica (= che potrebbe stare sotto un'altra recensione);
- [ ] nessuna frase presente identica in due bozze diverse;
- [ ] risposta nella lingua della recensione;
- [ ] sotto le 100 parole;
- [ ] almeno un riferimento concreto alla recensione;
- [ ] nessuna promessa non supportata dai fatti (playbook o nota).

Più: suite verde, branch pushato e presentato per il merge. La checklist è
formulata per essere in parte automatizzabile in futuro (lunghezza, lingua,
frasi duplicate cross-bozze).

## Evoluzioni possibili (fuori scope, non promesse)

Prefill da `f_reviews`, tracking response rate, pagina hub, agent
review-trends mensile, check automatici della checklist DoD.

### Prossima (approvata da Stefano 2026-08-06): loop "esempi promossi"

Quando Stefano pubblica una risposta (così com'è o editata), la promuove:
la coppia recensione → risposta pubblicata viene archiviata (v1: file
markdown accanto a `voice.md`, appeso via flag CLI) e il prompt include gli
ultimi N esempi promossi come **ancore di stile**, con vincolo esplicito
"imita registro e struttura, MAI riusare frasi" — il few-shot ingenuo
farebbe l'opposto (omologazione); il check DoD anti-duplicati resta la rete.

Nota dati: `f_reviews` **non ha alcun campo risposta** — le risposte
pubblicate non sono mai state scrappate né memorizzate. A differenza delle
bozze, la risposta *pubblicata* è un fatto osservabile (sta sulla OTA):
un'eventuale `f_review_risposte` in BQ sarebbe legittima e darebbe anche il
response rate. V1 comunque zero-infra (markdown + CLI).
