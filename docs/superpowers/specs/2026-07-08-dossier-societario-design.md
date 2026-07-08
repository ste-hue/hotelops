# Dossier societario ORTI/INTUR — miner Workspace + dati ufficiali

**Data**: 2026-07-08 · **Fronte**: `dossier-societario` · **Hub**: `workstreams/DOSSIER_SOCIETARIO.md`

## Obiettivo

Stefano diventa CEO di ORTI srl e INTUR srl e vuole nelle due cartelle Drive societarie
un archivio ordinato + ricostruzione completa: tutto ciò che nel Workspace
panoramagroup.it riguarda le due società (documenti Drive, email e allegati Gmail,
di **tutti** gli utenti del dominio) più i dati ufficiali via `openapi-ita`
(visure, bilanci, soci, catasto), classificato in una tassonomia da CEO, con indice
e lista di ciò che manca.

## Destinazioni e tassonomia

Cartelle Drive esistenti: ORTI `1jtik538_t4udzOM033KHXa88PaY-o53S`,
INTUR `1ZMjzCrYCNyHezHo7QdW-Hl3eNcz0eYFG`. Sotto ciascuna il miner crea (idempotente,
`ensure_subfolder`):

```
01_Societario        statuto, visure, verbali assemblea, cariche
02_Fiscale           F24, dichiarazioni, cartelle
03_Bilanci           bilanci depositati, bilancini, situazioni contabili
04_Banche_Finanza    contratti conto/mutuo/leasing, fidi, garanzie
05_Immobili_Catasto  visure catastali, planimetrie, atti
06_Personale         contratti, TFR, informative dipendenti
07_Legale_Ispezioni  GdF, antimafia, contenziosi, diffide
08_Contratti         fornitori, CDS (es. ALDEN), concessioni
_DaRivedere          classificazione incerta (review manuale)
```

I file già presenti nelle cartelle (oggi flat) vengono classificati nello stesso giro.

## Architettura

Nuovo modulo `workspace/miners/dossier_societario.py` + config
`workspace/dossier_config.py`, CLI `hotelops workspace mine-dossier`, sul pattern
del miner CapEx (dry-run, index, bucket certezza).

### Config per società (`dossier_config.py`)

Per ciascuna: `company_id` (ORTI/INTUR), ragione sociale e varianti di ricerca,
CF/P.IVA, `drive_folder_id`. Termini di ricerca:

- **INTUR**: `INTUR`, CF `00553430653` — termine distintivo, rumore basso.
- **ORTI**: MAI `orti` nudo (parola comune). Solo frasi: `"ORTI S.R.L."`, `"ORTI SRL"`,
  CF/P.IVA (recuperati via `CompanyAPI.name()` e fissati in config al primo run).

### Fase 1 — Census (read-only, nessuna scrittura su Drive)

1. **Enumerazione utenti**: Directory API (`admin.directory.user.readonly`, subject
   stefano@). Tutti i 12 account; i sospesi (`am@`) si tentano e, se l'impersonation
   fallisce, finiscono nel report come "non accessibile" → voce di gap list.
2. **Drive per utente**: per ogni utente, per ogni termine, `files.list` con
   `fullText contains '<term>'` (corpus `user`, `includeItemsFromAllDrives`).
   Raccoglie: fileId, nome, mime, owner, parents/path, modifiedTime, size.
3. **Gmail per utente**: `threads.list` con query sui termini; per i thread match,
   messaggi completi + allegati non-immagine (pattern CapEx pass 1+2; niente pass
   fuzzy al primo giro).
4. **Dedup**: per Drive fileId e per hash allegato (stesso PDF girato a 5 caselle =
   1 documento + lista di chi lo ha). La mappa proprietari/detentori si conserva:
   è informazione di dossier.
5. **Classificazione content-only**: mai sul nome file (mandato esistente
   "MAI matchare sul nome, sempre dentro"): testo estratto (PDF/docx/xlsx) →
   regole per categoria (es. F24/codici tributo → 02, "verbale di assemblea" → 01,
   "Guardia di Finanza" → 07, foglio catastale/particella → 05...). Sotto soglia
   di confidenza → `_DaRivedere`.
6. **Output census**: `census_<company>.jsonl` locale (ledger) + **Google Sheet
   indice** nella cartella società: una riga per documento (categoria proposta,
   fonte, owner, link, confidenza). Niente copie in questa fase.

### Fase 2 — Apply (dopo review del census)

`mine-dossier --apply`: copia i file Drive (`files.copy` impersonando stefano@) e
carica gli allegati Gmail nelle sottocartelle di categoria; aggiorna lo Sheet indice
con il link della copia. Ledger `applied` per fileId/hash → **idempotente**: run
successivi processano solo il nuovo. Mai move/delete degli originali: solo copie.

### Fase 3 — Dati ufficiali (openapi-ita, costi vivi)

Subcomando separato `dossier-official --company X --order visura,bilanci,soci`:
ordina via `VisureAPI`/`CompanyAPI` (visura storica ~€4.95, bilancio ottico ~€2.95/anno,
soci ~€2.30; polling asincrono ~15 min), scarica i PDF in `01_Societario`/`03_Bilanci`
e registra nell'indice. **Ogni ordine a pagamento è esplicito** (flag), mai automatico
in un run di mining. Catasto: lookup immobili per CF → `05_Immobili_Catasto`.

### Gap list

Tab dedicato dello Sheet indice: checklist CEO (statuto vigente, libri sociali,
contratti mutuo, polizze, concessioni demaniali...) spuntata automaticamente dove il
census ha trovato il documento, il resto = da chiedere a commercialista/notaio/banche.
Include gli account non accessibili (es. `am@` sospeso).

## Vincoli

- Scope minimi: Drive `drive.readonly` per leggere, `drive.file` impersonando
  stefano@ per scrivere (i file copiati appartengono a Stefano).
- Rate: pause tra utenti; batch Gmail come nel miner CapEx.
- Niente BigQuery in questo thread (il dossier vive su Drive; eventuale fact table
  in un fronte successivo se servirà).

## Definition of done

Census eseguito su tutti gli account del dominio per entrambe le società; apply
completato; cartelle popolate per tassonomia; Sheet indice + gap list; secondo run
a vuoto = 0 nuovi item (idempotenza dimostrata). Test: TDD sui componenti puri
(classificatore content-only, dedup, config) + dry-run end-to-end.

## Fuori scope

- Pass fuzzy Gmail (rumore; eventualmente secondo giro).
- Mining di account esterni al dominio (commercialista ecc.) → gap list.
- Automazione ricorrente (cron): il run resta manuale.
