# CEO Cockpit — ufficio CEO su AMM_CEO (design)

**Data:** 2026-09-11 · **Stato:** approvato in chat, in attesa di review scritta
**Repo edge:** `panorama_apps/ceo/` (nuovo) · **Produttore:** hotelops
**Precedenti:** spec `2026-07-17` (PEC multi-casella, pannello AMM_CEO), spec `2026-08-05-pec-novita-design.md`, decisione 2026-06-20 "front-door JS differito" (STATUS.md), `panorama_apps/bilancini` (pattern edge + push KV)

## 1. La domanda

**"Cosa devo fare, firmare o rispondere, per società?"**

Una pagina, una domanda (regola hub, CLAUDE.md). Tutto ciò che sta sulla pagina si giustifica contro questa domanda. Lo storico di AMM_CEO (bp, personale, verbali, PEC vecchie) resta su Drive: è drill-down, non prima pagina.

Perché nasce ora: la "sveglia" messa il 2026-06-20 ("JS quando il soffitto look/feel di Streamlit morde davvero") è suonata. Il cockpit CEO è la prima superficie che nasce fuori da Streamlit, non una pagina in più nel hub.

## 2. Dove vive: repo separato, pattern `bilancini`

Decisione: **repo separato** sotto `panorama_apps/ceo/`, non un vertical di hotelops.

Motivi:
- `panorama_apps/STATUS.md` fissa la regola: le app edge non condividono codice con hotelops; gli parlano solo via BigQuery o push. `bilancini` è il precedente esatto (Worker + KV + Access, contenuto spinto da un builder in hotelops con `--push`).
- Il gating è già risolto: dominio `panorama-host.com` su Cloudflare, Access con OTP nominativo. Il ramo "gating JS" lasciato aperto a giugno è chiuso da luglio.
- Il front-end statico legge un file, non interroga BigQuery a ogni rerun: risolve anche il "lento".

Il hub Streamlit resta in piedi per i tool che scrivono (Cashflow, Accodamenti): configurazione "JS principale, Streamlit contenitore-tool" già propesa a giugno.

Nota: il punto 7 del pattern in `panorama_apps/STATUS.md` ("UI = NiceGUI o Streamlit") è stale — le quattro app live sono tutte Worker + JS senza framework. Da correggere nel commit che registra `ceo/` nel registry.

## 3. Architettura

```
hotelops (produttore)                          panorama_apps/ceo (edge)
┌────────────────────────────────┐             ┌───────────────────────────┐
│ job Cloud Run `pec-fetch` 04:00│             │ Worker ceo.panorama-host  │
│  fetch && classify             │   PUT bulk  │  Access nominativo        │
│  && build_ceo_cockpit --push ──┼────────────▶│  KV CONTENT: html,        │
│                                │  api.cf KV  │              data.json    │
│ legge: v_pec_novita            │             │  GET / → html             │
│        v_pec_classificazione_  │             │  GET /data.json           │
│          corrente              │             └───────────────────────────┘
│        f_pec_panel_projections │
└────────────────────────────────┘
```

Nessuna data-API, nessun D1 in v1: la pagina è sola lettura e il contenuto è un artefatto rigenerato ogni notte. Coerente con l'audit 2026-09-09 (`hotelops-api` resta parcheggiata).

## 4. Produttore: `verticals/ceo/build_cockpit.py`

Copia della forma di `verticals/condges/build_bilancini_artifact.py`, **non** un'astrazione condivisa (l'audit dice: copia, non framework). Un file, tre funzioni pubbliche: `fetch_items(client)`, `build_payload(rows)`, `render_html(payload)`, più `push_to_kv` e `main`.

### 4.1 Query

Una sola query, base `v_pec_novita` (già filtrata su POSTA_CERTIFICATA in RECEIVED), LEFT JOIN `v_pec_classificazione_corrente` su `msgid`, LEFT JOIN `f_pec_panel_projections` su `msgid` (status `COPIED`, una riga per allegato proiettato, aggregata in array).

Filtro: `data_evento >= DATETIME_SUB(CURRENT_DATETIME(), INTERVAL 30 DAY)` — **`data_evento` è DATETIME**, non TIMESTAMP (già inciampato in fase di design).

Un messaggio è **da vedere** se almeno uno vale:
- `importance = 'ALTA'`
- `mittente_nuovo OR oggetto_nuovo OR allegati_nuovi` (novità relativa al mittente, spec 2026-08-05)
- `stato = 'NON_CLASSIFICATO'` (l'ignoto è visibile per default: lezione Oliva Coperture, 2026-08-05)

Gli altri messaggi in arrivo nella finestra si contano ma non si elencano ("+N routine").

Finestra 30 giorni e non 7: misurato l'11/09 con dati reali, 7 giorni danno 2 messaggi da vedere in tutto il gruppo, 30 giorni ne danno 7. Il numero è nel golden check (§8).

### 4.2 Contratto `data.json`

```json
{
  "generato_il": "2026-09-11T04:12:00Z",
  "finestra_giorni": 30,
  "entita": [
    {
      "entity_id": "INTUR",
      "drive_folder_url": "https://drive.google.com/drive/folders/1I-Mn2s8o58m4urWVZioTF9MoUE8o1GN3",
      "da_vedere": [
        {
          "msgid": "...",
          "data_evento": "2026-09-09T12:21:30",
          "mittente": "certpec.camcom.it",
          "subject": "...",
          "categoria": "REGISTRO_IMPRESE",
          "document_type": "ALTRO",
          "importance": "ALTA",
          "stato": "CLASSIFICATO",
          "motivi": ["ALTA", "OGGETTO_NUOVO"],
          "allegati": ["RicevutaRi.pdf"],
          "documenti_pannello": ["INTUR/PEC/Registro Imprese/2026-09 - RicevutaRi.pdf"]
        }
      ],
      "routine": 3
    }
  ]
}
```

- `entita` = `PANEL_ENTITIES` in ordine fisso (INTUR, ORTI, VIGNA), sempre presenti anche a zero righe. `STEFANO_PERSONALE` fuori: non è in `PANEL_ENTITIES` e la domanda è "per società".
- `drive_folder_url` da una mappa statica in `core/config.py` (`PANEL_DRIVE_FOLDER_IDS`), accanto a `PANEL_ROOT`. La projection su Drive avviene sul Mac (sync-panel legge il mirror locale), hotelops non conosce i file id: il link va alla cartella della società, il nome del documento è in `documenti_pannello`.
- `motivi` è la lista dei criteri scattati: la pagina la mostra, così si capisce **perché** un messaggio è lì.
- Il payload non contiene `body_text`: la pagina è un indice, il contenuto si legge in casella o su Drive.

### 4.3 Push e schedulazione

- `--push`: PUT bulk sulle chiavi `html` e `data.json` del KV del Worker `ceo`, stesse env `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` più `CEO_KV_NAMESPACE_ID`. Fail-fast prima di toccare BigQuery, come in bilancini.
- Il job Cloud Run `pec-fetch` (04:00) diventa `fetch && classify && build_ceo_cockpit --push`. Le tre variabili entrano nel job da Secret Manager, non in chiaro nel comando `gcloud run jobs update`.
- Se il push fallisce il job fallisce (exit ≠ 0): la pagina mostra il `generato_il` precedente, e la staleness è visibile (§5).
- Rimane possibile lanciarlo a mano dal Mac con `.env`, come il rito bilancini.

## 5. La pagina (repo `panorama_apps/ceo/`)

Struttura come `bilancini`: `src/index.js` (routes `/` e `/data.json` da KV, 503 se non pubblicato), `src/access.js` (verifica JWT Access in-Worker, fail-closed), `wrangler.jsonc` con dominio `ceo.panorama-host.com`, KV `CONTENT`, vars `ACCESS_TEAM_DOMAIN`/`ACCESS_AUD`. Access policy nominativa: **solo `stefano@panoramagroup.it`** (più le caselle personali già usate su HPAN26 se servono da telefono).

L'HTML è generato dal builder (come bilancini): niente framework, niente fetch a runtime, CSS inline. Layout:

1. **Testata**: "Ufficio CEO", `generato_il` in forma "aggiornato oggi 04:12" / "aggiornato 3 giorni fa" — se più vecchio di 36 ore la testata è in evidenza (staleness = segno in presentazione, ha la stessa dignità dei numeri). La pagina è statica e renderizzata al push: la staleness la ricalcola uno script **inline** all'apertura (nessuna richiesta esterna), altrimenti "3 giorni fa" resterebbe fermo al momento del push.
2. **Tre colonne** INTUR · ORTI · VIGNA (una sotto l'altra su telefono). In testa a ogni colonna: `N da vedere` e link "apri su Drive".
3. In ogni colonna, le righe `da_vedere` ordinate per `data_evento` decrescente. Ogni riga: data, categoria come etichetta, oggetto, mittente, motivi (chip: ALTA / mittente nuovo / oggetto nuovo / allegati nuovi / non classificato), nomi allegati. Se `documenti_pannello` è vuoto, si vede che il documento non è ancora sul pannello.
4. In fondo alla colonna: "+N di routine negli ultimi 30 giorni".
5. Colonna vuota = "niente da vedere" esplicito, non uno spazio bianco.

Nessun grafico, nessun contatore oltre quelli sopra.

## 6. Cosa NON entra (v1)

- **Stato "evasa"/"fatto"**: vorrebbe D1 come HPAN26. Si valuta dopo aver letto la pagina con dati reali per qualche settimana (v2).
- **Scadenze Registro Imprese, fiscali, contenziosi**: oggi non esistono come dato in BigQuery. Non si inventano (niente moduli speculativi); entrano quando esiste una fonte.
- **Digest markdown** (`AMM_CEO/_digest/`): resta il canale WhatsApp di NanoClaw delle 07:00. La pagina calcola la stessa cosa dalle viste; non legge il markdown (vive su un mirror locale, non raggiungibile dal job cloud).
- **Bp, personale, verbali, storico**: su Drive, raggiungibili dal link di colonna.
- **Migrazione delle altre pagine del hub** fuori da Streamlit: fuori scope.

## 7. Errori e casi limite

- Vista assente o query fallita → il builder esce con errore, nessun push, il contenuto precedente resta in KV.
- Messaggio senza classificazione corrente (classify non ancora girato) → `stato = 'NON_CLASSIFICATO'` implicito → da vedere.
- Messaggio senza mittente → i tre flag di novità sono falsi per costruzione della vista; entra solo se ALTA o non classificato.
- Access JWT mancante o non verificabile → 403 dal Worker, anche se l'edge avesse lasciato passare.

## 8. Test e gate di lettura

**hotelops** (`tests/test_ceo_cockpit.py`):
- `build_payload` con righe fixture: tre entità sempre presenti, ordinamento per data, `motivi` corretti per ciascun criterio, `routine` = messaggi nella finestra non da vedere.
- `render_html` con payload vuoto: tre colonne con "niente da vedere"; con payload pieno: nessun `body_text`, staleness in evidenza sopra le 36 ore.
- `push_to_kv` con `requests` mockato: chiavi `html` e `data.json`, errore su risposta non `success`. Nessun test tocca BigQuery né il KV reale.

**panorama_apps/ceo** (vitest, come le sorelle): 403 senza JWT, 503 senza contenuto, 200 con content-type corretto, 405 su POST.

**Golden check al primo push con dati reali** (misurato 2026-09-11, finestra 30 giorni): INTUR 5 in arrivo / 5 da vedere, ORTI 2 / 1, VIGNA 1 / 1. I numeri scorrono con la finestra: il check è "stessi numeri della query eseguita lo stesso giorno", non valori fissi.

**Gate di lettura** (regola hub): la pagina non si considera fatta finché Stefano non l'ha vista con dati reali su `ceo.panorama-host.com` e ha risposto: *tra le righe da vedere c'è qualcosa che avrei voluto sapere e non sapevo?* Se sono tutte cose già note da WhatsApp o dalla casella, il cockpit è un duplicato e si ferma qui.

## 9. Decisioni prese in questa spec

| # | Decisione | Alternativa scartata |
|---|---|---|
| D1 | Repo separato `panorama_apps/ceo/` | vertical hotelops / cartella `web/` nel repo Python |
| D2 | Cloudflare Worker + Access, pattern bilancini | Cloud Run + IAP (gating già risolto su panorama-host.com) |
| D3 | Contenuto spinto da hotelops su KV | data-API live (parcheggiata, audit 09-09) |
| D4 | Finestra 30 giorni | 7 giorni (pagina quasi vuota con i volumi reali) |
| D5 | Sola lettura in v1 | stato "evasa" su D1 (rinviato a dopo il gate di lettura) |
| D6 | Builder copiato da bilancini, non astratto | libreria `edge_push` condivisa |
| D7 | Link Drive alla cartella società | file id per documento (hotelops non li conosce) |
