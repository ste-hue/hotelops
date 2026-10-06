# Budget dalla Regia — backend del foglio, bozza, approvazione, portabilità

**Data:** 2026-10-06 · **Stato:** disegno approvato in conversazione, da pianificare ·
**Dipende da:** piano 2 della spec camere (`2026-10-04-budget-camere-panorama-design.md`,
§«Piano 2 — versioni, approvazione, viste»).

## La domanda

Stefano vuole scrivere il budget **dalla pagina della Regia** («rendiamo il foglio coi
numeri da completare un backend foglio nel OS, così aggiorno da là») e vuole i dati
**portabili** («rendiamo cose esportabili»). Solo il budget, per ora: le priorità e le
scadenze del Quadro restano fuori (`POST /ops` riservato nel Worker, altro pezzo).

## Cosa non cambia

- **Versioni + approvazione (I2).** Quello che si scrive nella pagina è una *bozza*. Diventa
  versione con un'impronta del contenuto; la approva solo Stefano; una versione approvata
  non si modifica mai. Cambia l'editor (la pagina al posto di Excel), non il modello.
- **Il budget è di hotelops.** `f_budget_versioni` / `f_budget_driver` in BigQuery sono la
  verità; la Regia (`mgmt_os`) mostra, non possiede ([[TRE_MODULI_REGIA_CDG_PIANO]]: la
  scheda è la lettura del CdG dentro la Regia).
- **Una sola verità per numero.** Obiettivo, ricavo «con i prezzi scritti», scarto ed
  effetti li calcola `verticals/condges/budget_camere/modello.py`; la pagina non ricalcola.
- **Il formato di scambio è il foglio xlsx** di `hotelops budget base` (fogli `Budget`,
  `Prezzi`, `Mesi`, colonne `foglio.COL_*`), che il parser del piano 2 rilegge per
  intestazione. Excel e pagina sono due editor dello stesso foglio.
- **Ogni scrittura canonica passa dal gate** (`bq_write_validated`, I1) e ogni versione ha
  il suo file in lineage (I9), anche se nasce dalla pagina.

## Architettura

```
browser ──OTP──▶ Worker regia (Access) ──/budget/*──▶ hotelops-budget-api (Cloud Run, privato)
                 │  GET /          KV html            │  FastAPI · modello.py · gate I1/I9
                 └─ inoltra con firma SA + email ─────┘  BigQuery: f_budget_bozze, f_budget_versioni, f_budget_driver
```

- **Servizio nuovo** `hotelops-budget-api`: FastAPI nel repo hotelops
  (`verticals/condges/budget_camere/api.py`), Cloud Run nel progetto `hotelops-suite`,
  regione `europe-west1`, **`--no-allow-unauthenticated`**. Non è esposto a nessun dominio.
- **La Regia non chiama l'API direttamente.** Il Worker `panorama_apps/regia` inoltra le
  richieste sotto `/budget/*` al servizio **dopo** aver verificato il JWT di Access, e
  aggiunge l'email autenticata (`X-Regia-User`). Un solo dominio, una sola login, nessun
  CORS, l'API non esiste per chi non passa dal Worker.
- **Firma delle chiamate**: service account dedicato `regia-budget@hotelops-suite` con il
  solo ruolo `run.invoker` sul servizio. La chiave JSON sta in 1Password
  (`regia · BUDGET_API_SA · prod`, vault work) e come secret del Worker
  (`wrangler secret put BUDGET_API_SA_KEY` incanalato da `op item get`). Il Worker firma
  un JWT RS256 con `jose`, ottiene l'ID token da Google, lo mette in `Authorization`.
  Il servizio accetta solo chiamate con quell'identità (Cloud Run lo impone).
- **Il hub (IAP) non c'entra**: resta la porta (tile), non il backend.

## Contratto dell'API (tre chiamate, nessun'altra)

Gradino e anno nel path: `/budget/{gradino}/{anno}`; oggi solo `camere-hotel` / `2027`.

### `GET /budget/camere-hotel/2027`
Risponde con:
- `bozza`: le righe correnti dei tre fogli (`budget`, `prezzi`, `mesi`), con le stesse
  chiavi delle colonne `foglio.COL_*`; se non esiste una bozza, la **base precompilata**
  generata come da `hotelops budget base` (osservato 2026, notti 2027 scalate, prezzi 2026,
  crescita 0, ragione vuota), marcata `origine: "base"`.
- `totali`: obiettivo 2027, ricavo con i prezzi scritti, scarto, quattro effetti — calcolati
  da `modello.py` sulla bozza.
- `approvata`: la versione approvata corrente (id, `approvato_il`, totali) o `null`.
- `mesi_stato`: per mese `osservato` / `stima` (da `Mesi`).
- `salvato_da`, `salvato_il`, `impronta` della bozza.

### `PUT /budget/camere-hotel/2027`
Corpo = la bozza intera (tre fogli, tutte le righe: **non patch**, la bozza è il foglio
intero come la versione). Il servizio:
1. valida per intestazione come il parser del piano 2 (colonne rinominate o mancanti →
   400 col nome; valori non numerici → 400 con cella);
2. **non accetta modifiche alle colonne osservate** (2026, calendario, notti reali): se
   differiscono dalla base → 409 con le celle;
3. ricalcola i totali con `modello.py` (una sola verità);
4. salva in `f_budget_bozze` (SNAPSHOT per `[gradino, anno]`: una riga, JSON delle righe,
   `impronta`, `salvato_da` = email dall'header, `salvato_il`) via `bq_write_validated`;
5. risponde come la GET.

### `POST /budget/camere-hotel/2027/approva`
- Rifiuta (403) se `X-Regia-User ∉ APPROVATORI` (= `stefano@panoramagroup.it`,
  `ste.dellapietra@gmail.com`); (409) se la bozza ha mesi `stima` (lista dei mesi); (409) se
  non c'è bozza o la sua impronta è già la versione approvata.
- Altrimenti: genera il file xlsx della bozza (stesso writer di `budget base`), lo registra
  in lineage (`intake`, fonte `HOTELOPS_BUDGETCAMERE_ORTI_APPEND`), e chiama **la stessa
  funzione** di `hotelops budget approva` del piano 2: righe in `f_budget_driver`, riga in
  `f_budget_versioni` con `approvato_da` = email, la precedente approvata → `ritirato`.
- Risponde con la versione nuova. CLI e API sono due porte della stessa funzione.

### Esportazioni
- `GET /budget/camere-hotel/2027/xlsx` → il foglio compilato con la bozza (o con la
  versione approvata se `?versione=<id>`): identico a quello che `budget base` + Excel
  produrrebbero; il parser del piano 2 lo rilegge senza perdita (round-trip).
- `GET /budget/export?vista=v_budget_approvato|v_camere_consuntivo_mensile|v_budget_camere_scostamento`
  → CSV della vista, intestazioni = colonne della vista. Nessun calcolo.
- Export verso HotelCube: **non in questo pezzo** (manca il formato dal direttore).

## La pagina (scheda «Budget» nel Quadro di mgmt_os)

Una domanda: *cosa decido per il 2027 e cosa produce?*
- In alto, i quattro totali vivi (obiettivo, con i prezzi scritti, scarto, effetti) e lo
  stato: «bozza salvata il … da …» / «versione approvata … il …».
- Tabella dei **mesi**: osservato 2026 (grigio, non modificabile), crescita obiettivo %
  (la cella gialla), obiettivo 2027 che ne esce, stato mese.
- Tabella dei **prezzi per categoria**: notti 2027, prezzo medio 2026, aumento %, prezzo
  2027, ricavo 2027, **ragione obbligatoria** su ogni riga cambiata (il salvataggio rifiuta
  una riga cambiata senza ragione).
- Bottoni: «Salva bozza» (PUT), «Scarica xlsx», «Approva» (solo approvatori; conferma; se
  rifiutato mostra i mesi stima).
- La pagina parla solo con `/budget/*` del proprio dominio; i calcoli tornano dal servizio.
- Il resto del Quadro resta una foto da KV: la scheda «Budget» è l'unica parte viva.

## Tabella nuova

`f_budget_bozze` — SNAPSHOT, chiave `[gradino, anno]`.

| Colonna | Tipo | Note |
| --- | --- | --- |
| `gradino`, `anno` | STRING, INT64 | `camere-hotel`, 2027 |
| `righe` | JSON | i tre fogli, chiavi = colonne `foglio.COL_*` |
| `impronta` | STRING | hash del contenuto, stessa regola delle versioni |
| `salvato_da` | STRING | email dall'header del Worker |
| `salvato_il` | TIMESTAMP | |
| `fonte` | STRING | `REGIA_BUDGET_API` |

Una bozza non è un fatto: non entra nelle viste e non si somma a niente.

## Verifica

- Contratto: le tre chiamate su un BigQuery finto (fake client come in `tests/test_cash_pf_service.py`): GET senza bozza = base; PUT valido salva e ricalcola; PUT con colonna rinominata → 400; PUT con osservato cambiato → 409; approva da non approvatore → 403; approva con mese stima → 409 con i mesi; approva valido → versione + ritiro della precedente.
- Round-trip: bozza → xlsx → parser del piano 2 → righe identiche al centesimo.
- Worker: `/budget/*` senza Access → 403; con Access → inoltro con `Authorization` e `X-Regia-User`; il servizio senza `Authorization` valida → 401 (test su Cloud Run reale, a mano, dopo il deploy).
- **Gate (regola hub)**: Stefano salva una bozza vera dalla pagina, la scarica, la riapre in Excel e torna uguale; poi la approva e `hotelops budget versioni` la mostra. Prima del merge, non dopo.

## Ordine

1. Piano 2 della spec camere (tabelle, parser, `carica`, `approva`, viste): è il prerequisito.
2. API: `GET`/`PUT`/`approva`/`xlsx` + `f_budget_bozze` + test.
3. Worker: route `/budget/*` con firma SA; secret; deploy.
4. Scheda «Budget» in mgmt_os (`html_export.py`), gate con dati veri.
5. Export CSV delle viste.

## Fuori da questo pezzo

Priorità e scadenze dalla pagina (`POST /ops`); altre voci oltre alle camere Panorama
(stesso schema, gradini nuovi); export HotelCube; automazione dei sync della Regia
(collect-actuals → publish → push).

## Punti aperti

- Chi oltre a Stefano può **salvare** una bozza (non approvare)? Oggi: chiunque passi da
  Access (= le due email di Stefano). Se entra il direttore, si allarga la policy Access,
  non il codice.
- Il Worker deve mostrare la scheda «Budget» anche quando il servizio non risponde? Proposta:
  sì, in sola lettura dall'ultima foto, con avviso «servizio non raggiungibile».
