# 2026-05-20 — `pf-rotate` design (rotation mensile del Piano Finanziario)

**Date:** 2026-05-20
**Status:** Draft v1
**Author:** Stefano + Claude
**Reference decisions:** [[2026-05-18_PF_Rotate_Design]] · [[2026-05-18_Cashflow_Modulo_Autonomo]]
**Reference concepts:** [[PF_ROTATION_WORKFLOW]] · [[PF_VOCE_FONTE]] · [[LE_3_DIMENSIONI]]

---

## 0. TL;DR

`hotelops pf-rotate` — comando per la rotation mensile del Piano Finanziario di Rosa
(lente CASSA), uguale motore per **ORTI** e **INTUR**, esposto come **CLI** e come
estensione dell'app esistente `verticals/condges/app_scadenzario.py`.

Tre step su **griglia fissa** (le colonne mese non si rinominano):

1. **Roll saldi banca** — letti da `f_saldi_banca_chiusura_mensile`, suggeriti, confermabili.
2. **Azzera mese chiuso** — solo celle-valore, formule mai toccate.
3. **Scadenzario write-back** — match per `codice_fornitore`; fornitori nuovi mappati
   interattivamente, **mai saltati**, persistiti in `d_fornitori.csv`.

Più due servitù:

- **Step 0 (prerequisito)** — normalizzazione del template INTUR (oggi sporco) sul
  layout-target ORTI: aggiungere colonna `CODICE` in col A dei fogli dettaglio. Una tantum.
- **Step 5 (verifica)** — ricalcolo dei 22 controlli del foglio `Controlli` in Python
  (sui valori delle celle), niente dipendenza da Excel desktop.

File output **nuovo**: l'input non viene mai mutato. La nuova superficie convive con
`tesoreria.py` (legge PF + genera Excel pulito derivato — uso diverso).

---

## 1. Contesto

Rosa esegue ogni mese a mano la rotation del PF per ORTI e INTUR. Il processo è fragile:

- I template ORTI e INTUR sono divergenti — ORTI ha colonna codice fornitore nei fogli
  dettaglio, INTUR no.
- INTUR ha le formule cross-sheet riscritte a mano ogni mese — fonte tipica di errori.
- Lo step "azzera mese chiuso" è il pezzo che evita il doppio conteggio; oggi è memoria
  manuale di Rosa, non meccanico.

Dal witness del 2026-05-19 ([[2026-05-19_rotation_maggio_witness_e_mappa_voci]]):

- ORTI rotation maggio completata (3 step, 72/73 fornitori, persistiti 23 nuovi in
  `d_fornitori.csv`).
- INTUR rotation maggio: step 1+2 puliti; **step 3 grezzo** — i fogli dettaglio non hanno
  colonna codice → solo append, niente update, rischio doppio conteggio.

Lo stato attuale dell'automation:

- **Step 3** (scrittura scadenzario) — coperto da `app_scadenzario.py::write_pf()` (live su
  Streamlit Cloud). **Regressione nota:** salta i fornitori non mappati in silenzio.
  Da fixare in questo spec.
- **Step 1+2** — solo script ad-hoc, non integrati.
- **Step 5** — assente.
- **Una CLI** per il flusso completo — assente.

### 1.1 Cosa è già nel repo (riuso)

| Pezzo | Dove | Stato |
|---|---|---|
| `write_pf()` (step 3) | `verticals/condges/app_scadenzario.py` | live, da estendere (fix regressione + interactive) |
| `parse_scadenze` (3 formati Esolver) | `verticals/condges/scadenze_parse.py`, `scadenzario_excel.py` | riuso as-is |
| Mappa fornitori centralizzata | `core/bq/dimensioni/d_fornitori.csv` | aggiungere colonna `societa_id` |
| Streamlit app surface | `verticals/condges/app_scadenzario.py` | estendere con "Chiudi mese precedente" |
| Saldi banca month-end ground truth | `f_saldi_banca_chiusura_mensile` (BQ) + omonimo CSV | scrittura già fatta per ORTI/INTUR Mar/Apr |

---

## 2. Goal / Non-goals

### Goal v1

- `hotelops pf-rotate --pf <file> --scad <file>` esegue il ciclo completo (step 0
  applicabile a INTUR una tantum poi tolto dal flusso runtime; step 1+2+3+5).
- Stessa logica esposta nella UI estesa di `app_scadenzario.py`.
- ORTI e INTUR sullo stesso motore.
- File output nuovo, input mai mutato.
- Persistenza `d_fornitori.csv` (mappature fornitori nuovi) con `societa_id`.
- Test: tre invarianti meccaniche del flusso (azzera-valori-mai-formule,
  saldo-iniziale-mese-nuovo, no-skip-unmapped).

### Non-goals v1

- **Voce → fonte per non-fornitori** (tasse, salari, mutui, entrate) — già il concept
  `PF_VOCE_FONTE.md` esiste; sarà un secondo spec. Per v1 lo step 3 copre solo i
  fornitori; mutui/tasse/salari/entrate restano scrittura manuale di Rosa nel file
  (come oggi).
- **Estrazione del modulo CASHFLOW da `verticals/condges/`** in un package dedicato —
  la decision `Cashflow_Modulo_Autonomo` lo segna esplicitamente come *separato, non
  urgente*. v1 vive sotto `verticals/condges/` come oggi.
- **Fusione di `tesoreria.py` + `app_scadenzario.py`** — restano due app distinte
  con use case diversi (tesoreria = lettura+vista+export pulito; pf-rotate = roll+write
  in place-style). Una eventuale fusione è scope a parte.
- **Materializzazione di un PF generato da BQ** (`genera_excel.py`) — non c'entra con
  questo flusso; restano percorsi indipendenti.
- **API HotelCube, Power BI revman, budget manuale** — fuori scope.

---

## 3. Architettura

### 3.1 Excel-as-truth per il forecast, BQ-as-fact per le ancore

Vincolo architetturale derivato da [[PF_ROTATION_WORKFLOW]] e
[[2026-05-18_PF_Rotate_Design]]:

> Il PF contiene **solo futuro**. Entrate proiettate, tasse, salari sono giudizio
> manuale che vive **solo nel file**. BQ registra il passato (consuntivo) e non può
> essere fonte del contenuto previsionale del PF. BQ fornisce solo i due *fatti* che
> ancorano la previsione:
> - **saldi banca a fine mese** → `f_saldi_banca_chiusura_mensile` → step 1.
> - **partite aperte fornitori** (scadenzario) → file Esolver → step 3.

Conseguenza pratica: la rotation **non rigenera** il file da un modello — **rolla** il
file del mese precedente. La memoria delle previsioni manuali vive nelle celle.

### 3.2 Griglia fissa, non shifting-window

Le colonne mese restano nominalmente fisse (es. `D=APRILE … L=DICEMBRE`).
Quando un mese si chiude la sua colonna viene **azzerata nei valori** (entrate hardcoded,
detail-sheet cells), **non rinominata, non cancellata fisicamente**. La cascata di r4
(`=C37` → eredita il saldo del mese precedente) propaga automaticamente il saldo
aggiornato al mese di apertura.

### 3.3 File output nuovo, mai mutare l'input

Il file di input (es. `04_ORTIFinancialPlan2026.xlsx`) non viene mai mutato. Output:
nuovo file con naming convention (vedi §9). Stesso principio per la versione INTUR
post-normalizzazione (§4).

### 3.4 Modulo CASHFLOW

Il codice nuovo vive (per ora) sotto `verticals/condges/` — la decision
`Cashflow_Modulo_Autonomo` riconosce CASHFLOW come modulo semanticamente autonomo ma
flagga il riposizionamento di codice come *separato, non urgente*. v1 evita lo
spostamento; usa solo nomenclatura coerente (commenti, docstrings) e raggruppa i nuovi
moduli sotto un sotto-package `verticals/condges/pf_rotate/`.

---

## 4. Step 0 — Normalizzazione template INTUR (prerequisito una tantum)

### 4.1 Stato attuale INTUR

I fogli dettaglio INTUR (`Salari e Stipendi`, `Utenze`, `Materie Prime-Conumo `,
`Tasse e Imposte`, `Mutui e Finaziamenti`, `Consulenze`, `Godimento Beni di Terzi`,
`Canoni e servizi`, ` Varie ed Eventuali`) hanno la **colonna A** con un misto di:

- codici fornitore (es. `73`, `92`, `1592`, `777`),
- testo `RID` (Rapporto Interbancario Diretto, fornitori con domiciliazione),
- importi-debito laterali (es. `14400` in Godimento Beni = "2024 Arretrati",
  `19200` = "2025 Arretrati", `68696` = "ARRETRATO IMPOSTE", `1273.38` su
  "CoIrEs SRL"), che sono **annotazioni storiche, non valori di cashflow** — il
  cashflow vive nelle colonne mese D-L.

Decisione (Stefano, 2026-05-20): **gli importi in col A sono sovrascrivibili.** Il
debito (es. Panorama Company 412k del foglio `Nota`) resta nello scadenzario / fuori dal
cashflow del PF.

### 4.2 Layout-target (= ORTI `Utenze` osservato)

```
r1:   ""   ""   ""   2026   ""   ""   ...
r2:   CODICE   ""   ""   APRILE  MAGGIO  GIUGNO  …  DICEMBRE
r3:   ""   <NomeFoglio>   =SUM(D3:L3)   =SUM(D4:D134)   =SUM(E4:E134)   …   (totale di colonna)
r4-N: <codice>   <nome>   =SUM(D_:L_)   <val>   <val>   …   <val>     (righe fornitore)
```

Alcuni fogli (es. `Godimento Beni di Terzi`, `Canoni e servizi`) hanno il totale in
**r4** invece che **r3** — pattern legittimo, da preservare per foglio (vedi §5.4 il
riferimento dal master).

### 4.3 Algoritmo di normalizzazione (`pf-normalize-intur`)

Comando una tantum (subcommand opzionale: `hotelops pf-rotate normalize-intur
--pf <file>` o utility a sé):

1. Backup l'input in `<input>.pre-normalize.xlsx` (paranoia).
2. Per ogni foglio dettaglio:
   a. Leggi i fornitori (col B) e abbinali a `d_fornitori.csv WHERE societa_id='INTUR'`
      con la stessa logica di `app_scadenzario._find_supplier_row_by_name` (exact poi
      containment ≥4 char).
   b. Sostituisci `col A` con il `codice_fornitore` quando trovato.
   c. Per i fornitori non in `d_fornitori`: lasciali in col A vuoti, **registra** nel
      report di output (Excel `INTUR_fornitori_da_mappare.xlsx` con codice/nome/voce
      proposta — flusso di consolidamento manuale con Rosa).
   d. **Log di overwrite col A** — per ogni cella col A sostituita, registrare riga in
      un report `INTUR_col_a_overwrites.xlsx` con: `foglio, riga, vecchio_valore,
      nuovo_codice, nome_fornitore_b`. Nessun overwrite silenzioso, anche per importi
      flaggati come "non-cashflow".
   d. Aggiungi/normalizza le formule riga totale (r3 o r4) se mancano.
   e. Assicura `CODICE` in r2 col A.
3. Output: nuovo file `<input>.normalized.xlsx` + report fornitori non mappati.
4. Verifica con §5.4 sul file output.

### 4.4 Risultato atteso

INTUR dopo normalize ha la stessa anatomia ORTI → motore unico `pf-rotate` lavora su
entrambi senza branch-per-società.

---

## 5. Rotation — i 3 step + verifica (Step 5)

### 5.1 Step 1 — Roll saldi banca

**Input:** data della rotation (default = ultimo giorno del mese precedente),
`societa` (ORTI o INTUR).

**Azione:**

1. Query a `f_saldi_banca_chiusura_mensile` per la coppia (societa, data_saldo) →
   ottieni `{banca → saldo}` suggeriti.
2. Mostra a utente (CLI: stampa + prompt y/n per ciascun saldo; app: 2-3 numeric
   input precompilati). Confermabili o sovrascrivibili.
3. Scrivi:
   - `Piano Finanziario` foglio, **colonna del mese in chiusura** (es. APRILE = col C
     osservato sul file ORTI 2026-05-19): `<col>31` = data (formato `gg/mm/aaaa`),
     `<col>32`, `<col>33` (e `<col>34` se presente) = saldi singoli. (`<col>35` =
     `=SUM(<col>32:<col>34)` resta intatto come formula.) Le posizioni dei saldi
     sono nella colonna del mese in chiusura, **non** in una colonna fissa — questo
     riflette il principio "griglia fissa, file è la memoria": ogni rotation scrive
     in una nuova colonna, le precedenti restano come snapshot storico.
   - `<col>4` (saldo iniziale del mese in chiusura): **sovrascritto** al totale
     banche del cutover, hardcoded (no formula). Convenzione del template, verificata
     in due posti: il Controllo #1 (`Piano Finanziario.C4` NON formula) e il witness
     del 2026-05-19 (C4 = 339.337,46 = saldo 30/04 = SUM(C32:C34)). **Conseguenza
     by-design** (cf. [[PF_ROTATION_WORKFLOW]]): il saldo iniziale *storico* del mese
     chiuso (es. saldo 31/03 quando si chiude APRILE) viene perso — la cella `<col>4`
     ospita solo l'àncora del cutover, non il saldo storico di apertura. Le colonne
     successive `D4..K4` restano formule cascata (`=<col_prev>37`).

**Vincoli:**

- Se la query BQ è vuota, prompt manuale obbligatorio.
- Se `<col>32`, `<col>33` (o `<col>34`) hanno una formula con riferimenti ad altre
  celle → ERRORE (input atteso = valore hardcoded; una formula con sole costanti
  tipo `=251897.54` è ammessa, conta come valore).
- Etichetta banca (col A r32+) determina quale saldo va in quale riga — match per nome
  banca normalizzato (case-insensitive, `_` → spazio, sottoinsieme di parole).
- La colonna del mese in chiusura è determinata dall'header r2 (nome mese ITA).

### 5.2 Step 2 — Azzera mese chiuso

**Input:** `mese_chiuso` (es. 4 = APRILE).

**Vincolo durissimo:** azzera **solo le celle-valore**, mai le formule. "Cella-valore"
= numero, stringa, o formula con sole costanti (es. `=110000+160000` — osservato nel
master ORTI riga 6 SETTEMBRE — conta come valore aggregabile). "Cella-formula" =
qualsiasi cosa contiene riferimenti `A1`-style (es. `=Utenze!D3`, `=SUM(...)`, `=C37`).

**Azione sul master `Piano Finanziario`:**

- Trova la colonna del mese chiuso (header r2).
- Azzera celle **valore** di:
  - r6-r11 (entrate hardcoded) → `None`
  - r24 (`Deposito Fitto`, se hardcoded)
  - r31-r34 saldi (in realtà aggiornati allo step 1, no-op qui)
- **Non** toccare: r4 (può essere hardcoded sul primo mese, formula `=C37` sui
  successivi — usare `ISFORMULA`-equivalent in openpyxl per discriminare); r12
  (SUM), r14-r23 (formule link), r27 (SUM), r29 (formula), r37 (formula), r45
  (formula), r43 (SUM).

**Azione sui fogli dettaglio:**

- Trova la colonna del mese chiuso (header r2).
- Azzera celle **valore** dalle righe 5 in giù (oltre la riga totale r3/r4) →
  imposta `None` se la cella è un numero hardcoded, lascia intatto se è formula
  (es. `=SUM(D_:L_)` in col C).
- La riga PREVISIONALE (quando esiste) ha celle valore: anch'esse → `None`.

**Effetto:** il TOTALE ENTRATE/USCITE/Cash Flow del mese chiuso → 0; il saldo del mese
chiuso (r37) = saldo iniziale = saldo banca reale aggiornato dallo step 1; la cascata
r4 del mese di apertura eredita il saldo aggiornato.

### 5.3 Step 3 — Scadenzario write-back

Riusa `app_scadenzario.write_pf()` con **due fix obbligatori** rispetto a oggi:

#### Fix 1 — Mai saltare in silenzio i fornitori non mappati

Oggi `write_pf()` salta i fornitori non in `d_fornitori`. Il design dice
*conta / classifica / escludi + memorizza, mai saltare*.

Nuovo contratto:

- Costruisci `unmapped = [forn ∈ scadenzario WHERE codice ∉ d_fornitori[societa]]`.
- **Policy esplicita** governata da flag `--unmapped-policy` (CLI) o radio (app):
  - `fail` (**default**) — se `unmapped ≠ ∅`, esci con errore. Default per non-TTY (test, CI).
  - `report` — esporta `unmapped` in Excel + esci. Mai scrivere il PF di output.
  - `interactive` — prompt CLI / sezione bloccante UI (vedi sotto). Default solo
    se `isatty()` (CLI lanciato da terminale interattivo).
  - `skip` — salta gli unmapped (modalità legacy compat con `write_pf` attuale,
    **sconsigliato**, ma disponibile per smoke testing).
- **Modalità interactive (CLI):** stampa la tabella (codice / nome / totale debito);
  per ciascuno chiedi:
  - `[v]oce voceID` → mappa subito a quella voce (persisti).
  - `[s]kip` → escludi solo per questa run (non persistito).
  - `[e]xclude` → persisti con `is_excluded=True, exclude_reason=<input>` — utile per
    fornitori intercompany / capex tipo CamerePrimoPiano.
- **Modalità interactive (app):** sezione "Fornitori non mappati" già esistente in
  `app_scadenzario.py` resa **bloccante** — bottone "Aggiorna PF" disabilitato finché
  tutti gli unmapped hanno una scelta esplicita (voce / skip / exclude).
- Tutte le scelte `voce` e `exclude` → append a `d_fornitori.csv` con `societa_id`,
  `is_excluded`, `exclude_reason`.

#### Fix 2 — Filtro per `societa_id` in d_fornitori

Aggiungere colonna `societa_id` a `d_fornitori.csv` (oggi assente). Il loader filtra
per la società del PF in input. ORTI esistenti → bulk-set `societa_id='ORTI'` come
baseline; INTUR si popola via lo Step 0 + rotation.

Tutto il resto di `write_pf` (sheet typo-tolerant, PREVISIONALE adjustment, no
`insert_rows`, empty-row search nel SUM range) **resta as-is** — è già robusto.

### 5.4 Step 5 — Verifica 22 controlli (in Python)

**Niente dipendenza da Excel desktop, niente dipendenza da `data_only=True`.**
`openpyxl` con `data_only=True` legge solo i *cached* values prodotti dall'ultima
apertura in Excel; dopo che Python modifica/salva il file, la cache è stale o nulla
per le celle-formula. Quindi: **reimplementare i 22 check come funzioni pure Python
sui valori sorgente**. Per ogni check:

- Le celle sorgente referenziate dalle formule del foglio `Controlli` (es. `C12 =
  SUM(C6:C11)`) vengono lette via `data_only=False` (file appena scritto). I valori
  hardcoded sono numeri diretti. Le formule sorgente vengono *valutate* solo se
  semplici e deterministiche (es. `=110000+160000` → 270000), altrimenti il check
  che dipende da quella cella va in `INDETERMINATE` (warning, non error).
- Il controllo confronta i due lati dell'uguaglianza ricavandoli entrambi dai valori
  sorgente nel workbook attuale. Esempio: il check "C12 = SUM(C6:C11)" diventa
  `read_value(ws, 'C12') == sum(read_value(ws, f'C{r}') for r in range(6, 12))`.

**I 22 controlli** (dal foglio `Controlli` ORTI letto il 2026-05-20):

| # | Sezione | Check | Predicato Python |
|---|---|---|---|
| 1 | Saldo Partenza | C4 hardcoded (non formula) | `not is_formula(pf!C4)` |
| 2 | Saldo Partenza | D4 = C37 | `pf!D4 == pf!C37` |
| 3 | Saldo Partenza | catena D4:K4 = mese_prec!37 | `all(pf!Xi+1 == pf!Xi+0 row37 for i in cols)` |
| 4 | Saldo Partenza | mesi passati rimossi | static OK (post step 2) |
| 5 | Totale Entrate | C12:K12 = SUM(C6:C11 …) | per mese |
| 6 | Totale Uscite | C27:K27 = SUM(C14:C26 …) | per mese |
| 7 | Cash Flow | C29:K29 = riga12 - riga27 | per mese |
| 8-17 | Riferimenti Uscite | r14-r23 = `detail!D3` (o D4) | per voce |
| 18 | Saldo Proiettato | r37 = r4 + r29 | per mese |
| 19 | Cash Flow con Affidamenti | r45 = r37 + r43 | per mese |
| 20 | Colonna Totali | L12 = SUM(C12:K12) | |
| 21 | Colonna Totali | L27 = SUM(C27:K27) | |
| 22 | Colonna Totali | L29 = L12 - L27 | |

Output: lista di tuple `(check_id, esito, dettaglio)` + summary `n_ok / n_err / n_indet`.

**Comportamento su fallimento (NON blocca la scrittura):** se `n_err > 0`, il file
output viene scritto con suffisso `_FAILED_CHECKS` invece del naming canonico (es.
`ORTI_PF_2026-05_post-rotate_2026-05-20T14-30_FAILED_CHECKS.xlsx`). Stampa il diff
dei check falliti, exit 1. Avere il file output disponibile è essenziale per il
debug visivo in Excel — bloccare la scrittura cieca rende il debug masochistico.

---

## 6. Due superfici

### 6.1 CLI — `hotelops pf-rotate`

```bash
hotelops pf-rotate \
  --pf  /path/to/05_ORTIFinancialPlan2026.xlsx \
  --scad /path/to/situazione_scadenze.xlsx \
  --scad-tipo sintetica          # o riepilogo / partite (cfr. scadenze_parse)
  --mese-chiuso aprile           # o numero 4
  --data-saldo 2026-04-30        # default = ultimo del mese chiuso
  --out /path/to/out.xlsx        # default = naming convention §9
  --dry-run                       # esegui tutto fino a Step 5 senza scrivere file output
```

Flag opzionali:

- `--banca <BANCA>=<importo>` (ripetibile) — sovrascrive il suggerimento BQ per uno
  specifico conto.
- `--auto-confirm-saldi` — non chiedere conferma per ciascun saldo (CI / batch).
- `--unmapped-policy {fail,report,interactive,skip}` — vedi §5.3 Fix 1. Default
  `fail` quando stdin non è TTY, `interactive` se lo è.
- `--unmapped-report /path/to/report.xlsx` — destinazione dell'export `report`
  (default: accanto al PF output).

Sub-comando opzionale (Step 0):

```bash
hotelops pf-rotate normalize-intur --pf /path/to/05_INTUR_Piano_Finanziario.xlsx
```

### 6.2 App — estensione di `app_scadenzario.py`

Aggiunte alla UI esistente:

- **Sezione "Chiudi mese precedente"** (sopra l'uploader scadenzario):
  - Selectbox `mese_chiuso` (default = mese precedente al corrente).
  - Date picker `data_saldo` (default = ultimo giorno del mese chiuso).
  - 2-3 numeric input per saldi banca, precompilati dalla query
    `f_saldi_banca_chiusura_mensile`. Checkbox "Conferma e procedi al roll" per
    eseguire step 1+2.
- **Sezione fornitori non mappati** già esistente → resa **bloccante** (bottone
  "Aggiorna PF" disabilitato finché tutti hanno una scelta esplicita); persistenza
  delle scelte in `d_fornitori.csv` al click.
- **Sezione "Controlli"** (sotto l'azione): visualizza l'output di Step 5 — green
  badge per ogni check passato, red per ciascun fail con dettaglio.
- Bottone download del file output usa la naming convention §9.

L'app esistente `tesoreria.py` **non viene toccata**.

---

## 7. Contratti dati

### 7.1 Input

| Input | Formato | Validazione |
|---|---|---|
| PF Excel | `.xlsx` con foglio `Piano Finanziario` + fogli dettaglio canonici | Step 5 enforced |
| Scadenzario Esolver | `.xlsx`, 3 formati (riepilogo / partite / sintetica) | `parse_scadenze` |
| `f_saldi_banca_chiusura_mensile` | BQ table | filtro `societa_id`, `data_saldo` |
| `d_fornitori.csv` | CSV, **nuova colonna `societa_id`** richiesta | filtro per società |

### 7.2 Output

| Output | Path | Contenuto |
|---|---|---|
| PF aggiornato | vedi §9 | Excel ruotato |
| Report fornitori unmapped (se non interattivo) | accanto al PF output | Excel: codice/nome/totale/voce_proposta |
| `d_fornitori.csv` aggiornato | `core/bq/dimensioni/d_fornitori.csv` | append delle nuove mappature |
| Controlli log | stdout (CLI) / sezione app (UI) | 22 check + summary |

---

## 8. Persistence — `d_fornitori.csv` con `societa_id`

### 8.1 Schema nuovo

```
codice_fornitore,nome_esolver,nome_pf,voce_id,is_intercompany,is_excluded,exclude_reason,societa_id
```

Razionale (vedi anche §10 I3): `voce_id` resta semantico (= voce PF reale).
`is_excluded` + `exclude_reason` esprimono routing/exclusion *senza* sporcare il
codominio di `voce_id`. Un fornitore escluso (es. CamerePrimoPiano) ha
`is_excluded=True`, `exclude_reason='HPAN25PIANO1'`, `voce_id` nullable o ignorato
in scrittura.

### 8.2 Migrazione

- One-shot: bulk-set `societa_id='ORTI'`, `is_excluded=False`, `exclude_reason=NULL`
  su tutte le righe esistenti (baseline storica = ORTI, nessuna esclusione).
- Validazione tramite Pydantic in `core/schemas.py` (nuovo model `FornitoreMapRow`).

### 8.3 Loader BQ

`core/bq/load/load_fornitori.py` aggiorna lo schema BQ con la nuova colonna; rimane
SNAPSHOT.

---

## 9. Naming convention file output

```
<societa>_PF_<YYYY-MM>_post-rotate_<YYYY-MM-DDTHH-mm>.xlsx
```

Esempio: `ORTI_PF_2026-05_post-rotate_2026-05-20T14-30.xlsx`.

Il file output **non sostituisce** il file canonico nella cartella `pianfin/`; va
spostato manualmente da Stefano/Rosa come "file canonico del mese". Questo lascia il
file mensile sotto controllo umano.

---

## 10. Conformità invariants

- **I1** (gate Pydantic) — nuove scritture su `d_fornitori` passano per Pydantic
  `FornitoreMapRow`. Letture da BQ (saldi) usano i model esistenti.
- **I2** (lifecycle) — nessuna scrittura su tabelle fatti. `d_fornitori` è SNAPSHOT
  (rimane); lo step 3 appendina righe nuove → re-load completo della dimensione.
- **I3** (vault SSOT per ontologia) — risolto via schema (`is_excluded BOOL +
  exclude_reason TEXT`, §8.1): `voce_id` resta semantico, non si introduce una
  categoria reservata "IGNORE" che inquinerebbe l'ontologia delle voci PF.
  L'esclusione vive come *flag di routing*, separato dalla classificazione voce.
- **I4** (3 lenti) — pf-rotate vive interamente nella lente CASSA. Nessun overlap
  con COMPETENZA.
- **I7** (audience) — audience = Rosa (operativa) + Stefano (occasional CLI).
- **I8** (canonical view dedup) — non applicabile (Excel rotation, non view BQ).

---

## 11. Test

### 11.1 Unit tests (pure functions)

In `tests/test_pf_rotate.py`:

- `test_step2_azzera_solo_valori_mai_formule` — fixture con celle miste valore+formula
  in colonna mese chiuso → solo valori → None, formule intatte.
- `test_step1_saldo_iniziale_mese_nuovo` — fixture pre/post step 1+2 → r4 del mese
  nuovo (post-rotation) eredita correttamente da `f_saldi_banca_chiusura_mensile`.
- `test_step3_no_skip_unmapped` — fixture scadenzario con 1 fornitore non in
  d_fornitori → `write_pf` solleva (o blocca la run, in modalità interattiva).
- `test_controlli_22_check_ok_su_witness_orti_maggio` — fixture =
  `pianfin/05_ORTIFinancialPlan2026.xlsx` post-witness → tutti 22 check OK.
- `test_controlli_failure_modes` — fixture con master.D4 ≠ master.C37 → check #2
  fallisce con messaggio diagnostico.

### 11.2 Integration test (golden semantic-diff)

`tests/test_pf_rotate_golden.py`:

- Input: ORTI PF pre-rotation (snapshot vendored sotto `tests/fixtures/pf/`).
- Run: `pf-rotate` con scadenzario fixture + saldi mock.
- Assert: **diff semantico**, non byte-by-byte (gli xlsx hanno rumore di metadata,
  ordine zip, calc-state irrilevanti). Tolleranze:
  - Stessi nomi foglio.
  - Per ogni cella target (definita da una `target_cells_map` nella fixture): stesso
    valore (tolleranza float `1e-6` per numeri) o stessa stringa di formula
    (case-insensitive sui riferimenti, es. `=SUM(C6:C11)` ≡ `=SUM(c6:c11)`).
  - Le celle non-target (es. metadata workbook, sheet protection, dimensioni
    finestre) sono ignorate.

### 11.3 Smoke INTUR

Dopo Step 0 implementato, smoke su file reale INTUR:

```bash
hotelops pf-rotate normalize-intur --pf 05_INTUR_PF_2026_05.xlsx
hotelops pf-rotate --pf …normalized.xlsx --scad INTURsituazioneal30-04-2026.xlsx \
  --scad-tipo sintetica --mese-chiuso aprile --data-saldo 2026-04-30 --dry-run
```

Atteso: 22/22 controlli OK, fornitori unmapped esposti, nessun crash.

---

## 12. Open / Out-of-scope

### 12.1 Aperti, da decidere

- **CamerePrimoPiano** — i ~40 fornitori del cantiere appaiono nello scadenzario
  INTUR. Per v1 vanno marcati `is_excluded=True, exclude_reason='HPAN25PIANO1'`;
  un secondo spec li porterà nel modulo Progetti.
- **Saldi BCP / MPS_KROSS** — non sempre presenti nei master ORTI/INTUR. Il roll
  Step 1 deve gestire la cella mancante (skip-and-warn) senza alzare.

### 12.2 Out-of-scope (rimandati a spec separati)

- Voce → fonte per tasse / salari / mutui / entrate (riferimento [[PF_VOCE_FONTE]]).
- Spostamento codice CASHFLOW fuori da `verticals/condges/`.
- Estensione automatica del PF per nuovi mesi (oggi solo Apr-Dic, post-Dic richiede
  altro file).
- Ingest automatico dei movimenti banca INTUR — separato (task #6 in [[2026-05-18_pf_rotate_design_e_saldi_banca]]).
- API HotelCube, revman Power BI ingestion.

---

## 13. Related

- Decisions: [[2026-05-18_PF_Rotate_Design]] · [[2026-05-18_Cashflow_Modulo_Autonomo]]
- Sessions: [[2026-05-18_pf_rotate_design_e_saldi_banca]] · [[2026-05-19_rotation_maggio_witness_e_mappa_voci]]
- Concepts: [[PF_ROTATION_WORKFLOW]] · [[PF_VOCE_FONTE]] · [[LE_3_DIMENSIONI]] · [[EXCEL_GOOGLE_SHEETS_INTEROP]]
- Tabelle BQ: `f_saldi_banca_chiusura_mensile` · `f_partite_aperte_fornitori`
- Codice riusato: `verticals/condges/app_scadenzario.py` (`write_pf` da estendere) ·
  `verticals/condges/scadenze_parse.py` · `verticals/condges/scadenzario_excel.py` ·
  `core/bq/dimensioni/d_fornitori.csv`

