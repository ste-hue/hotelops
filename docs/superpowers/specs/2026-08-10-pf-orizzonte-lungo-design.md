# PF orizzonte lungo — estensione a giugno anno+1 con rito annuale estendi+pota

**Data:** 2026-08-10 · **Stato:** draft, in review Stefano
**Worktree:** `pf-orizzonte-lungo` · **Vault:** [[ORIZZONTE_DI_TRAVERSATA]], [[OK_SUL_VUOTO]], sessione `2026-08-10_pf_orizzonte_lungo_e_2027_cieco`

## La domanda a cui risponde

*"Con che cassa arriviamo a giugno dell'anno prossimo?"* — non "come chiudiamo l'anno".
Il business produce apr–ott e brucia nov–mar; aprile e maggio riaprono ma assorbono
(ramp-up personale, approvvigionamenti): la cassa vera torna a **giugno**. Un PF che
finisce a dicembre mostra due mesi di traversata e ne nasconde sei — e il 2027 è il
picco del servizio del debito (743k di rate, INTUR +68%).

## Il modello (deciso con Stefano, 2026-08-10)

**Orizzonte fisso "giugno anno+1", rinfrescato una volta l'anno con estendi+pota.**

- **Adesso**: i master 2026 (ORTI apr-dic, INTUR mar-dic + col C snapshot) si
  allungano di 6 colonne → GENNAIO–GIUGNO 2027.
- **A metà 2027**: si estende fino a GIUGNO 2028 e si **potano** le colonne 2026.
  Il passato non si perde: è congelato nei file mensili (post-rotate + "nomi
  semplici" curati da Rosa su Drive, un file per mese = verità del mese).
- Il file resta a taglia ~15 colonne costante. Nessuna finestra che scorre ogni
  mese: la rotation mensile continua a lavorare su griglia fissa (decisione 05-18);
  estendi+pota è manutenzione **annuale** del template.

Convenzione nomi invariata: i post-rotate tengono il nome post-rotate; il nome
semplice (`XXX_PF_2026-MM.xlsx`) significa "Rosa l'ha visto" — Drive è l'archivio
dei buoni, si lavora in locale.

## I tre pezzi

### 1. Motore year-aware: chiave periodo ordinale (PREREQUISITO)

Con APR 2026 → GIU 2027 nello stesso foglio, **APRILE/MAGGIO/GIUGNO compaiono due
volte**. Oggi `find_month_columns` fa "latest col wins" → le scadenze di giugno 2026
finirebbero nella colonna di giugno **2027**. Il motore non deve MAI toccare un file
allungato prima di questo pezzo.

**Rappresentazione**: `periodo = anno*12 + (mese-1)` — resta `int`, firme invariate,
ordinamento corretto, `periodo+1` sostituisce `mese % 12 + 1`, `divmod(periodo, 12)`
recupera anno/mese per le etichette.

**Inferenza anno in `find_month_columns`**: scansione colonne da sinistra; anno di
partenza dalla riga-1 della prima colonna-mese (`C1` master ORTI, `D1` fogli
dettaglio, gestione INTUR col suo layout); l'anno incrementa a ogni wrap (numero
mese che *scende*, es. DIC→GEN). Le colonne sono cronologiche per costruzione.

**Guardia anti-confusione**: periodo e mese nudo sono entrambi `int`; ogni entry
point del motore rifiuta valori < 1000 con errore esplicito ("questo è un mese
nudo, serve un periodo").

**Punti da toccare (mappati)**: `excel_model.find_month_columns` ·
`step2_azzera.azzera_mese` · `controlli_sheet.advance_controlli` ·
`step3_scadenzario.apply_scadenzario` (+`min(bucket)`) · `pf_writer` (chiavi
`mese_{m}` → `mese_{periodo}`) · `step5_controlli.verifica_controlli`
(`ordered_mesi.index`) · `rotate.rotate` · `scadenze_parse.parse_scadenze` ·
CLI/app ai bordi (già year-aware: convertono la tupla in periodo).

**Fix bug latente incluso**: `scadenze_parse.py:120` oggi scarta `scad_year` dopo il
test "scaduto" — luglio 2027 sommato in luglio 2026. Con la chiave periodo il bucket
è per-periodo e il bug muore.

**Scadenze oltre orizzonte**: una scadenza in un periodo senza colonna nel foglio
NON viene scritta né sommata altrove: finisce in un secchio "oltre orizzonte"
riportato nel summary (CLI e app) con importo totale. Se il numero è grosso, è il
segnale che serve allungare.

### 2. Script di allungamento (one-shot, adesso)

`pf-extend --to 2027-06` su entrambi i master. Per master + 11 fogli dettaglio:

- aggiunge le colonne mancanti fino al periodo target: header mese (riga 2) +
  anno in riga 1 sulla prima colonna del nuovo anno;
- estende le formule di riga copiando il pattern dell'ultima colonna-mese con
  traduzione dei riferimenti (`openpyxl.formula.translate.Translator`): cascata
  saldo (`=<prev>37`), link ai fogli dettaglio, SUM di colonna;
- sposta la colonna TOTALI a destra e ne estende i SUM (vedi domanda aperta §5);
- NON tocca i valori esistenti: solo colonne nuove + spostamento TOTALI.

Output = file nuovo in `pianfin-out/` (mai mutare l'input), verifica umana in Excel
desktop con ricalcolo (⌘=) prima di qualsiasi uso. Stesso script per ORTI e INTUR
(layout-aware via `find_layout`, come il resto del motore).

### 3. Rito annuale: estendi + pota (giugno 2027)

Stesso comando con `--trim-before 2027-04` (o simile): oltre ad aggiungere le
colonne fino a GIUGNO 2028, **elimina le colonne dei periodi prima del cutoff**.

Insidia nota da gestire: la prima colonna superstite ha saldo iniziale
`=<colonna cancellata>37` → diventerebbe `#REF!`. La potatura **ri-ancora** la
prima colonna: congela il saldo iniziale come valore hardcoded (com'è oggi la
colonna d'apertura del file) prima di cancellare. Stesso trattamento per ogni
formula che punta a colonne potate (controllo post-trim: zero `#REF!` nel file).

## 4. Test

- **Golden di non-regressione**: rotation sul PF ORTI 2026 reale a 9 colonne →
  output identico cella per cella a oggi. Se cambia qualcosa, ho rotto qualcosa.
- **Collisione mesi**: fixture a 15 colonne (apr26–giu27) con scadenze giugno 2026
  E giugno 2027 → devono atterrare in colonne diverse.
- **Wrap dic→gen**: inferenza anno corretta sul confine.
- **Guardia**: mese nudo (es. `6`) passato dove serve un periodo → errore esplicito.
- **Oltre orizzonte**: scadenza 2027-07 su file che finisce a giugno 2027 → secchio,
  non scritta, riportata nel summary.
- **Estensione**: file esteso → `find_layout` ok, formule tradotte corrette
  (spot-check catena saldo e link dettaglio), zero `#REF!`.
- **Trim**: post-pota → prima colonna ri-ancorata, zero `#REF!`, rotation funziona.
- **INTUR end-to-end**: fixture da `INTUR_PF_2026-06` (il golden INTUR manca da
  sempre — thread aperto in CASH_PF, si chiude qui).

## 5. Domande aperte (per Stefano, non bloccanti per il pezzo 1)

1. **TOTALI** su 15 mesi a cavallo di due anni non corrisponde a nessun esercizio:
   nasconderlo, o sdoppiarlo (TOT stagione · TOT gen-giu)?
2. **Alla potatura**: tagliare tutto il passato o tenere 1-2 mesi chiusi di coda
   per contesto visivo?

## 6. Non-goals / vincoli

- **Nessuna scrittura BQ**: il PF è proiezione, resta fuori dal pool `f_*`
  (decisione 2026-06-19). Il motore continua a *leggere* saldi/fornitori da BQ.
- **Nessun ingest 2027 in `f_piano_finanziario_input`**: bloccato dall'ordine
  #120 (migrazione chiave hash prima di tutto) e #122 (la fonte SCADENZIARIO non
  ha pipeline). Fuori scope qui.
- **`NO_DATA` in `v_previsione_cassa`** e **fix #122**: thread separati in
  [[workstreams/CASH_PF]], non dipendono da questa spec.
- **Niente finestra mensile scorrevole**: le colonne non si rinominano mai
  (anti-pattern 05-18); l'orizzonte cambia solo col rito annuale.

## 7. Ordine di esecuzione

0. Rebase del worktree su main (il gate PR #121 non è nella base attuale).
1. Pezzo 1 (chiave periodo) con golden di non-regressione — il motore resta
   pienamente compatibile coi file a 9/10 colonne.
2. Pezzo 2 (allungamento) → file estesi in `pianfin-out/` → **verifica
   Stefano/Rosa in Excel** (gate umano, come per le pagine hub).
3. Prima rotation reale su file esteso (probabile chiusura luglio, coi saldi
   31/07 già annotati nel hub).
4. Pezzo 3 (`--trim`) può aspettare: serve a giugno 2027, ma farlo insieme al 2
   costa poco perché condivide tutta la meccanica di traduzione formule.
