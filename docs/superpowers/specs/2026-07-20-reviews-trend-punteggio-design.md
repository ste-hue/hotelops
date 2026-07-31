# Trend punteggio recensioni — design

**Data:** 2026-07-20 · **Vertical:** reviews · **Stato:** approvato (approccio A)

## La domanda (una pagina, una domanda)

**"Il punteggio delle recensioni sta andando su o giù?"**

Sezione nuova nella dashboard reviews esistente (`verticals/reviews/app.py`),
tra lo scan NLP e la tabella "Dettaglio review". Non è una pagina nuova.

## Design

- **Serie:** media mensile di `punteggio_norm`, **una linea per BU**
  (HOTEL/RESIDENCE/CVM/LIDO), calcolata sul `df` già caricato da
  `load_reviews()` — zero query BQ aggiuntive. Rispetta i filtri
  anno/piattaforme della sidebar (il filtro BU riduce a una linea sola).
- **Smoothing:** media mensile (scelta esplicita di Stefano vs media mobile).
- **Low-sample guard:** mesi con `n < 3` review per BU → marker vuoto
  (open circle), così un 9.5 fatto da 2 review non inganna. Hover mostra
  sempre `n` e media. (Famiglia "segni in presentazione", CLAUDE.md.)
- **Libreria:** plotly (già nell'extra `[dashboard]`), `st.plotly_chart`.
- **Aggregazione:** funzione pura `monthly_trend(df) -> pd.DataFrame`
  (colonne: mese, business_unit_id, media, n) — testabile senza Streamlit.

## Alternative scartate

- **B — SVG dentro lo scan HTML** (`scan.py`): appare anche in `?scan=full`
  ma niente interattività e tocca un file denso da 584 righe.
- **C — pagina hub dedicata:** overkill per una singola domanda.
- **Media mobile ultime N review:** più reattiva, scartata da Stefano
  a favore della leggibilità mensile.

## Test & gate

- Unit test su `monthly_trend`: media per (mese, BU), conteggio `n`,
  mesi senza review assenti (nessuna interpolazione).
- Gate hub (CLAUDE.md): render con dati REALI visto da Stefano in chat
  PRIMA del merge.
