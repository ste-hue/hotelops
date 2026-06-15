# HotelOps Data-API — gateway read-only sottile su BigQuery (design)

**Data:** 2026-06-15 · **Stato:** design (da spec → plan)
**Decisione di riferimento:** `vault/decisions/2026-06-15_Una_Data_API_Non_Una_Per_App.md`
**Consumatori:** vetrina bespoke (drill live), futura CdG-mobile, future app.

## Cos'è (e cosa non è)

**Una sola** API sottile **read-only** su BigQuery. Serve **viste whitelistate come JSON** via
un endpoint generico `/data/<vista>` (+ in futuro pochi endpoint *compute*). È il "live" fatto
bene del modello vetrina: il frontend resta bespoke/mobile, ma quando serve "tutto, qualsiasi
taglio, fresco" chiama l'API invece di leggere uno snapshot statico.

**Non è:** un'API per app (è UNA), non scrittura (v1), non SQL arbitrario, non un ORM, non un
re-implement della logica di dominio (la logica vive nelle **viste BQ** = i contratti).

## Perché (la leva)

Era-AI: il frontend è economico. La leva è **dati puliti + accesso uniforme**. La **vista BQ è
il contratto**: aggiungere una superficie di lettura = whitelist di una vista → **zero backend
nuovo**. Le app sono frontend sottili sopra la spina BQ. Una API = un deploy, un auth, niente
N-backend con plumbing duplicato.

## Architettura

```
  Frontend (vetrina, CdG-mobile…)
       │  GET /data/v_fb_kpi?anno=2026
       │      /data/f_reviews?piattaforma=BOOKING&limit=100
       ▼
  hotelops-api (FastAPI · Cloud Run · scale-to-zero)
   ├─ GET /data/<vista>?<filtri>&limit&offset   ← generico, viste whitelistate
   ├─ GET /meta                                  ← elenco viste esposte + schema (discovery)
   └─ (futuro) POST /cdg/scenario, /reviews/search  ← compute, fuori v1
       │  SELECT su viste whitelistate (parametrizzato), service account ADC
       ▼
  BigQuery (viste = contratti)
```

- **Stack:** Python **FastAPI** + `uvicorn`, container su **Cloud Run** (scale-to-zero ≈ €0 da
  fermo). Legge BQ col **service account del servizio** (ADC, come l'hub Streamlit — nessuna
  chiave nell'immagine). Riusa `core.bq.client.get_client()`.
- **Posizione nel repo:** `api/` a root (parallelo a `core/`, `ingest/`, `verticals/`). Importa
  `core/`, non è un vertical (è infra che serve *tutti* i vertical).

### Endpoint generico `/data/<vista>`

- `vista` deve essere nella **whitelist**; altrimenti 404.
- **Filtri** = query param mappati a `WHERE col = @val` **parametrizzato** (mai string-interp).
  Solo colonne dichiarate filtrabili per quella vista; valore validato per tipo.
- `limit` (default 500, max 5000), `offset` per paginazione.
- Risposta: `{ "schema": 1, "view": "<vista>", "rows": [...], "count": N, "generated_at": "…" }`.

### Whitelist — `api/views_registry.yaml`

SSOT di *cosa* l'API espone. Per ogni vista:
```yaml
v_fb_kpi:
  filterable: [anno, mese, business_unit_id]
  default_limit: 500
f_reviews:
  filterable: [piattaforma, business_unit_id, sentiment_nlp]
  default_limit: 1000
```
Niente in whitelist = niente esposto. Previene injection + query incontrollate. (Parallelo
concettuale a `core/source_registry.yaml`: lì *come si promuove*, qui *cosa si legge*.)

## Sicurezza (non negoziabile)

- **Read-only:** solo `SELECT` su viste whitelistate. Nessun DDL/DML. Niente `f_*` raw di default
  (esponi viste curate, non tabelle fatto grezze).
- **Filtri parametrizzati** + colonne whitelistate → no SQL injection.
- **Auth all'edge:** l'API espone dati finanziari → **gated**. Cloudflare Access o un token
  (decisione aperta, vedi sotto). Stesso set identità di IAP/Access (workspace + i 2 gmail).
- **CORS:** allow-list dell'origine vetrina (`*.workers.dev` / dominio futuro), non `*`.
- **Cost guard:** ogni richiesta = una query BQ → cache TTL breve (es. 300s) per `vista+filtri`,
  + limite righe. Cloud Run scale-to-zero.

## Slice incrementali

1. **v1 — il gateway di lettura.** `/data/<vista>` generico + `views_registry.yaml` (whitelist
   iniziale: `v_fb_kpi`, `f_reviews`, + 2-3 utili) + `/meta` + cache TTL + CORS + auth + Dockerfile
   Cloud Run. **DoD:** la **vetrina** punta qui per il drill (es. *tutte le reviews live* via
   `/data/f_reviews?…` invece dello snapshot statico). Test: contratto risposta, filtri
   whitelistati, rifiuto vista non-whitelisted, rifiuto colonna non-filtrabile.
2. **v2 — endpoint compute.** `/cdg/scenario` (motore budget i/p/o/z/v/f), `/reviews/search`
   (semantic). Logica vera che una vista non fa.
3. **v3 — scrittura.** `update previsione`, ecc. — dietro RBAC. Fuori scope ora.

## La vetrina diventa ibrida (non full-live)

Decisione di design: la vetrina **resta statica per il colpo d'occhio** (home, card, semaforo,
grafici = veloce, gratis, offline-ok) e **chiama l'API solo per il drill on-demand** (sfoglia
tutte le reviews live, scegli un taglio non nello snapshot). Il meglio dei due: caricamento
istantaneo + profondità live quando la chiedi. (Niente Streamlit, niente full-server-roundtrip
per ogni vista.)

## Fuori scope v1

- Compute endpoints, scrittura, RBAC fine, semantic search, esposizione di tabelle `f_*` raw,
  GraphQL/query-language ricco. YAGNI finché una superficie reale non lo chiede.

## Domande aperte (da chiudere prima del plan)

1. **Auth edge:** Cloudflare Access (serve dominio/zona — `panoramagroup.it` non è su Cloudflare)
   **o** un token semplice (header `X-API-Key`) per partire? → propendo token per v1, Access dopo.
2. **Cache:** in-process semplice (TTL dict) **o** affidarsi alla cache di BQ? → in-process v1.
3. **Whitelist iniziale:** quali viste in v1 oltre a `v_fb_kpi` + `f_reviews`? (candidate:
   `v_fb_consumi`, `v_economato_consumi`, `v_spiaggia_*`).
4. **Vetrina ibrida vs full-live:** confermare ibrida (statico + API-per-drill).
