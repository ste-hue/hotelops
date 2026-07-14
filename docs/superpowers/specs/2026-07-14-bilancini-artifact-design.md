# Bilancini — artifact consultabile + terzo layout parser

**Data:** 2026-07-14 · **Stato:** design approvato a voce, in review scritta
**Decisioni prese con Stefano:** niente vertical nuovo (condges resta il dominio); deliverable = artifact Claude statico "tipo i mutui"; i re-export sostituiscono il caricato (principio deciso su maggio ORTI, esteso a re-baseline completo 2026 quando Stefano ha ri-esportato l'intera serie); scope ORTI+INTUR (INTUR solo navigatore, senza budget).

## La domanda della pagina

> **"Come sta andando il bilancio a oggi, e come ci siamo arrivati?"**

Ogni elemento dell'artifact si giustifica contro questa domanda (regola "una pagina, una domanda"). Le sotto-letture — a oggi, progressione, peso del mese, scostamento vs budget, red flags — sono sezioni, non pagine separate.

## Contesto

- `f_bilancino` è il backbone COMPETENZA del CdG (decisione 2026-06-22); `v_ce_mensile_bilancino` ricava il mese per differenza YTD.
- Copertura attuale in BQ: ORTI e INTUR fino a 2026-05, da export in formati misti (griglia/legacy). Il 2026-07-14 Stefano ha ri-esportato **l'intera serie 2026**: cartella `bilancinimensili/{ORTI,INTUR}/01..06`, 12 file, tutti nel **terzo layout** (varianti 5 e 11 colonne — le 11 aggiungono Progressivi annui/periodici → risoluzione colonne per nome header, obbligatoria).
- I re-export contengono rettifiche sui mesi già caricati (maggio ORTI: es. `47.91.07.02` Ricavi bar 52.747,38 vs 52.780,11 in BQ; aprile ORTI: 22 conti diversi, tra cui banca `19.01.01` −6,7k e fornitori `33.03.01` −6,9k). Il dedup per hash le salterebbe in silenzio → **re-baseline completo 2026**, non merge.
- Quadratura verificata su tutti e 12: sbilancio dare−avere costante = −241.772,91 (ORTI, perdita a nuovo) / +625.546,25 (INTUR, utile a nuovo); foglie crescenti mese su mese (semantica YTD corretta).
- Tutti e 12 già in GCS (intake 2026-07-14, stato CLASSIFIED, nomi canonici `esolver_bilancino_<SOC>_2026-<MM>.xlsx`). Un raw object precedente di aprile ORTI (`0fe78f07…`, dal primo drop Desktop) resta CLASSIFIED non promosso: superseded da questa serie. Lezione pagata: maggio/giugno del primo drop sono spariti dal Desktop prima dell'intake → **intake al primo drop, sempre**.
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

**Attesi dry-run per file (foglie a saldo ≠ 0):**
ORTI 01→112, 02→123, 03→136, 04→154, 05→160, 06→168 · INTUR 01→112, 02→116, 03→122, 04→127, 05→133, 06→138. Sbilancio costante per società (−241.772,91 / +625.546,25).

### 1b. Ingest — re-baseline 2026

Intake già fatto (2026-07-14). Raw object id:
- INTUR 01 `906c3c28` · 02 `549064ef` · 03 `6a27a0aa` · 04 `f7eecf71` · 05 `5cc62144` · 06 `d5fffe55`
- ORTI 01 `2ebeb2e4` · 02 `b4b8e8d3` · 03 `5f13fa74` · 04 `a7e27a36` · 05 `d1952f6a` · 06 `4c2d15bf`

Con parser esteso:
1. **DELETE scoped**: `DELETE FROM f_bilancino WHERE mese LIKE '2026-%'` per entrambe le società (attese cancellate, contarle prima: ORTI 112+124+136+157+165 = 694; INTUR 72+101+115+116+123 = 527). I mesi 2025 NON si toccano. Il vecchio dato resta ricostruibile dai raw GCS.
2. **Promote dei 12** in ordine mese (gennaio→giugno) per società.
3. Vantaggio collaterale: provenienza uniforme (stesso layout, stesso giorno di export, FK fresca) su tutto il 2026.

### 1c. Verifica (output-based)

- FK coverage 100% sulle righe 2026 (`raw_object_id IS NOT NULL`).
- Row count per (società, mese) = attesi di §1a; saldo cumulato costante per società su ogni mese.
- Stato lineage: tutti e 12 i raw object PROMOTED.
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

### ⚠️ Amendment 2026-07-14 (decisione Stefano, post-implementazione Task 4)

**V1 = solo numeri veri.** I bilancini sono FATTI; il budget/PF sono STIME (cashflow: tutto stimato tranne i saldi banca iniziali). Mischiarli in pagina confonde la lettura — evidenza concreta: il budget Personale è un rollup a 1 conto mentre il bilancino ha i conti Esolver granulari → 849k € di actuals finivano in "Fuori budget". Quindi:
- L'artifact v1 NON contiene budget/scostamenti: sezioni ridotte a **A oggi / Progressione / Navigatore** (la progressione usa i macro-gruppi top-level del CE reale: 47 Ricavi, 55 Acquisti, 57 Servizi, …).
- Il builder perde gli input xlsx budget (`--budget-xlsx`/`--incidenza-xlsx` rimossi): legge SOLO `f_bilancino`.
- Confronto vs stime = iterazione futura, in sezione separata etichettata "STIME", con Personale confrontato a livello categoria. Le sezioni sotto restano come riferimento per quella iterazione.

### Sezioni (v1 ridotta: 1, 2 senza budget, 4 — la 3 è deferita)

1. **A oggi (KPI YTD ORTI):** ricavi, costi, margine YTD vs budget YTD; scostamenti con segni in presentazione leggibili (ricavi sopra budget = verde "+", costi sopra budget = rosso "+") — mai numeri a segno-bilancio grezzi.
2. **Progressione (il peso di ogni mese):** delta mensile actual vs budget per categoria (Ricavi / Costi fissi / Variabili / Personale / Finanziari, le categorie del budget) — barre mensili + cumulata.
3. **Scostamenti (drill categoria → conto):** tabella budget vs consuntivo, mese × YTD, ordinata per |scostamento|; conti a consuntivo senza budget esposti in riga esplicita "Fuori budget" (mai nascosti); personale con drill per reparto dall'Incidenza.
4. **Navigatore bilancino (ORTI + INTUR):** selettore società+mese → albero SP+CE gerarchico (ricostruito dai prefissi conto), saldo YTD e delta mese per conto. Per INTUR nessun confronto budget; entrambe le società coperte gen–giu 2026, freshness dichiarata in pagina.

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
