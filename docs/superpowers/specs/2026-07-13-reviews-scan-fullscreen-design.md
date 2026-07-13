# Reviews — scan NLP a schermo intero (parità bottone Mutui)

**Data:** 2026-07-13 · **Stato:** approvato in chat (approccio 1 di 3)

## La domanda della pagina

Invariata: la pagina Reviews risponde a "com'è la reputation?". Questa feature non aggiunge
una seconda domanda — aggiunge una **modalità di lettura**: lo scan NLP (l'HTML
self-contained oggi embeddato in un iframe da 4300px) apribile da solo, a tutta finestra,
come il bottone "↗ Apri a schermo intero" della pagina Mutui.

## Design

- **Bottone** in cima alla pagina Reviews (modalità normale): `↗ Apri a schermo intero`,
  apre `/reviews?scan=full&…` in scheda nuova. I filtri correnti (anno, piattaforme, BU)
  viaggiano nell'URL così la vista fullscreen mostra esattamente ciò che si stava guardando.
- **Modalità fullscreen** (`scan=full` in `st.query_params`): `render()` corto-circuita —
  niente sidebar, niente tabella dettaglio; solo lo scan a piena altezza, con CSS che
  nasconde header/nav Streamlit e azzera il padding del container.
- **Stessa app, stesso cancello**: nessuna infrastruttura nuova; IAP e grant `roles.py`
  valgono identici (la modalità è un query param sulla pagina già concessa). Dati live BQ.

### Parametri URL

| Param | Valori | Default se assente |
|---|---|---|
| `scan` | `full` | — (modalità normale) |
| `anno` | int | anno di default della pagina (2026) |
| `piattaforme` | CSV di `PIATTAFORME` | tutte |
| `bu` | `HOTEL/RESIDENCE/CVM/LIDO` | tutte (assente) |

Valori malformati → si cade sul default (mai errore all'utente).

## Alternative scartate

- **Download HTML** (`st.download_button`): robusto ma "aprire" ≠ "scaricare".
- **Artifact esterno tipo Mutui** (Worker/bucket): porterebbe dati reviews fuori da IAP o
  richiederebbe auth propria; infrastruttura in più; snapshot stale.

## Test & gate

- Unit test sul parsing dei query param (funzione pura).
- Gate lettura CLAUDE.md: screenshot del render con dati REALI (entrambe le modalità)
  incollato in chat PRIMA del merge.
