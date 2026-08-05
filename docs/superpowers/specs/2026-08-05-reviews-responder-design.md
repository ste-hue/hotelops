# Reviews Responder — design

**Data:** 2026-08-05 · **Branch:** `feat/reviews-responder` · **Stato:** approvata da Stefano (brainstorming in chat)

## Problema

Le recensioni ospiti (Booking, Google, TripAdvisor, Expedia, Trip.com) restano
in gran parte senza risposta. Rispondere bene è revenue capture (rating ↑
correla con revenue +5–9%; response rate medio globale ~40%). Scrivere ogni
risposta a mano, nella lingua giusta e con la voce giusta, non scala.

Ispirazione: agent "review-responder" della guida Officina Turistica
(2026-05). Fuori scope: l'agent "review-trends" (analisi mensile temi).

## Decisioni prese (brainstorming 2026-08-05)

1. **Interfaccia: CLI**, non pagina hub (valutata e scartata: prima si vede
   la qualità delle bozze, la UI eventualmente dopo).
2. **Input manuale**: Stefano incolla il testo della recensione; il sistema
   genera la bozza. Nessuna coda automatica da `f_reviews` in v1.
3. **Firma unica** configurabile, default "Panorama Team" (non nome reale
   del direttore — scelta esplicita di Stefano, difforme dalla guida).
4. **Ristrutturazione**: molte review dicono "hotel datato" → il playbook
   per il tema STRUTTURA/datato menziona la ristrutturazione in corso
   (vale per BU HOTEL).
5. **Pubblicazione sempre manuale** sulla OTA (draft-only). Nessuna tabella
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

- `--bu HOTEL|RESIDENCE|CVM` **obbligatoria** con `--rispondi` (contesto:
  playbook ristrutturazione solo HOTEL).
- `--file PATH` alternativa a stdin. Testo vuoto → errore, exit ≠ 0.
- `--nota "..."` facoltativa: indicazione di Stefano per la singola risposta.
- Output: la bozza su stdout, nient'altro (pipe-friendly).

## Componenti

```
verticals/reviews/
  respond.py    <- nuovo: build_response_prompt() + generate_response() + validazioni
  voice.md      <- nuovo: la voce codificata (vedi sotto)
  config.py     <- RESPONDER_MODEL = Sonnet (il classificatore resta su Haiku)
  cli_commands.py <- flag --rispondi / --bu / --file / --nota
```

### `voice.md` — la voce codificata

Distillato (committato nel repo, editabile da Stefano) di:
- **Manifesto** e **Valori** dal handbook DOCS ("L'Ospite è il nostro Nord",
  "Autenticità, non Apparenza", "la parola no non fa parte del nostro
  vocabolario", "poche cose fatte bene");
- standard di servizio **TALENT** (iniziativa, sorriso, ascolto, empatia);
- **playbook per-tema**: per ora un solo tema — hotel datato/STRUTTURA →
  "ristrutturazione in corso" (solo HOTEL). Estendibile aggiungendo sezioni;
- **firma**: "Panorama Team" (configurabile qui).

`respond.py` legge `voice.md` a runtime e lo inserisce nel prompt: cambiare
la voce = editare il markdown, zero codice.

### Regole cablate nel prompt (dalla guida, non negoziabili)

- Risposta **nella lingua della recensione**.
- **Max 100 parole**.
- Ringraziamento **specifico** su dettagli concreti della recensione —
  mai generico, mai difensivo, mai promozionale.
- Sulle critiche: **UNA azione concreta** presa o pianificata, niente scuse
  generiche.
- Chiusa con la firma da `voice.md`.

## Flusso

```
stdin/--file → validazione (testo non vuoto, BU valida)
            → prompt = regole + voice.md + BU + [nota] + testo recensione
            → Claude (RESPONDER_MODEL, Sonnet)
            → bozza su stdout → Stefano rilegge, copia, pubblica sulla OTA
```

## Error handling

- `ANTHROPIC_API_KEY` mancante o chiamata API fallita → messaggio chiaro su
  stderr, exit ≠ 0 (nessun retry: si rilancia il comando).
- `--rispondi` senza `--bu`, BU sconosciuta, testo vuoto → errore immediato.
- Bozza oltre le 100 parole: warning su stderr, la bozza esce comunque
  (Stefano la rilegge sempre prima di pubblicare).

## Test

- Unit su `build_response_prompt()`: voce+playbook+firma inclusi, nota
  propagata quando presente, playbook ristrutturazione presente solo con
  `bu=HOTEL`, regole (lingua, 100 parole) presenti.
- Unit sulla CLI: stdin e `--file`, errori su testo vuoto / BU mancante,
  modello mockato.
- **Verifica finale a mano** (gate di chiusura del thread): 2–3 recensioni
  reali — una positiva, una "hotel datato", una in inglese — e il giudizio
  di Stefano sulle bozze.

## Definition of done

Il thread è chiuso quando `hotelops reviews --rispondi` produce bozze che
Stefano giudica pubblicabili su 3 recensioni reali (positiva / datato /
inglese), suite verde, branch pushato e presentato per il merge.

## Evoluzioni possibili (fuori scope, non promesse)

Prefill da `f_reviews`, tracking response rate, pagina hub, agent
review-trends mensile.
