# Bilancini — artifact consultabile + terzo layout parser

**Data:** 2026-07-14 · **Stato:** design approvato a voce, in review scritta
**Decisioni prese con Stefano:** niente vertical nuovo (condges resta il dominio); deliverable = artifact Claude statico "tipo i mutui"; maggio ORTI → il re-export sostituisce (stesso trattamento per aprile, droppato dopo: 22 conti rettificati vs BQ); scope ORTI+INTUR (INTUR solo navigatore, senza budget).

## La domanda della pagina

> **"Come sta andando il bilancio a oggi, e come ci siamo arrivati?"**

Ogni elemento dell'artifact si giustifica contro questa domanda (regola "una pagina, una domanda"). Le sotto-letture — a oggi, progressione, peso del mese, scostamento vs budget, red flags — sono sezioni, non pagine separate.

## Contesto

- `f_bilancino` è il backbone COMPETENZA del CdG (decisione 2026-06-22); `v_ce_mensile_bilancino` ricava il mese per differenza YTD.
- Copertura attuale: ORTI e INTUR fino a 2026-05. Stefano ha droppato tre export nuovi ORTI (aprile e maggio re-export + giugno) in un **terzo layout** che il parser non supporta. Il layout ha due varianti: 5 colonne (maggio/giugno) e 11 colonne con Progressivi annui/periodici (aprile) → risoluzione colonne per nome header, obbligatoria.
- I re-export contengono rettifiche (maggio: es. `47.91.07.02` Ricavi bar 52.747,38 vs 52.780,11 in BQ, 160 foglie vs 165 righe caricate; aprile: 22 conti diversi, tra cui banca `19.01.01` −6,7k e fornitori `33.03.01` −6,9k). Il dedup per hash li salterebbe in silenzio → serve sostituzione esplicita.
- ⚠️ I file di maggio e giugno sono spariti dal Desktop prima dell'intake (lezione: intake al primo drop, sempre). Aprile è già in GCS (`raw_object_id 0fe78f07-9b49-4369-8fc5-f9685af02477`, stato CLASSIFIED); maggio e giugno vanno ridroppati da Stefano.
- Budget a livello conto disponibile in `Budget_ORTI_2026.xlsx` (fogli Ricavi/Fissi/Variabili/Personale/Finanziari, `codice_conto × mese`) + `Incidenza_costi_personale.xlsx` (personale per reparto/mese). Stessa chiave del bilancino → join pulito.

## Parte 1 — Pipeline (prerequisito)

### 1a. Estensione parser `ingest/flussi/ingest_bilancino.py`

Nuovo branch in `_parse_xlsx` per il terzo layout, riconosciuto da header
`('Conto', 'Partitari', 'Descrizione', 'Saldo finale Dare', 'Saldo finale Avere')`
(match su `header[0] == 'conto'` dopo strip/lower, per non collidere con la griglia che inizia con `codice conto`). Colonne risolte **per nome header**: la variante di aprile aggiunge 6 colonne di Progressivi annui/periodici, si usano solo `Saldo finale Dare`/`Saldo finale Avere`:

- **Leaf detection:** assenza di figli (nessun altro codice inizia con `codice + '.'`). I marker Partitari (S/C/F/B) NON bastano: 147 foglie CE sono senza marker.
- **Importi:** `dare`/`avere` dal file (positivi); `saldo = dare − avere`. Verificato coerente con le convenzioni esistenti (ricavi < 0, costi > 0, attività > 0).
- **tipo_conto:** dal prefisso top-level, boundary derivato dai dati esistenti: CE se `47 ≤ int(prefisso) ≤ 88`, SP altrimenti (89 = SP, come nello storico).
- **sezione:** CE → `Ricavi` se prefisso `47`, altrimenti `Costi` (ciò che serve a `v_ce_mensile_bilancino`); SP → stringa vuota (categoria fallback `PATRIMONIALE` — accettato, la vista consumer filtra solo CE).
- Righe a importo zero: escluse (come gli altri layout).

**Attesi dry-run:** giugno 168 righe, maggio 160, aprile ~154; per tutti sbilancio dare−avere = −241.772,91 (= risultato a nuovo già in BQ).

### 1b. Ingest

Entrambi i file via lineage (source `ESOLVER_BILANCINO_ORTI_SNAPSHOT`, promotion AUTO), con copia rinominata per l'inferenza mese nel path di promotion (che passa solo `--file --societa --raw-object-id`):

1. Copia `bilancioOrtial30giugno.XLSX` → `esolver_bilancino_ORTI_2026-06.xlsx`; `BilancioORTIal30maggio.XLSX` → `esolver_bilancino_ORTI_2026-05_reexport.xlsx` (il pattern numerico basta all'inferenza mese). Aprile già intaken come `esolver_bilancino_ORTI_2026-04_reexport.xlsx`.
2. `hotelops intake` dei file mancanti appena ridroppati (maggio, giugno).
3. **Aprile e maggio (sostituzione decisa):** per ciascun mese `DELETE FROM f_bilancino WHERE societa_id='ORTI' AND mese='<M>'` (attese: 157 righe per 2026-04, 165 per 2026-05 — contarle prima) → promote del re-export (attese ~154 e 160 righe nuove). Il vecchio dato resta ricostruibile dal raw GCS.
4. **Giugno:** promote diretto (0 righe esistenti, nessuna DELETE).

### 1c. Verifica (output-based)

- FK coverage 100% sulle righe nuove (`raw_object_id IS NOT NULL`).
- Row count: ORTI 2026-04 ≈ 154, 2026-05 = 160, 2026-06 = 168; saldo cumulato = −241.772,91 per tutti.
- Stato lineage: tutti e tre i raw object PROMOTED.
- Sanity consumer: `v_ce_mensile_bilancino` giugno ORTI produce delta mensili plausibili (ricavi giugno > maggio, stagione).

## Parte 2 — Artifact "Bilancini · Gruppo Panorama"

### Approccio

Artifact statico self-contained con dati embedded (JSON inline), generato da uno script versionato nel repo, ripubblicato sullo stesso URL a ogni refresh mensile. Alternative scartate: pagina hub Streamlit (più lavoro + gate render reale — evoluzione futura se diventa strumento quotidiano); parse diretto dei soli xlsx locali (gen–apr esistono solo in BQ).

### Builder: `verticals/condges/build_bilancini_artifact.py`

Input:
- `f_bilancino` da BQ (ORTI + INTUR, tutti i mesi 2026; delta mensile calcolato per differenza YTD, stessa logica della vista).
- `Budget_ORTI_2026.xlsx` (fogli conto-level) → budget per `codice_conto × mese`.
- `Incidenza_costi_personale.xlsx` (foglio Costi Mensili per Division) → dettaglio personale.

Output: un file HTML in `docs/reports/artifacts/bilancini.html` (dati embedded, nessuna richiesta esterna), pubblicato con lo stesso path a ogni run → stesso URL.

I path dei due xlsx budget sono parametri CLI con default agli attuali percorsi Desktop; quando i budget entreranno in lineage si punterà a BQ.

### Sezioni

1. **A oggi (KPI YTD ORTI):** ricavi, costi, margine YTD vs budget YTD; scostamenti con segni in presentazione leggibili (ricavi sopra budget = verde "+", costi sopra budget = rosso "+") — mai numeri a segno-bilancio grezzi.
2. **Progressione (il peso di ogni mese):** delta mensile actual vs budget per categoria (Ricavi / Costi fissi / Variabili / Personale / Finanziari, le categorie del budget) — barre mensili + cumulata.
3. **Scostamenti (drill categoria → conto):** tabella budget vs consuntivo, mese × YTD, ordinata per |scostamento|; conti a consuntivo senza budget esposti in riga esplicita "Fuori budget" (mai nascosti); personale con drill per reparto dall'Incidenza.
4. **Navigatore bilancino (ORTI + INTUR):** selettore società+mese → albero SP+CE gerarchico (ricostruito dai prefissi conto), saldo YTD e delta mese per conto. Per INTUR nessun confronto budget; dati fermi all'ultimo mese caricato, dichiarato in pagina.

Freshness dichiarata in testa: "dati al <max mese per società>, generato il <data>".

### Semantica e trappole presidiate

- Il confronto budget usa il **delta mensile** del bilancino (non lo YTD) contro il budget mensile; YTD = somma.
- Segni: `saldo` bilancino ha ricavi negativi → in presentazione tutto positivo con direzione esplicita.
- Budget e consuntivo si confrontano solo dove la chiave conto matcha; nessuna media/fusione silenziosa.
- L'artifact è default-privato; contiene dati finanziari sensibili → resta privato salvo decisione esplicita di Stefano.

### Rituale mensile

Export bilancino da Rosa → `hotelops intake` + promote (parser ora copre i 3 layout) → `python -m verticals.condges.build_bilancini_artifact` → republish artifact (stesso URL).

## Test

- Unit sul parser: fixture sintetica del terzo layout (gerarchia 3 livelli, marker S/C/F/B, dare/avere) → leaf count, saldi, tipo/sezione attesi. In linea con i test esistenti del modulo.
- Builder: run reale + controllo che i totali YTD dell'artifact quadrino con `SELECT SUM(saldo)` da BQ per (società, mese).
- Render: verifica visiva dell'HTML con dati reali prima di consegnare il link (gate lettura, non solo numeri).

## Fuori scope (v1)

- Red flags automatiche (anomalie di business, YoY): dopo, quando i bilanci accumulati sono di più — "ci facciamo analisi sopra" in un'iterazione successiva.
- Budget INTUR, consolidato, bilancini 2025 (il re-export 2025 con CE è un HANDOFF già tracciato in STATUS).
- Pagina hub Streamlit.
