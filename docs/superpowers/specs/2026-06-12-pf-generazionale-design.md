# PF generazionale — memoria delle rotazioni in `f_piano_finanziario_input`

**Data:** 2026-06-12
**Stato:** spec approvata a voce, in review scritta
**Dipendenze:** lineage Phase 1 (intake→promote), source registry
**Consumatore primario:** spec gemella `2026-06-12-hub-app-store-design.md` (pagina Cassa/PF)

## Problema

Il source `ESOLVER_PF_ORTI_SNAPSHOT` (e l'equivalente INTUR) scrive `f_piano_finanziario_input`
in modalità SNAPSHOT con natural key `(societa_id, voce_id, anno, mese, fonte)`: ogni file
post-rotate ingerito **cancella** i valori della generazione precedente (DELETE-INSERT,
`core/bq/write.py`). La curva forward storica ("cosa diceva il file di aprile su luglio")
sopravvive solo come xlsx immutabile su GCS — non queryabile.

`f_chiusura_mensile` non copre il gap: salva previsione-vs-consuntivo del solo mese chiuso
al momento di `hotelops chiudi`, non la curva forward per generazione.

La pagina Cassa/PF del hub richiede lo "specchio con memoria": confrontare le previsioni
attraverso le rotazioni. Questa memoria oggi non esiste in nessuna tabella.

## Decisione

`f_piano_finanziario_input` diventa **generazionale**: ogni file post-rotate ingerito
via intake→promote aggiunge le sue righe (APPEND), identificate da `raw_object_id`.
Il "presente" diventa una vista derivata. Nessuna tabella nuova, nessuna memoria duplicata.

### Modifiche

1. **Source registry** (naming grammar `<SYSTEM>_<DATASET>_<SOCIETA>_<LIFECYCLE>`):
   - rename + lifecycle flip: `ESOLVER_PF_ORTI_SNAPSHOT` → `ESOLVER_PF_ORTI_APPEND`;
   - **nuovo** source `ESOLVER_PF_INTUR_APPEND` (oggi un source PF INTUR non esiste —
     verificato 2026-06-12). In esecuzione: verificare il parser sul file INTUR
     normalizzato (layout fixed-snapshot) prima del primo promote;
   - `lifecycle: APPEND`; `natural_key` resta documentata come chiave della *generazione corrente*.
2. **`hash_riga`** in `ingest_piano_finanziario_xlsx` estesa: da
   `societa|voce|anno|mese|fonte` a `societa|voce|anno|mese|fonte|raw_object_id`.
   Senza questa estensione due generazioni collidono e il dedup le collassa.
   Righe con `raw_object_id IS NULL` (storiche, pre-lineage): invariate.
3. **Vista nuova `v_pf_corrente`** (`core/bq/views/v_pf_corrente.sql`):
   - per le righe `fonte = 'PIANO_FINANZIARIO'`: tiene solo l'**ultima generazione** per
     `(societa_id, voce_id, anno, mese)` — `ROW_NUMBER() ORDER BY data_caricamento DESC,
     raw_object_id DESC` (tiebreak deterministico);
   - tutte le altre fonti (CLI, APP, PARTITE, SCADENZIARIO, BVA_2026): pass-through invariato.
4. **`v_piano_finanziario_mensile`** legge `v_pf_corrente` al posto della tabella raw.
   La logica di priorità fonte interna (riga ~109) **non cambia**.

### Semantica di precedenza (esplicita)

La priorità fonte esistente è `CLI > APP > PARTITE > SCADENZIARIO > BVA_2026 > PIANO_FINANZIARIO`,
per `(societa, voce, anno, mese)`. La migrazione la conserva integralmente. Ne seguono:

| Scenario | Esito | Note |
|---|---|---|
| Generazione G1, poi correzione CLI | **CLI vince** | comportamento attuale, intenzionale |
| Correzione CLI, poi generazione G2 | **CLI vince ancora** | comportamento attuale, **conservato** |
| Generazione G1, poi generazione G2 | **G2 vince** (dentro fonte PIANO_FINANZIARIO) | il nuovo: latest-generation-wins via `v_pf_corrente` |

Lo scenario 2 è una scelta consapevole, non un'omissione: cambiare la precedenza
(es. "generazione nuova invalida le correzioni") altererebbe l'output di `hotelops pf`
ovunque esistano righe CLI/APP, violando lo smoke obbligatorio. Il rischio — una correzione
CLI stale che ombreggia il file nuovo — viene **reso visibile** invece che risolto qui:

- la pagina Cassa del hub mostra un badge "correzione CLI/APP attiva, precedente all'ultima
  generazione" sulle celle interessate (vedi spec hub);
- disciplina operativa: le correzioni CLI devono rientrare nell'Excel alla rotazione successiva;
- un'eventuale pulizia automatica delle correzioni a nuova generazione è una **decisione
  separata futura**, fuori scope (cambierebbe il workflow di update_previsione).

### Cosa NON cambia

- `update_previsione.py` (DELETE-INSERT per fonte CLI/APP): invariato.
- Parser xlsx: invariato salvo l'hash (stessa griglia, stesse voci).
- `hotelops chiudi` / `f_chiusura_mensile`: invariati (memoria di accuratezza, ortogonale).
- Le righe storiche già in tabella: nessun backfill distruttivo, restano la generazione
  più vecchia (o pre-lineage con `raw_object_id NULL`).

## Smoke obbligatorio (gate di accettazione)

`v_piano_finanziario_mensile` alimenta l'intera lente di Rosa. Prima di dichiarare
la migrazione completa:

1. **Pre**: catturare output completo di `hotelops pf` e `hotelops saldo` per ORTI e INTUR.
2. Applicare migrazione (deploy `v_pf_corrente` + redeploy `v_piano_finanziario_mensile`).
3. **Post**: ricatturare e fare **diff byte-per-byte**. Atteso: identico (la tabella oggi
   contiene una sola generazione per chiave → `v_pf_corrente` è l'identità su di essa).
4. Solo dopo il diff verde: primo intake→promote di una seconda generazione.

## Seed della memoria

Dopo lo smoke: intake→promote dei due file post-rotate del 2026-06-12
(`ORTI_PF_2026-05_post-rotate_*.xlsx`, `INTUR_PF_2026-05_post-rotate_*.xlsx`) +
eventuali PF mensili storici disponibili (più file storici = memoria più profonda dal giorno 1).

## Test

- `hash_riga` con `raw_object_id`: due generazioni stessa voce×mese → hash distinti.
- Semantica `v_pf_corrente`: latest-generation-wins dentro PIANO_FINANZIARIO,
  pass-through altre fonti, tiebreak deterministico.
- Parser: test esistenti invariati salvo fixture hash.

## Esecuzione

Commit atomici propri, separati dal lavoro hub UI (vincolo esplicito 2026-06-12):
registry+hash → vista+redeploy → smoke → seed.
