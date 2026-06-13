# HotelOps Hub — Viewer static-edge (design)

**Data:** 2026-06-13 · **Stato:** design approvato (modello), spec in review
**Supersedes:** la decisione "origin Cloud Run always-on dietro Cloudflare Tunnel + Access
per tutta la hub" (task publish). Resta valida *solo* per l'app admin; il layer-direttore
cambia modello (vedi sotto).

## Contesto

La hub ha due audience (deciso 2026-06-12): **admin** (Stefano, tutte le superfici incluse
le scritture) e **viewer** (direttore, sola lettura). Finora entrambe erano Streamlit. Il
tracker Mutui (Worker Cloudflare statico) ha reso evidente un'asimmetria: è online a costo
zero perché è statico, mentre la hub Streamlit resta localhost perché è un server Python.

Osservazione chiave: **i dati di HotelOps non sono mai realtime.** F&B è a grana mensile,
le reviews arrivano a scrape periodici, la rotation PF è mensile, i mutui sono piani fissi.
Quindi quasi ogni superficie di *lettura* può essere uno snapshot rigenerato su schedule.

## La regola di confine

Cosa va dove si decide con una domanda sola: **la superficie scrive/calcola su richiesta,
o mostra dati che si aggiornano su schedule?**

| Tipo | Esempi | Casa |
|---|---|---|
| **Scrive / calcola on-demand** | Ingest (intake→promote), update previsione, edit Cassa | **Python · Streamlit · admin privato** |
| **Mostra su schedule** | Home freshness, F&B, Reviews, Mutui | **static-edge · Cloudflare · viewer pubblico** |

Tutto ciò che vede il direttore sta nella riga "static-edge". Tutto ciò che scrive lo fa
solo Stefano. Le due audience si separano lungo questo confine, non solo per permessi.

## Architettura

Tre pezzi. Il flusso è: **BQ (read-only) → JSON → sito statico Cloudflare → direttore.**

### 1. Exporter (`verticals/hub/publish/`)

Script Python che legge BQ (via `core.bq.client.get_client()`, **solo SELECT** sulle viste
canoniche — nessuna scrittura, nessun lineage toccato) e produce un JSON per superficie.

- Riusa le query già esistenti dietro le viste (`v_fb_kpi`, `v_economato_consumi`, freshness
  da `f_ricavi_fb`/`f_reviews`). Non duplica logica di dominio: serializza l'output delle
  viste, niente di nuovo.
- Output: `site/data/<surface>.json` + un `site/data/_meta.json` con `generated_at` e, per
  ogni superficie, la freschezza (giorni dall'ultimo periodo coperto) — così la home statica
  mostra il semaforo senza interrogare BQ.
- Esposto come CLI: `hotelops publish-export` (dry-run stampa i JSON senza scrivere il sito).

### 2. Contratto dati (JSON)

Una superficie = un file JSON con shape stabile e versionata (`"schema": 1`). Il frontend
legge **solo** questi file, mai BQ. Slice 1 definisce due contratti:

- `_meta.json` — `{ schema, generated_at, surfaces: { fb: {giorni, semaforo}, reviews: {...} } }`
- `fb.json` — bridge mensile a 3 bucket (lo stesso contratto onesto di `v_fb_kpi`:
  breakfast / ristorante / bar, food_cost_pct separati, €/pasto), serie per mese + YoY.

Contratti aggiuntivi (reviews, cassa) si aggiungono una superficie alla volta.

### 3. Sito statico + hosting + auth

- **Frontend**: sito statico vanilla sul modello provato di `app-mutui` (`index.html` +
  `css/` + `js/` + `data/*.json`), con i **token Panorama** (gli stessi di
  `verticals/hub/theme.py`: navy/sky/azure/gold/coral/ivory/sand/slate, font
  Cinzel/Cormorant/Jost). Charts client-side (es. Chart.js come mutui). Nessun framework
  pesante finché non serve.
- **Hosting**: Cloudflare (Pages o Worker-assets, stesso account di `mutui-tracker`).
- **Aggiornamento dati**: un **job schedulato** (Cloud Run *job* via Cloud Scheduler —
  *non* always-on, costo trascurabile) esegue `hotelops publish-export` e ridepoloya il
  sito con i JSON freschi. Cadenza notturna (i dati sono a grana ≥ giornaliera).
- **Auth**: **Cloudflare Access** davanti al progetto, gated per email Google (Stefano +
  direttore). I dati finanziari non vanno su URL pubblico non protetto. Mutui, già pubblico
  e non sensibile, resta linkato a parte (o si porta dietro lo stesso Access in seguito).

### Mechanismo di delivery dati — scelta

| Opzione | Come | Quando |
|---|---|---|
| **A — bundle + redeploy** (raccomandato per slice 1) | il job scrive `data/*.json` nel sito e fa `wrangler deploy` | semplice, mutui-like, un solo artefatto versionato |
| B — R2 + fetch | JSON su R2, il sito li fetcha a runtime | quando i dati crescono o si vuole disaccoppiare deploy da refresh |

Si parte con A. B è lo scale-up, non lo si fa finché A non stringe.

## Slice incrementali

Non big-bang. Mutui è già online. Ordine:

1. **Slice 1 — front-door + F&B.** Exporter (`_meta.json` + `fb.json`) + sito statico:
   home landing brandizzata con card e semaforo freshness (da `_meta.json`), card Mutui che
   linka il Worker esistente, pagina F&B che disegna `fb.json`. Deploy manuale (`wrangler`)
   la prima volta. **Questo è ciò che si manda al direttore.**
2. **Slice 2 — automazione refresh.** Cloud Run job + Cloud Scheduler che rigenera e
   ridepoloya notturno. + Cloudflare Access gated per email.
3. **Slice 3+ — Reviews, poi Cassa snapshot.** Una superficie alla volta, stesso pattern.

L'admin Streamlit (`app.py`, con Ingest e le scritture) resta invariato e privato per tutta
la durata. `app_viewer.py` Streamlit diventa ridondante una volta che lo slice 1 copre il
direttore — si rimuove a quel punto, non prima (fallback finché il sito statico non è solido).

## Fit con governance / lineage

L'exporter è **read-only**: SELECT sulle viste, zero INSERT/UPDATE, nessun `f_raw_objects`,
nessuna promozione. Non tocca I1/I9 (non scrive in BQ, non bypassa intake→promote). I JSON
sono un *output di presentazione* derivato, non una fonte: se si perdono, si rigenerano. BQ
resta l'unica source of truth; i JSON sono cache d'edge con `generated_at` esplicito.

## Domande aperte (da chiudere prima dello slice 2)

1. **Dominio**: sottodominio dedicato (es. `hub.panoramagroup.it` / `direzione.…`) o un
   `*.workers.dev` come mutui? (slice 1 può partire su workers.dev, dominio dopo)
2. **Email direttore** per la regola Cloudflare Access.
3. **Account/credenziali Cloudflare** per il deploy automatico dal Cloud Run job (API token).

Nessuna di queste blocca lo slice 1 (deploy manuale su workers.dev, ancora senza Access se
i JSON F&B non sono sensibili oltre il già-condiviso — da confermare con Stefano).
