---
subsystem: condges
code_paths:
  - verticals/condges/pf_rotate/rotate.py
  - verticals/condges/pf_rotate/saldi_registry.py
  - verticals/condges/pf_rotate/pf_writer.py
  - verticals/condges/scadenze_parse.py
  - core/bq/load/load_saldi_banca_chiusura_mensile.py
  - core/bq/dimensioni/d_saldi_banca_chiusura_mensile.csv
  - core/bq/dimensioni/d_fornitori.csv
last_verified: 2026-10-26
source: tribal knowledge (Rosa) → first written 2026-05-13
---

# Procedura: Rollover Cashflow Mensile (Piano Finanziario Rosa)

> **⚠️ AGGIORNAMENTO 2026-06-23 — flusso e persistenza cambiati.**
> Lo step 2 NON usa più `streamlit run app_scadenzario.py` (file **cancellato**): si usa
> l'**app Cashflow** montata nel hub (`verticals/condges/app_cashflow.py`), che gira il
> motore canonico `pf_rotate.rotate()`. Conseguenze su questo doc:
> - **Persistenza mappatura fornitori:** NON più `st.session_state` (la nota "si perde al
>   refresh" più sotto è **superata**). "Salva mapping" fa `upsert_fornitore_bq` →
>   **MERGE su BigQuery `d_fornitori`** (chiave `codice_fornitore+societa_id`), permanente.
>   Il CSV `core/bq/dimensioni/d_fornitori.csv` è solo **seed/export**.
>   - ⚠️ **Doppia-verità (open):** gli upsert in-app NON vengono riscritti nel CSV. Il loader
>     `core/bq/load/load_fornitori.py` fa WRITE_TRUNCATE dal CSV (ora protetto da `--force`):
>     un reseed dal CSV stale **cancellerebbe** le mappature fatte in-app. Prima di QUALSIASI
>     reseed: `python -c "from verticals.condges.pf_rotate.fornitori_map import export_fornitori_to_csv, FORNITORI_CSV; export_fornitori_to_csv(FORNITORI_CSV)"` e committa il CSV.
> - **Importo per scadenza (fix issue #47, 2026-06-23):** `parse_scadenze` ora legge la colonna
>   **Z "Saldo scadenza in UDC"** (residuo per-scadenza, col 26), non più T "Importo apertura"
>   (col 20 = fattura intera ripetuta su ogni rata → importi sballati).

Ogni mese si genera un nuovo file Piano Finanziario (PF Rosa) a partire da quello del mese precedente. Il file mostra:

- **Mese corrente** (colonna 3 dello sheet master "Piano Finanziario"): primo mese previsionale. La sua riga 4 `SALDO MESE PRECED` = somma saldi banca a fine mese precedente (consuntivo).
- **Mesi N+1 → N+8** (colonne 4-11): proiezione forward di entrate e uscite.
- **Sheet dettaglio per voce USCITE** (es. `Materie Prime-Consumo `, `Utenze`, …): righe per singolo fornitore con importi per mese.

Il rollover N → N+1 sostituisce la colonna N con la N+1 come nuovo "mese corrente", aggiorna i saldi banca al consuntivo di fine N, e ridistribuisce i debiti residui fornitori secondo il nuovo scadenzario Esolver.

---

## Quando — il rito del giorno 1 (regola Stefano, 2026-10-26)

**Il giorno 1 di N+1 devono esistere gli input datati all'ultimo giorno di N.** Non "tra il 5 e il 10":
la rotation di N si fa appena il mese è chiuso, con una fotografia presa al 30/31 di N. Chiudere
settembre con uno scadenzario del 26/09 (successo il 2026-10-26) è un debito da rifare, non una rotation.

- Il contratto di freschezza di `ESOLVER_PARTITE_*_SNAPSHOT` ha `grace_day: 1`: dal 2 del mese
  `hotelops health` segna le partite STALE finché non c'è la foto di fine mese.
- I saldi di fine mese si prendono **dal foglio di Rosa "Saldi Banca Fine Mese"** (Drive), colonna
  di N compilata per **tutti** i conti del registry (`pf_rotate/saldi_registry.py`): ORTI = MPS, Intesa,
  **MPS Kross, Unicredit** (contati dal 2026-10-26); INTUR = Sella, MPS, Intesa. BCP resta fuori (D3).
  Senza un saldo obbligatorio il motore si ferma (gate O-A), non lo salta.

---

## Prerequisiti

| Input | Origine | Nota |
|---|---|---|
| PF mese N | Drive cartella Rosa, file col **nome semplice** `XXX_PF_YYYY-MM.xlsx` (= Rosa l'ha visto) | ORTI: layout month-closed; INTUR: fixed-snapshot (`C1="DATA RILEVAZ"`) |
| Saldi banca al 30/31 di N | Foglio Rosa "Saldi Banca Fine Mese" (Drive) → righe in `core/bq/dimensioni/d_saldi_banca_chiusura_mensile.csv` → `python -m core.bq.load.load_saldi_banca_chiusura_mensile` (CSV = verità, WRITE_TRUNCATE) | un saldo senza data di riferimento non si registra; la nota della riga cita il foglio |
| Scadenzario partite (×2 società) | Esolver "Situazione partite sintetica per fornitori", senza filtri, **esportato il 30/31 di N o dopo** | intake → `ESOLVER_PARTITE_<SOC>_SNAPSHOT`; attenzione: l'export "ORTI" può contenere INTUR (ragione sociale interna) |

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

### 2. Rotation — **automatizzata** (`hotelops pf-rotate`, oppure app Cashflow nel hub)

```bash
hotelops pf-rotate --pf <PF di N> --scad <partite al 30/31 di N> --societa ORTI \
  --mese-chiuso <N> --anno <YYYY> --unmapped-policy skip [--exclude 264]
```

Il motore fa da solo lo step 1 (saldi dal CSV→BQ, azzera il mese chiuso senza toccare formule,
avanza la cascata) e scrive un file nuovo `<SOC>_PF_<primo mese aperto>_post-rotate_<ts>.xlsx`;
con ERR nei Controlli il file esce con suffisso `_FAILED_CHECKS`. Più mesi arretrati = più giri in
catena sull'output precedente. I non mappati finiscono nel foglio `DA MAPPARE<n>`: li assegna Rosa.

Equivalente nell'app Cashflow (`verticals/condges/app_cashflow.py`, stesso motore), nell'app:

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
3. **Coerenza saldi banca**: la riga TOTALE BANCHE del master deve essere = somma di **tutti** i conti del registry (ORTI: MPS + Intesa + MPS Kross + Unicredit; INTUR: Sella + MPS + Intesa) e coincidere col subtotale del foglio di Rosa. Riga 4 (SALDO MESE PRECED) colonna N+1 deve essere uguale.
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
