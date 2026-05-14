---
subsystem: condges
code_paths:
  - verticals/condges/app_scadenzario.py
  - verticals/condges/scadenze_parse.py
  - core/bq/dimensioni/d_fornitori.csv
last_verified: 2026-05-13
source: tribal knowledge (Rosa) → first written 2026-05-13
---

# Procedura: Rollover Cashflow Mensile (Piano Finanziario Rosa)

Ogni mese si genera un nuovo file Piano Finanziario (PF Rosa) a partire da quello del mese precedente. Il file mostra:

- **Mese corrente** (colonna 3 dello sheet master "Piano Finanziario"): primo mese previsionale. La sua riga 4 `SALDO MESE PRECED` = somma saldi banca a fine mese precedente (consuntivo).
- **Mesi N+1 → N+8** (colonne 4-11): proiezione forward di entrate e uscite.
- **Sheet dettaglio per voce USCITE** (es. `Materie Prime-Consumo `, `Utenze`, …): righe per singolo fornitore con importi per mese.

Il rollover N → N+1 sostituisce la colonna N con la N+1 come nuovo "mese corrente", aggiorna i saldi banca al consuntivo di fine N, e ridistribuisce i debiti residui fornitori secondo il nuovo scadenzario Esolver.

---

## Quando

Una volta al mese, tipicamente tra il 5 e il 10 del mese N+1, **dopo** che:

- I movimenti bancari di N sono caricati in Esolver (per leggere i saldi a fine N)
- Esolver è aggiornato con le fatture passive di N (per l'export scadenzario riflette lo stato corretto)

---

## Prerequisiti

| Input | Origine | Esempio |
|---|---|---|
| PF mese N | Drive `1wGf0yL7RGrvumCKSVWFBlxC2zcAYT8u` (cartella Rosa) — scaricato in locale | `~/Downloads/ORTI Piano Finanziario 2026.xlsx` (versione aprile) |
| Saldi banca a fine N | Estratti conto / Esolver scheda contabile | MPS, Intesa (ORTI); MPS, Intesa, Sella, BCP (INTUR) |
| Scadenzario partite sintetica | Esolver export "Situazione partite sintetica per fornitori" | `~/Desktop/WORK/condges/pianfin/scadenziarioall<giorno>maggio.xlsx` |

---

## Passi

### 1. Skeleton mese N+1 — **manuale** (sarà automatizzato in fase 2)

Aprire il PF di N e:

1. **Sheet master "Piano Finanziario"**:
   - Shiftare i mesi a sinistra: colonna 3 diventa N+1, colonna 11 diventa N+9.
   - Azzerare/sovrascrivere riga 31 con la data di fine mese N (es. `30/04/2026`).
   - Aggiornare righe 32+ (Saldo MPS, Saldo Intesa, …) con i saldi consuntivo di fine N.
   - Aggiornare riga 4 (SALDO MESE PRECED) colonna 3 = somma nuovi saldi banca.
2. **Sheet dettaglio per ciascuna voce USCITE** (`Materie Prime-Consumo `, `Utenze`, `Salari e Stipendi`, `Tasse e Imposte`, `Commisisoni Portali`, `Mutui e Finaziamenti`, `Consulenze`, `Godimento Beni di Terzi`, ` Varie ed Eventuali`, `Canoni e servizi`):
   - Shiftare le colonne mese (col 4..12) di un mese.
   - Azzerare le celle del vecchio mese N nelle righe fornitori (lasciando intatte riga 3 PREVISIONALE e riga 4 totale voce).

**Razionale del cancellamento**: tutto ciò che era previsto per il mese N ora è materializzato nei saldi banca aggiornati. Lasciarlo in cella creerebbe double counting.

### 2. Scrittura fornitori — **automatizzata** (Streamlit)

```bash
streamlit run verticals/condges/app_scadenzario.py
```

Nell'app:

1. Upload **Piano Finanziario** (file post-step 1)
2. Upload **Situazione fornitori** (scadenzario Esolver di N+1)
3. Review:
   - Mappati: fornitori con `voce_id` in `d_fornitori.csv`
   - Non mappati: fornitori senza voce — assegnare manualmente nell'UI (persiste in session)
   - Escludere fornitori specifici con checkbox se necessario
4. Click **"Aggiorna PF Excel"** → download

Cosa scrive l'app (`app_scadenzario.write_pf`):

- Per ogni fornitore mappato: cerca la riga nel foglio dettaglio della sua voce (match per codice colonna 1, fallback per nome fuzzy colonna 2)
- Scrive `scaduto` → colonna del mese corrente (= mese N+1 per `date.today().month`)
- Scrive importi `mese_K` → colonna del mese K
- Sign flip (scadenzario negativo → PF positivo)
- Aggiusta riga `PREVISIONALE` se è dentro il range del SUM totale, riducendola di `supplier_total` per evitare double counting (SUM = MAX(orig_prev, supplier_total))

### 3. Voci non-fornitori — **manuale**

L'app aggiorna solo le 10 voci USCITE legate a fornitori. Le restanti restano da aggiornare a mano nel master "Piano Finanziario":

- **ENTRATE**: Entrate Hotel, Residence, CVM, Supermercato, Rientro Sospesi, Caparre Intur (forecast manuale)
- **USCITE non-fornitore**: Mutui e Finaziamenti, Salari e Stipendi, Tasse e Imposte (forecast manuale, anche se hanno fogli dettaglio)
- Eventuali altre celle sul master Piano Finanziario

---

## Verifica

Check operativo prima di passare il file a Rosa:

1. **Eyeball 3-5 fornitori chiave** (es. Le Croissant, Ausino, fitto INTUR): aprire il foglio dettaglio della loro voce e confermare che le celle del mese N+1 corrispondono ai valori attesi dallo scadenzario.
2. **Sanity check sui totali**: riga 27 (TOTALE USCITE) del master deve aggiornarsi automaticamente via formula SUM dai fogli dettaglio; controllare che il valore N+1 sia plausibile vs N.
3. **Coerenza saldi banca**: riga 35 (TOTALE BANCHE) del master deve essere = somma saldi MPS+Intesa+altre. Riga 4 (SALDO MESE PRECED) colonna N+1 deve essere uguale.
4. **Riga 29 Cash Flow** colonna N+1 = TOTALE ENTRATE − TOTALE USCITE.

Approval finale: passare il file a Rosa, attendere conferma o segnalazione anomalie.

---

## Limitazioni note (TODO)

- **Step 1 (skeleton) è manuale** → in fase 2 l'app farà shift colonne + cancellamento mese N + scrittura saldi banca.
- **Step 3 (non-fornitori) resta manuale** → non in scope per questa patch.
- **Match fornitori per nome è fuzzy** (containment ≥4 char in entrambe le direzioni) — può causare falsi positivi rari. Match per codice fornitore è preferito quando disponibile.
- **Sheet name typos** (`Commisisoni Portali`, `Mutui e Finaziamenti`, ` Varie ed Eventuali`) sono hardcoded in `app_scadenzario.VOCE_TO_SHEET_CANDIDATES`. Se Rosa cambia template, aggiornare la mappa.
- **Voce assignments per fornitori non mappati** vivono in `st.session_state` e si perdono al refresh. Se ricorrenti, aggiungerli a `core/bq/dimensioni/d_fornitori.csv` come fix permanente.
- **Library `verticals/condges/scadenzario_excel.py`** contiene un workflow alternativo (`parse_sintetica_scadenze` + `cascade_scaduto` + `write_back_to_pf`) per il formato "Situazione sintetica scadenze" (aggregato per fornitore). Non collegato alla CLI attiva. Dead code candidato a rimozione.
