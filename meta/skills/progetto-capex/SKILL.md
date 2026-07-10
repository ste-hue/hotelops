---
name: progetto-capex
description: Use when the user is working on a CapEx / investment project at Panorama Group (hotel rooms renovation, beach equipment, lighting, terrace, facade, reception, infrastructure). Triggers on "nuovo progetto capex", "apri progetto <nome>", "ho ricevuto un preventivo per <X>", "preventivi <scope>", "fattura <fornitore>", "a che punto siamo con <progetto>", "tracking progetto", "CapEx", or whenever the user references Drive paths under `04_Progetti_Investimenti/Investimenti<YYYY>/<project>/` or a project master xlsx. Two modes: KICKOFF (scaffold a new project from a project_id) and UPDATE (reconcile sources → cockpit). Overrides default instinct to edit xlsx ad-hoc: enforces canonical folder structure, per-fornitore F-folders, the 5-sheet cockpit model, 4-source reconciliation, and correct IMPEGNO→COMPETENZA→CASSA→CHIUSURA lifecycle.
---

# PROGETTO CAPEX — Workflow skill per progetti di investimento

Harness del workflow CapEx di Panorama Group. Enforce struttura Drive canonica, modello tracking a 5 fogli (cockpit operativo), riconciliazione multi-fonte.

## Come si invoca

L'utente chiama la skill con il **nome del progetto**. Due modi:

- **KICKOFF** — "apri progetto HPAN27SPIAGGIA" / "nuovo progetto capex <id>" → scaffolding completo: cartelle Drive + master xlsx vuoto con i 5 fogli. Vedi §Modalità KICKOFF.
- **UPDATE** — "aggiorna tracking <id>" / "ho ricevuto fattura X" / "a che punto siamo" → riconcilia le fonti e ricalcola il cockpit. Vedi §Modalità UPDATE.

Se l'utente nomina un progetto che non esiste ancora → proponi KICKOFF. Se esiste → UPDATE.

## project_id — naming canonico

`<BU><YY><TYPE>_<scope>` — es. `HPAN27SPIAGGIA_Lotto1`, `HPAN26PIANO2_Camere`.
- `<BU>` business unit (HPAN = Hotel Panorama)
- `<YY>` anno di avvio
- `<TYPE>` macro-scope (PIANO2, SPIAGGIA, RECEPTION, FACCIATA, TERRAZZA, ILLUMINAZIONE…)
- `<scope>` dettaglio libero

Non hardcodare progetti specifici in questa skill — il project_id arriva dall'utente.

## Prospettivo vs retrospettivo

- **Prospettivo** (default, il caso facile): registri ogni evento — preventivo, fattura, pagamento — *quando arriva*. Niente mining. La skill è soprattutto questo.
- **Retrospettivo** (recupero a posteriori): il progetto è già in corso/finito e si ricostruiscono le evidenze sparse. Doloroso. Vedi §Retrospettivo.

Avviare un progetto in modalità prospettiva fin dal giorno 1 è la differenza tra 20 minuti e 2 giorni di lavoro.

## Il modello — bottom-up, 4 domande

Un progetto CapEx **non parte dal budget**. Parte da cosa serve. Il budget è *emergente*: a volte è dato (target noto), spesso va *scoperto* sommando i costi man mano che arrivano. Non chiedere "quanto vogliamo spendere" come prima cosa.

Il progetto risponde, in ordine, a 4 domande:

1. **COSA CI SERVE** — gli *items* / work-package (es. "10 TV camere", "moquette", "impianto elettrico", "porte tagliafuoco"). È il punto di partenza, foglio `Scope_Items`.
2. **CHI CE LO DA** — il fornitore per ogni item, foglio `Tracking_Fornitori` (F-code).
3. **QUANTO COSTA** — preventivi (IMPEGNO) e fatture (COMPETENZA), aggregati per fornitore.
4. **QUANDO PAGHIAMO / QUANTO È SALDATO** — partite Esolver (CASSA), foglio `Chiusura_Fornitori`.

### Le 3 dimensioni — IMPEGNO → COMPETENZA → CASSA → CHIUSURA

Le domande 3-4 si articolano nel lifecycle che ogni fornitore percorre:

| Fase | Trigger | Evidenza |
|---|---|---|
| IMPEGNO | preventivo ricevuto / ordine firmato | PDF preventivo o contratto |
| COMPETENZA | fattura emessa dal fornitore | PDF fattura |
| CASSA | bonifico eseguito | partita chiusa in Esolver / bonifico |
| CHIUSURA | lavoro finito + tutto pagato | — |

Sequenza **append-only**: mai cancellare, mai tornare indietro senza registrare l'evento.

## Struttura Drive canonica

```
04_Progetti_Investimenti/Investimenti<YYYY>/<project_id>/
├── <project_id>_Tracking.xlsx          master cockpit (xlsx, NON Google Sheet nativo)
├── 00_contesto/                         briefing, vincoli, bando
├── FATTURE_<SCOPE>/                     drop-point fatture — SORGENTE
├── Preventivi_<SCOPE>/                  drop-point preventivi/offerte — SORGENTE
├── 07_fornitori/                        vista organizzata per fornitore (shortcut)
│   └── F<NNN>_<NOME>/
│       ├── 01_preventivi/
│       ├── 02_ordini_contratti/
│       ├── 03_fatture/
│       └── 04_comunicazioni/
└── 99_OOS/                              out-of-scope (fatture non pertinenti)
```

**Principio**: ci sono **due sorgenti canoniche** (`FATTURE_<SCOPE>/` e `Preventivi_<SCOPE>/`) dove l'utente droppa i PDF. `07_fornitori/F*/` è solo la **vista per fornitore**, popolata via shortcut. Il tracking xlsx legge le sorgenti, non si inventa la realtà.

## Anagrafica fornitori — globale, non per-progetto

I fornitori sono **entità globali**: definite una volta sola e riusate da tutti i progetti. Non si ridefiniscono per progetto. Vivono in due livelli:

- `Work/suppliers_registry.md` — rubrica globale: id stabile `SUP###`, tier **CORE / TACTICAL / TRANSIENT**, categoria, contatti, progetti in cui compare.
- `HotelOps/ontology/companies/<Nome>.md` — nota-entità completa per i fornitori **CORE** (ricorrenti, multi-progetto, obbligazioni residue).

La cartella `07_fornitori/F<NNN>_<NOME>/` di un progetto è **solo l'archivio-documenti di quel progetto**, non è l'anagrafica. Il numero `F<NNN>` è **locale al progetto**; l'**identità** del fornitore è la riga nel registry globale. Lo stesso fornitore può essere `F022` in un progetto e `F005` in un altro — va benissimo, perché a identificarlo è `SUP###` / la nota in `ontology/companies/`, non il numero di cartella.

**Conseguenze operative** (il *perché*: l'anagrafica vive una volta, i documenti vivono per-progetto — confonderli duplica e sporca):

- **Crea le F-folder per ingaggio**, non in anticipo. Una F-folder nasce quando arriva il primo documento di quel fornitore *per quel progetto*. Allo scaffold `07_fornitori/` resta vuota.
- **Mai copiare wholesale la lista F-folder di un altro progetto.** "Riusiamo i fornitori del progetto X" è un'illusione comoda: non sai ancora chi userai davvero, e pre-creare 30 cartelle vuote duplica l'anagrafica. I fornitori si riusano a livello di *entità* (registry), non di *cartelle*.
- **Fornitore nuovo** (non nel registry) → prima aggiungilo al registry globale col tier giusto (vedi `Work/ENTITY_REVIEW.md` per CORE/TACTICAL/TRANSIENT), poi crea la F-folder di progetto e linkala all'entità.
- Nei fogli `Tracking_Fornitori`/`Chiusura_Fornitori` il fornitore punta al nome canonico dell'entità globale; la colonna `Cartella F*` è solo il puntatore locale ai documenti.

## Master xlsx — 5 fogli (cockpit model)

| Foglio | Ruolo | Risponde a |
|---|---|---|
| `Summary` | dashboard | budget, IMPEGNO/COMPETENZA/CASSA, residuo, scoperti |
| `Tracking_Fornitori` | archivio documenti, 1 riga per F-code | "quali documenti ho?" |
| `Documents` | ogni PDF con link Drive | "dov'è il documento X?" |
| `Chiusura_Fornitori` | **cockpit operativo** | "abbiamo finito? quanto resta? chi va pagato?" |
| `OOS_Out_Of_Scope` | fatture non pertinenti al progetto | tracciabilità esclusioni |

### `Tracking_Fornitori` — colonne
`Cod | Ragione Sociale | Macro | Scope | # Prev | € Prev | # Contr | € Contr | # Fatt | € Fatt | Totale € | Status | Cartella F* (Drive)`

- **Totale €** = `MAX(€ Prev, € Fatt)` — MAI `Prev + Fatt` (la fattura *realizza* il preventivo: sommarli è double-counting).
- **Status**: `SCOPERTO` / `SOLO IMPEGNO` / `SOLO COMPETENZA` / `COMPLETO`.
- Ultima colonna: hyperlink `Apri →` alla cartella `07_fornitori/F<NNN>/` su Drive.

### `Chiusura_Fornitori` — colonne (il cockpit vero)
`Cod | Fornitore | Macro | Scope | € Prev/Contratto | € Fatturato | € Pagato | € Da Pagare | € Da Fatturare | Stato Operativo | Lavoro Finito? | Ultima Evidenza | Chi Lo Sa | Prossima Azione | Note`

- **€ Pagato** = `€ Fatturato − € Aperto` (da partite Esolver). **€ Da Pagare** = saldo aperto partite. **€ Da Fatturare** = `MAX(€ Prev − € Fatt, 0)`.
- **Stato Operativo**: `SCOPERTO` / `SOLO IMPEGNO` / `DA FATTURARE` / `DA PAGARE` / `LAVORI IN CORSO` (da pagare *e* da fatturare) / `CHIUSO` / `DUBBIO`.
- **Lavoro Finito? / Chi Lo Sa**: campi umani — riempi solo se l'informazione è certa, altrimenti lascia vuoto.
- **Prossima Azione**: derivata dallo stato ("sollecitare saldo", "verificare bonifico", "avviare lavori"…).

## Le 4 fonti da riconciliare

| Fonte | Cosa dà | Dove va |
|---|---|---|
| `FATTURE_<SCOPE>/` (Drive) | fatture PDF | shortcut → `F*/03_fatture/` → Documents → # Fatt / € Fatt |
| `Preventivi_<SCOPE>/` (Drive) | preventivi PDF | shortcut → `F*/01_preventivi/` → Documents → # Prev / € Prev |
| Esolver — "Lista fatture acquisto per fornitore" | tutte le fatture passive registrate | cross-check completezza: nessuna fattura deve mancare |
| Esolver — "Situazione partite fornitori" | saldo aperto per fattura | € Pagato / € Da Pagare nel cockpit |

**Importi**: il PDF fattura dà il *Totale documento* (con IVA). Esolver "ValTotImp" dà l'*imponibile*. Tieni una convenzione sola per progetto (di norma: Totale documento) e dichiarala nel `Summary`.

**Società**: le fatture possono essere intestate a entità diverse (INTUR, ORTI, Panorama Company…). Le partite Esolver sono per-società → servono entrambi gli export se il progetto ha fatture su più entità. Annota in `Note` quando un fornitore è intestato a una società che non vale per incentivi (ZES, Medio Credito Centrale, bandi).

## Modalità KICKOFF — scaffold nuovo progetto

Quando l'utente apre un progetto nuovo:

1. **Conferma il project_id** (naming canonico) e il committente canonico (UNA società).
2. **Crea le cartelle Drive** via il layer canonico `workspace/drive.py` (DWD,
   impersona `stefano@panoramagroup.it` — vedi §Tool):
   ```python
   svc = get_drive_writer("stefano@panoramagroup.it")
   for d in ["00_contesto", "FATTURE_<SCOPE>", "Preventivi_<SCOPE>", "07_fornitori", "99_OOS"]:
       ensure_subfolder(svc, project_folder_id, d)   # idempotente
   ```
3. **Non pre-creare le F-folder.** `07_fornitori/` resta vuota allo scaffold — le cartelle nascono per ingaggio (vedi §Anagrafica fornitori — globale, non per-progetto). Solo se ci sono fornitori già ingaggiati con documenti in mano, crea le F-folder *per quelli* (`07_fornitori/F<NNN>_<NOME>/{01_preventivi,02_ordini_contratti,03_fatture,04_comunicazioni}`) e linkale all'entità nel registry globale. Mai copiare la lista F-folder di un altro progetto.
4. **Crea il master xlsx** `<project_id>_Tracking.xlsx` con i 5 fogli vuoti (header pronti). openpyxl, salva locale, poi `upload_bytes(svc, project_folder_id, name, data, XLSX_MIME)`. Annota il **fileID** ritornato: è l'identità stabile del tracking.
5. **Registra il progetto** nel vault: `HotelOps/ontology/projects/<project_id>.md` (stato: avviato).
6. Comunica all'utente il link Drive del tracking + dove droppare fatture/preventivi.

## Modalità UPDATE — riconcilia → cockpit

Loop operativo standard (idempotente, ri-eseguibile):

1. **Backup** del master xlsx (`cp <master>.xlsx <master>.BACKUP_<timestamp>.xlsx`).
2. **Lista le sorgenti**: `svc.files().list(q="'<folder_id>' in parents and trashed=false", ...)` su `FATTURE_<SCOPE>/` e `Preventivi_<SCOPE>/`.
3. **Per ogni PDF sorgente**: identifica F-code dal nome fornitore; se manca lo shortcut in `F*/0X_.../`, crealo (`create_shortcut(svc, f_folder_id, name, target_id)`); estrai importo (`pdftotext -layout`, o vision per PDF scansionati).
4. **Aggiorna `Documents`**: una riga per documento, con importo + link Drive. Dedup per numero fattura (gestisci formati SDI tipo `FPR 12/26`, `IT00126V0001851`, `V326-00470`).
5. **Ricalcola `Tracking_Fornitori`**: # Prev, € Prev, # Fatt, € Fatt, Totale = MAX, Status.
6. **Ricalcola `Chiusura_Fornitori`**: incrocia con partite Esolver per € Pagato / € Da Pagare; deriva Stato Operativo + Prossima Azione.
7. **Ricostruisci `Summary`**: budget, totali, macro breakdown, lista scoperti.
8. **Salva sullo stesso file** e aggiorna in place via `svc.files().update(fileId=<tracking_id>, media_body=...)` → il fileID Drive resta stabile → **stesso link**. Mai creare `_v2`, `_v3`, mai delete+ricrea (cambierebbe il fileID).

## Playbook per evento (modalità prospettiva)

- **Arriva un preventivo** → droppa in `Preventivi_<SCOPE>/`, shortcut in `F*/01_preventivi/`, estrai totale, riga in Documents, UPDATE.
- **Ordine firmato** → PDF in `F*/02_ordini_contratti/`, è l'evento IMPEGNO esplicito (mai dedurlo dal "prezzo migliore").
- **Arriva una fattura** → droppa in `FATTURE_<SCOPE>/`, shortcut in `F*/03_fatture/`, estrai Totale documento, UPDATE.
- **Bonifico eseguito** → si riflette da solo al prossimo export "Situazione partite" (la fattura sparisce dalle aperte). UPDATE.
- **Fattura non pertinente** → shortcut in `99_OOS/`, riga nel foglio `OOS_Out_Of_Scope`, esclusa dai totali.

## Retrospettivo — recupero evidenze a posteriori

Se il progetto è già avviato senza tracking: stesso modello, ma le sorgenti vanno *ricostruite* prima.
1. **Mining automatico delle email**: `hotelops workspace mine-capex --project <id> --mailboxes gm@panoramagroup.it,amministrazione@panoramagroup.it --output-folder <DriveFolderID> [--keywords ...] [--fuzzy preventivo,offerta] [--extra 'after:2024/01/01']` — estrae thread + allegati dalle caselle e li deposita su Drive (miners: `triage_capex`, `classify_attachments`). Poi raccogli il resto a mano (Drive sparso, WhatsApp) → consolida in `FATTURE_<SCOPE>/` e `Preventivi_<SCOPE>/`.
2. Cross-check con Esolver "Lista fatture acquisto" per scoprire cosa manca ("nell'etere").
3. Poi gira la modalità UPDATE normale.

## Regole oro — non violabili

1. **Naming canonico** `YYYY-MM-DD_Fornitore_Dettaglio.pdf` per i preventivi; le fatture mantengono il nome del fornitore o `<Fornitore>_FT<num>_DEL_<data>`. I fileID Drive sono stabili al rename → i link reggono; si rompe solo la ricerca per nome.
2. **Mai marcare un fornitore "scelto/commitment" senza ordine firmato.** Fino all'ordine è fase Preventivo, fornitore "(candidato)". Il salto a IMPEGNO è un evento esplicito dell'utente.
3. **Mai presumere quantità preventivo = quantità da ordinare.** Il totale preventivato non è il totale da pagare. Se l'utente dà una quantità diversa, segnala la discrepanza.
4. **Mai mischiare entità committenti** senza dichiararlo. Scegli UNA società per progetto; se un preventivo è intestato altrove, chiedi riemissione o annota l'eccezione.
5. **Mai sommare € Prev + € Fatt** come "totale". Usa `MAX`. La fattura realizza il preventivo.
6. **Mai contare due volte lo stesso documento.** Una revisione di preventivo *sostituisce* la precedente (vecchia → categoria storica, non conta). Dedup per numero documento.
7. **Aggiorna sempre lo stesso file** (stesso fileID = stesso link). Niente `_v2`/`_v3`.
8. **Fornitori = entità globali, F-folder = archivio locale.** L'identità del fornitore è la riga in `Work/suppliers_registry.md` (`SUP###`) / la nota in `ontology/companies/`, non il numero `F<NNN>` di una cartella. Crea le F-folder per ingaggio; mai copiare wholesale la lista di un altro progetto.

## Anti-pattern da evitare

- Aprire il master xlsx in Excel mentre uno script openpyxl ci scrive → file corrotto.
- `insert_rows` su fogli con hyperlink/stili → duplica valori. Preferisci direct cell writes o read-all → clear → rewrite.
- Stringhe che iniziano con `=` in celle xlsx → Excel le interpreta come formula. Usa `→` o altro prefisso.
- Match fornitore per substring senza verifica → falsi positivi (omonimi). Verifica P.IVA o ragione sociale completa.
- Trattare `07_fornitori/F*/` come sorgente → è solo la vista. La verità sono `FATTURE_<SCOPE>/` + `Preventivi_<SCOPE>/` + Esolver.
- Pre-creare le F-folder copiando la lista di un altro progetto → presuppone il riuso, duplica l'anagrafica, lascia cartelle vuote. Crea per ingaggio; l'anagrafica vive nel registry globale.

## Tool e comandi frequenti

Layer Drive canonico = **`workspace/drive.py`** (service account DWD; per le scritture
impersona `stefano@panoramagroup.it`, che ha la quota storage). ⚠️ Il MCP Google Drive
gira sull'account personale, NON su panoramagroup: per questo flusso usa il workspace
layer. `rclone`/`mywork:` è il path legacy in dismissione — non costruirci sopra.

```python
# ~/.virtualenvs/hotelops_core/bin/python, dalla repo hotelops
from workspace.drive import (
    get_drive_writer, get_drive_reader,      # service Google API (DWD)
    ensure_subfolder,                        # mkdir idempotente → folder_id
    create_shortcut,                         # shortcut (non copia) → shortcut_id
    upload_bytes,                            # upload nuovo file → file_id
    ensure_shared_with,                      # condivisione silenziosa
)
svc = get_drive_writer("stefano@panoramagroup.it")

# lista sorgente fatture
svc.files().list(q="'<folder_id>' in parents and trashed=false",
                 fields="files(id,name,mimeType)", supportsAllDrives=True).execute()
# rename in place (fileID stabile) / update contenuto in place
svc.files().update(fileId="<id>", body={"name": "<nuovo>"}, supportsAllDrives=True).execute()
svc.files().update(fileId="<id>", media_body=MediaIoBaseUpload(...)).execute()
# download PDF
svc.files().get_media(fileId="<id>").execute()
```

```bash
pdftotext -layout "<file>.pdf" -    # estrai testo preventivo/fattura
```

PDF scansionati (senza text layer) → leggili con vision invece di pdftotext.
Mining retrospettivo email → `hotelops workspace mine-capex` (vedi §Retrospettivo).

## Chiusura progetto

Quando tutti i fornitori sono `CHIUSO` nel cockpit:
1. Export PDF del master in `00_contesto/<project_id>_consuntivo.pdf`.
2. Decision doc `HotelOps/decisions/YYYY-MM-DD_<project_id>_consuntivo.md`: budget vs consuntivo, scostamenti, lessons learned.
3. Aggiorna `HotelOps/ontology/projects/<project_id>.md` → stato "Consuntivo chiuso".

## Riferimenti cross-vault

- `HotelOps/concepts/PROGETTO.md` — concept layer
- `HotelOps/concepts/LE_3_DIMENSIONI.md` — IMPEGNO / COMPETENZA / CASSA
- `Work/workflows/PROGETTO_CAPEX.md` — workflow doc canonico (tieni allineato a questa skill)
- `Work/suppliers_registry.md` — rubrica fornitori globale (SSOT anagrafica, id `SUP###`, tier)
- `Work/ENTITY_REVIEW.md` — triage CORE / TACTICAL / TRANSIENT per nuovi fornitori
- `HotelOps/ontology/companies/` — note-entità per i fornitori CORE
