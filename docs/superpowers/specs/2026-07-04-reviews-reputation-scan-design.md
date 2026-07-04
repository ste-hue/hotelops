# Reviews Reputation Scan — Design

**Data:** 2026-07-04 · **Vertical:** reviews · **Stato:** approvato

## Obiettivo

La pagina Reviews del hub diventa *il* posto dove si vede il quadro generale
della reputation e tutte le review: sopra lo scan NLP (keywords positive/negative,
temi, trend, fotografia sintetica), sotto il dettaglio browsabile.

Origine: scan NLP one-off del 2026-07-04 (artifact condiviso via claude.ai),
da rendere parte permanente del vertical. Scelte utente: report HTML statico
(non ricostruito nativo Streamlit), servito come pagina nel hub (IAP),
complessità minima.

## Componenti

### 1. `verticals/reviews/scan.py` (nuovo)

Due funzioni pure (nessuna dipendenza da BQ o Streamlit — testabili in isolamento):

- `build_scan(rows: list[dict]) -> dict`
  - Input: righe `f_reviews` come dict (campi usati: `data_review`, `piattaforma`,
    `business_unit_id`, `punteggio_norm`, `lingua`, `titolo`, `testo`,
    `testo_positivo`, `testo_negativo`, `categoria_nlp`, `riassunto_nlp`,
    `reviewer_paese`, `tipo_viaggio`).
  - Corpus positivo/negativo: campi `testo_positivo`/`testo_negativo` quando
    presenti (Booking/Expedia); fallback su `titolo + testo` intero assegnato
    per voto (≥8 → positivo, ≤6 → negativo, 6–8 scartato) per Google/TripAdvisor.
  - Output dict: keywords pos/neg (tokenizzazione multilingua it/en/de/fr/es,
    stopword + junk di rating rimossi), bigrammi, conteggi per tema
    (bucket keyword→tema multilingua), aggregati per mese/BU/piattaforma/
    tipo_viaggio/paese, distribuzione voti 1–10, elenco negative (≤6) con riassunto.

- `render_scan_html(scan: dict, anno: int) -> str`
  - Rende l'HTML self-contained (CSS inline, token light/dark via
    `prefers-color-scheme`, nessun JS, nessuna risorsa esterna) con le sezioni:
    KPI, La fotografia, trend mensile, wordcloud pos/neg, temi divergenti,
    card per BU, distribuzione voti, tabelle piattaforme/segmenti/paesi,
    elenco negative.
  - **La fotografia = deterministica da template**: frasi generate da regole sui
    dati (mese più debole, tema negativo più frequente, segmento con media
    peggiore, quota 10/10). Nessuna chiamata LLM.

### 2. Refactor `verticals/reviews/app.py`

- Sidebar invariata (anno, piattaforme, BU, sentiment, ricarica).
- Corpo della pagina:
  1. **Quadro generale** — `st.components.v1.html(render_scan_html(build_scan(rows), anno), height=…, scrolling=True)`
     calcolato dal DataFrame già caricato da `load_reviews` (stessa cache ttl=300).
     Cambio filtri ⇒ scan ricalcolato sulle righe filtrate.
  2. **Dettaglio review** — la sezione tabellare esistente, invariata.
- **Si eliminano** le sezioni plotly "Trend punteggio medio mensile" e
  "Categorie" (duplicate dallo scan, meglio rese lì).

## Non-goal (YAGNI)

- Nessun comando CLI `--scan` (aggiungibile dopo sul motore condiviso).
- Nessun upload GCS, nessun tile nuovo nel registry, nessuna email.
- Nessuna sintesi LLM.

## Test

`tests/test_reviews_scan.py`:
- `build_scan` su righe sintetiche: split corpus pos/neg (campi Booking vs
  fallback per voto), tokenizzazione/stopword, conteggio temi, aggregati,
  distribuzione voti, elenco negative.
- `render_scan_html`: smoke — stringa HTML con sezioni attese, escaping di
  testo utente (recensioni contengono HTML/quote), nessun placeholder vuoto
  con 0 righe (caso df vuoto gestito a monte in app.py).

## Rischi / note

- `st.components.v1.html` renderizza in iframe: serve `height` esplicito
  (~4200px) o scroll interno; scelta finale in implementazione, criterio =
  nessun doppio-scroll fastidioso.
- I testi review sono input non fidato: escaping HTML ovunque nel renderer.
- La pagina hub monta `verticals.reviews.app.render()` (nessuna modifica al hub).
