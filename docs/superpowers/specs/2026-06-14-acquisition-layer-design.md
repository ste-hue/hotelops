# HotelOps — Acquisition layer: mappa fonti, tier di refresh, primitivi

**Data:** 2026-06-14 · **Stato:** design approvato (mappa), spec in review
**Relazione:** sibling di `2026-06-14-hub-app-store-infrastructure-design.md`. Costruisce sul
**lineage path vivo** (`ingest/intake.py` + `ingest/promotion.py` + `core/lineage/*`) e sulla SSOT
`core/source_registry.yaml`. **Non** rianima il loop `IngestManager`/`SourceAdapter` (morto).

## Cos'è (e cosa non è)

Una **mappa** dello strato di acquisizione: classifica ogni fonte per **tier di refresh**,
definisce i **3 primitivi di automazione** che coprono tutti i tier, fissa il **freshness
contract** che lega l'acquisizione al hub, e pianifica la **bonifica dello scaffolding morto**.

**Non è** l'implementazione dei primitivi: ognuno avrà il suo plan/slice. È il documento che
decide *cosa esiste, come si aggiorna, e in che ordine si automatizza*.

## Perché conta — la spina dorsale

CdG e Cashflow non sono "app con dati": sono **l'apice di una pipeline** radicata nell'ERP/PMS.

```
Esolver (ERP) + HotelCube (PMS) ──intake/promote──▶ BigQuery (truth) ──▶ PF rotation ──▶ CdG / Cashflow
```

Corollario: **l'apice è vero quanto è fresca l'acquisizione sotto.** I movimenti banca a 32 giorni
avvelenano in silenzio il cashflow. Lo strato di acquisizione non è plumbing sotto il hub — è ciò
che rende affidabili le app di maggior valore. Per questo va modellato prima di automatizzarne i pezzi.

## Contesto — due modelli di ingest, uno morto

- **Vivo (l'unico reale):** lineage `intake → promote`. File → GCS + `f_raw_objects` → policy gate
  → parser (`parser_module` da registry) → tabella canonica. Trigger manuale oggi (CLI `hotelops
  intake`/`promote` o la pagina Ingest Streamlit). Governato da `source_registry.yaml`
  (30+ fonti: system, dataset, societa, lifecycle, canonical_table, parser, loop_targets,
  promotion_policy, raw_storage).
- **Morto (da bonificare):** `core/start_date.py` ha un **SyntaxError** (riga 126, non importabile);
  `core/ingest_manager.py` (`IngestManager`/`SourceAdapter` polling loop) e
  `core/sources/local_folder.py` (`LocalFolderAdapter`) ci dipendono → scaffolding inerte, mai
  cablato al lineage path. Verificato 2026-06-14. È una mina (sembra "automazione esistente" ma non
  lo è) → §Bonifica.

## Il principio — EXTRACT vs LOAD

Ogni fonte si separa su una domanda: **l'EXTRACT è automatizzabile (c'è un'API) o è un umano che
clicca "esporta"?** Il **LOAD** (intake→promote) è **sempre** automatizzabile una volta che il file
esiste. I due semi-cicli si automatizzano separatamente; la classe della fonte fissa il soffitto.

## Mappa delle fonti per tier di refresh

| Tier | Cadenza | Fonti (da `source_registry.yaml`) | EXTRACT | Automazione |
|---|---|---|---|---|
| **R — Real-time / API** | min/ore | Reviews (Apify ✅), coperti (registry: *"Google Sheet o XLSX"* → Sheets API), Workspace (Gmail/Cal/Drive — fonte futura) | pull schedulato | **end-to-end, zero umano** |
| **E — Export-bound** | giorni/settimane | Esolver ×7 (movimenti, fatture acq/vend, scheda, partite, bilancino, budget/gasparotto, PF), banche (MPS/SELLA/INTESA), HotelCube/PowerBI (consumi, ricavi_fb, produzione, statistiche), RistoCube orders, accodamenti TXT | **click umano** (no API) | umano esporta + back-half auto + nudge cockpit |
| **M — Manuale / raro** | mensile+ | Spiaggia dump (SNAPSHOT full-replace, MANUAL), bilanci annuali (XBRL), semantic model docs (RAW_ONLY) | manuale | resta manuale, bassa cadenza |

Note: Spiagge.it è oggi Tier M (dump manuale); **→ Tier R se/quando emerge un'API**. Coperti è
l'unico Tier E che può **salire a R** perché può vivere come Google Sheet (Sheets API).

## Stato reale GCS (2026-06-14) — la mappa è parziale

Il registry è il catalogo *inteso*; `gs://hotelops-raw` mostra cosa è **davvero atterrato**. Le due
viste divergono — la verità di build è GCS.

**Fonti che fluiscono nel bucket (con recency raw):**

| Fonte (prefix GCS) | files | ultimo raw | lettura |
|---|---|---|---|
| ESOLVER_MOVIMENTI ORTI/INTUR | 3+3 | 2026-06-11 | 🟢 attiva |
| ESOLVER_FATTURE acq/vend ×4 | 1 cad. | 2026-06-11 | 🟢 |
| ESOLVER_BILANCINO ORTI/INTUR | 6+5 | 2026-06-13 | 🟢 |
| HOTELCUBE_ACCODAMENTI ORTI | 13 | 2026-06-10 | 🟢 |
| ESOLVER_SCHEDA (saldi banca) ORTI/INTUR | 1+2 | 2026-05-08/10 | 🔴 **alimenta cashflow** |
| MPS_BANCA ORTI/INTUR, INTESA_BANCA ORTI | 4+1+1 | 2026-05-12 | 🔴 **alimenta cashflow** |
| ESOLVER_PARTITE ORTI/INTUR | 1+2 | 2026-05-13 | 🔴 |
| POWERBI_RICAVIFB ORTI | 24 | 2026-05-19 | 🟡 |
| MANUAL_BUDGET ORTI | 1 | 2026-05-19 | 🟡 |
| POWERBI_SEMANTICMODEL ORTI | 2 | 2026-05-07 | doc RAW_ONLY |

**Lettura cruciale:** le fonti 🔴 (scheda/saldi, banche, partite) sono *esattamente* quelle che
nutrono il cashflow, e l'umano ha **smesso di esportarle a metà maggio**. Il cashflow avvelenato non
è un bug di pipeline — è un export dimenticato, visibile nel raw layer. Il primitivo cockpit
(step 3) punta precisamente a questi.

**Due buchi che GCS rivela:**

1. **Copertura lineage parziale.** `f_ristocube_orders` (31k), `f_spiaggia_*` (33k),
   `f_consumi_economato` (24k), `f_produzione_pms`, `f_coperti` hanno dati canonici ma **nessun raw
   object nel bucket** — caricati *fuori* dal path GCS (legacy/diretto). L'auto-refresh via
   intake→promote **non li copre** finché non vengono onboarded al path GCS. Step 0 della build.
2. **Prefissi scaffolded ma vuoti, non nel registry:** `POWERBI_ANDAMENTOPRENOTAZIONI`,
   `POWERBI_BOOKINGS`, `POWERBI_BUDGETFORECAST`. Spazi di atterraggio pre-creati per dati
   **booking-pace / revenue-management / forecast** → famiglia di fonti **futura** (e una futura app
   hub Revenue/Occupancy). Da formalizzare nel registry quando i dati atterrano.

**Drift registry↔GCS** da riconciliare: registry ha fonti senza dati GCS (PF, coperti, economato
diretto, cruscotto); GCS ha prefissi non nel registry (BOOKINGS, ANDAMENTOPRENOTAZIONI,
BUDGETFORECAST, MANUAL_BUDGET vs ESOLVER_BUDGET). La riconciliazione è parte della fondazione
(freshness contract).

## I 3 primitivi (coprono tutti i tier, niente rewrite)

Costruiti **sul lineage path** (riusano `intake`/`promote` + `source_registry.yaml`), non sul loop morto.

1. **Scheduled puller** (Tier R) — Cloud Run *job* + Cloud Scheduler che chiama un'API (Apify,
   Sheets, Spiagge.it) → atterra in GCS → esegue `intake`+`promote`. Riusa **esattamente** il pattern
   già provato con `publish-export --deploy`. Reviews è all'80%.
2. **Watched-folder auto-promoter** (Tier E, back-half) — un prefisso GCS (o cartella) dove cadono
   gli export; un job schedulato fa intake+promote del nuovo, guidato dal registry. Riduce il compito
   umano al **solo click di export**. (Sostituisce per intento il `LocalFolderAdapter` morto, ma sul
   lineage path.)
3. **Ingest cockpit nel hub** (visibilità, tutti i tier) — la pagina Ingest mostra **freshness per
   fonte** (🔴 "banca 32gg — serve export"), drop-zone, coda di promote. Il hub **guida**
   l'acquisizione invece di subirla: dice *quale export andare a cliccare* e lo fa entrare in un gesto.
   Vedere-la-verità e nutrire-la-verità diventano la stessa superficie.

**Soffitto onesto:** Esolver e banche restano export-bound — l'unica "automazione" dell'EXTRACT
sarebbe RPA fragile sul portale della banca (credenziali, rotture). **Fuori scope** salvo diventi il
collo di bottiglia. Il target realistico non è "tutto automatico": è *automatizzare end-to-end le
fonti API, e rendere le fonti export one-click-to-promote e impossibili da dimenticare*.

## Freshness contract — il legame col hub

Ogni fonte espone una **freschezza grain-aware**: giorni dalla fine dell'ultimo periodo coperto
(non dalla data di scrittura), con soglia alla scala giusta (daily 🔴>7gg; monthly 🔴>40gg;
snapshot per cadenza attesa). Riusa/estende la logica di `hotelops health`. Una sola implementazione
alimenta **due consumatori**: le **card del hub** (`card_fn` del registry app) e i **nudge del
cockpit**. Proposta: aggiungere `refresh_tier` (R/E/M) e un hint di grain alle voci di
`source_registry.yaml`, e un `core/freshness.py` unico che calcola dalla `canonical_table`.

Simmetria: come il hub ha un **app registry** (chi/cosa si vede), il dato ha un **source registry**
(cosa/come si promuove). Stessa idea dichiarativa, due layer; la freshness di una card è una lettura
di quanto bene il source registry viene nutrito.

## Fit governance / lineage

- Tutto passa per **intake→promote** (I1 strict, I9): nessun primitivo scrive in BQ bypassando il
  raw_object. Lo scheduled puller atterra in GCS e promuove — non fa INSERT diretti.
- **Niente live-read** che salti BQ (es. leggere il Google Sheet a render-time): violerebbe
  "BQ unica fonte di verità + lineage". Tier R = *sync frequente in BQ*, non lettura live nel hub.
- Le `promotion_policy` restano il gate: `RAW_ONLY` non promuove; `MANUAL` (Spiaggia) non
  auto-promuove neppure nel watched-folder (distruttivo full-replace → resta esplicito).

## Bonifica scaffolding morto

- `core/start_date.py`: **rotto** (SyntaxError riga 126). Decisione: **rimuovere** insieme a
  `core/ingest_manager.py` e `core/sources/local_folder.py` se nessun consumer reale li usa
  (verificare i match grep: molti sono la stringa "start_date" come nome colonna, non l'import).
  Il watermark per i load incrementali, se serve, vive già nel lineage/`f_raw_objects`.
- Aggiornare `CLAUDE.md` (oggi descrive `IngestManager`/`SourceAdapter`/`LocalFolderAdapter` come
  vivi) e la nota `core/start_date.py`.

## Scope boundary

- Questo spec è **mappa + contratti + ordine**, non l'implementazione dei 3 primitivi.
- Auth/edge, app complesse, hub-infra: altri spec.
- Workspace come fonte (Gmail/Cal/Drive) è citata come Tier R **futuro**, non modellata qui.

## Ordine di esecuzione proposto (visibilità prima di automazione)

0. **Riconcilia registry ↔ GCS** + bonifica scaffolding morto (`start_date.py` & co.) + fix doc.
   Allinea il registry alla realtà GCS (aggiungi BOOKINGS/ANDAMENTOPRENOTAZIONI/BUDGETFORECAST,
   sana MANUAL_BUDGET vs ESOLVER_BUDGET); decidi se onboardare al path GCS le fonti caricate fuori
   (ristocube, spiaggia, economato, produzione, coperti) o lasciarle legacy. Toglie la mina, fissa
   l'universo reale delle fonti.
1. **Freshness contract** (`refresh_tier` nel registry + `core/freshness.py` grain-aware). Substrato
   per card e cockpit. Misura anche la recency **raw** (ultimo export atterrato), non solo canonica.
2. **Ingest cockpit** (visibilità nel hub). Il più alto valore/€: rende la staleness impossibile da
   ignorare e risolve la causa reale dei dati cashflow stantii (l'export dimenticato di metà maggio:
   scheda/saldi, banche, partite) — senza nuova infra.
3. **Scheduled pullers** (Tier R): Reviews end-to-end, poi coperti-Sheet. Toglie l'umano dove si può.
4. **Watched-folder auto-promoter** (Tier E back-half). Ultimo: più infra, e il click di export resta.

Razionale: non si automatizza ciò che non si vede; e il solo cockpit (3) sana il "ho dimenticato di
esportare" che è la causa concreta del cashflow avvelenato. Poi si automatizza il davvero-automatizzabile.

## Domande aperte (non bloccanti)

1. **Coperti**: oggi è Sheet o XLSX? Se Sheet → candidato Tier R immediato (Sheets API).
2. **Spiagge.it**: esiste un'API/endpoint, o solo dump manuale? Decide R vs M.
3. **Cadenza target per Tier E**: banche/Esolver — settimanale è accettabile per il cashflow, o serve
   bisettimanale? (fissa le soglie 🔴 del freshness contract).
4. **Workspace**: quali superfici davvero servono come fonte dati (vs solo MCP a runtime)?
