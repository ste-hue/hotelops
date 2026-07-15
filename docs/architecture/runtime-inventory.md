# HotelOps — As-Built Runtime Inventory

**Generated:** 2026-07-15T08:34:41Z · **Mode:** read-only audit · **Canonical data:** [`runtime-inventory.yaml`](runtime-inventory.yaml) · **Gaps:** [`runtime-audit-gaps.md`](runtime-audit-gaps.md) · **Command log:** [`runtime-audit-commands.md`](runtime-audit-commands.md) · **Diagram:** [`runtime-topology.mmd`](runtime-topology.mmd)

## 1. Executive summary

HotelOps runs on **two clouds under two different personal/organizational accounts**:

- **Google Cloud `hotelops-suite`** (account `stefano@panoramagroup.it`) hosts the single interactive product — **Cloud Run service `hotelops-hub`** (Streamlit app-store, 10+ pages, reads/writes BigQuery) — behind **Google IAP** with a custom OAuth client, plus **4 scheduled Cloud Run Jobs** (reviews ×2, spiaggia-corrispettivi, coperti) triggered by Cloud Scheduler.
- **Cloudflare account `ste.dellapietra@gmail.com`** (ID `8a6fdb9f…`) hosts the satellite apps: Worker **`mutui-tracker`** (public, KV-backed scenario API), Worker **`reception-control-tower`** on **`reception.panorama-host.com`** behind **Cloudflare Access** (team `panoramagroup.cloudflareaccess.com`), Pages project **`finanza`** on `finanzaorti.com` (public), and one **stale, undocumented public Worker named `hotelops-hub`** that still serves the June static launcher despite STATUS.md recording that surface as deleted.

The zone **`panorama-host.com`** exists on Cloudflare with exactly one hostname in use (`reception.`); `bilancini.panorama-host.com` is scaffolded locally but not provisioned. There is **no CI/CD**: every deploy is manual from the laptop (`gcloud run deploy --source`, `wrangler deploy`); GitHub Actions run tests and Claude review only. No Terraform/Pulumi/K8s. R2 is not enabled; one KV namespace and one D1 database exist.

## 2. Audit scope

- Repos inspected: `hotelops` (primary), `app-mutui`/`mutui-tracker`, `panorama_apps/{reception-control-tower,bilancini}`, `investimenti2026`, plus filesystem discovery under `~/dev/Projects`.
- Live systems: `gcloud` (project `hotelops-suite` + light probe of 4 adjacent projects), Cloudflare API via authenticated MCP tools + `wrangler whoami`, and unauthenticated HTTP probes (GET/HEAD only).
- Everything read-only. No resource was created, modified, deleted, or re-configured. No secret values were read into artifacts (names only).
- Not inspected: Cloudflare Zero Trust IdP config, Looker Studio ACLs, ~40 `sys-*` Apps-Script-generated GCP projects, xitnode/exitnode zones (non-Panorama).

## 3. Current architecture overview

```
Users (org + 3 external gmail)
 ├─ IAP (custom OAuth client) ──► Cloud Run hotelops-hub (Streamlit app.py, roles.py grants)
 │                                  └─► BigQuery hotelops · GCS hotelops-raw
 ├─ Cloudflare Access ──► Worker reception-control-tower ─► D1 + Anthropic API
 ├─ (public) ──► Worker mutui-tracker ─► KV SCENARIO_KV   [writes: Bearer token]
 ├─ (public) ──► Pages finanza (finanzaorti.com)
 └─ (public, STALE) ──► Worker "hotelops-hub" (frozen 2026-06-18 launcher)

Cloud Scheduler ──► Cloud Run Jobs (reviews-scrape/-report, spiaggia-corrispettivi, coperti)
                     └─► Drive (drive-audit@) · BigQuery · Gmail/Apify/Anthropic (Secret Manager)
```

## 4. Complete application inventory

| Application | Hostname | Cloudflare Path | Authentication | Cloud Run | Project | Region | Source | Deployment | Status | Confidence |
|---|---|---|---|---|---|---|---|---|---|---|
| HotelOps Hub (Streamlit app-store: cashflow, cassa-consuntivo, bilancini, accodamenti, mutui-embed, revenue, fb, spiaggia, reviews, banche-bind) | `hotelops-hub-942784312622.europe-west1.run.app` (+legacy alias `…lvk3phpq4q-ew.a.run.app`) | none (direct run.app) | IAP + Cloud Run IAM (IAP agent only) + `roles.py` grants | `hotelops-hub` | hotelops-suite | europe-west1 | `hotelops` repo, `Dockerfile` → `verticals/hub/app.py` | manual `gcloud run deploy --source .` | active | high |
| Mutui tracker + Piano Industriale | `mutui-tracker.ste-dellapietra.workers.dev` | Worker + KV | public GET; Bearer `ADMIN_TOKEN` for PUT `/api/scenario` | — | — | CF edge | `~/dev/Projects/app-mutui` (gh: ste-hue/mutui-tracker) | manual `wrangler deploy` | active | high |
| Reception Control Tower (triage AI board) | `reception.panorama-host.com` | Access → Worker (custom domain; workers.dev disabled) | Cloudflare Access (panoramagroup.it + 1 gmail) + in-Worker JWT check | — | — | CF edge | `~/dev/Projects/panorama_apps/reception-control-tower` (**no git remote**) | manual `wrangler deploy` | active | high |
| Finanza (ORTI finance site) | `finanzaorti.com`, `www.` | Pages (CNAME → `finanza-63f.pages.dev`) | none found | — | — | CF edge | gh: ste-hue/finanza@master | Pages GitHub CI (`npm run build`) | active, last deploy 2025-08-07 (stale candidate) | high |
| Static launcher "HotelOps — Direzione" | `hotelops-hub.ste-dellapietra.workers.dev` | Worker (assets) | **none — public** | — | — | CF edge | unconfirmed (inferred `verticals/hub/publish/site` @2026-06-18) | unknown (upload 2026-06-18) | **stale candidate, undocumented** | medium |
| Vetrina (retired launcher) | `hotelops-vetrina.ste-dellapietra.workers.dev` | — (404) | — | — | — | — | `hotelops:verticals/hub/publish/` | `wrangler deploy` (deleted 2026-06-20) | retired | high |
| Bilancini standalone Worker | `bilancini.panorama-host.com` (planned) | planned Access → Worker + KV | planned Access JWT | — | — | — | `~/dev/Projects/panorama_apps/bilancini` (**no git remote**) | not provisioned | source exists, runtime absent | high |
| Reviews pipeline | (no hostname — batch) | — | Cloud Run IAM (scheduler SA invokes) | jobs `reviews-scrape`/`reviews-report` | hotelops-suite | europe-west1 | `hotelops` repo, `Dockerfile.jobs` | `scripts/cloud/*.sh` manual | active | high |
| Spiaggia corrispettivi ingest | (batch) | — | Cloud Run IAM | job `spiaggia-corrispettivi` | hotelops-suite | europe-west1 | `hotelops` repo | manual scripts | active | high |
| Coperti ingest | (batch) | — | Cloud Run IAM | job `coperti` | hotelops-suite | europe-west1 | `hotelops` repo | manual scripts | active | high |
| Banche (Looker Studio) | `datastudio.google.com/...2a7a4c25…` | — | Google account sharing (ACL unknown) | — | — | — | external SaaS (bind tile in registry.py) | n/a | active external | medium |
| Adjacent: investimenti2026 / excelllm / finanza-react-app (Pages), xitnode-newsletter-subscribe (Worker), NanoClaw (WhatsApp agent, runtime unknown) | various `.pages.dev` / workers.dev | Pages/Worker | public / unknown | — | — | CF edge | ste-hue GitHub / local | Pages CI / wrangler / unknown | adjacent | medium |

## 5. Hostname inventory

| Hostname | DNS | Origin | Exposure | Verified |
|---|---|---|---|---|
| `hotelops-hub-942784312622.europe-west1.run.app` (+alias) | Google-managed | Cloud Run `hotelops-hub` | **private** (302→IAP observed) | ✅ |
| `reception.panorama-host.com` | CF AAAA `100::` proxied (Workers custom domain) | Worker `reception-control-tower` | **private** (302→Access login observed) | ✅ |
| `mutui-tracker.ste-dellapietra.workers.dev` | CF workers.dev | Worker + KV | **public** (200 observed, incl. `/api/scenario`) | ✅ |
| `hotelops-hub.ste-dellapietra.workers.dev` | CF workers.dev | stale assets Worker | **public** (200 observed) | ✅ |
| `hotelops-vetrina.ste-dellapietra.workers.dev` | CF workers.dev | none | 404 (retired) | ✅ |
| `finanzaorti.com` / `www.` | CF CNAME → `finanza-63f.pages.dev`, proxied | Pages `finanza` | **public** (200 observed) | ✅ |
| `bilancini.panorama-host.com` | no DNS record | none | not deployed | ✅ (absence) |
| `*.pages.dev` (investimenti2026, excelllm, finanza-react-app) | CF | Pages | public | listed via API, not probed |

`panorama-host.com` zone contains **only** the reception record. `panoramagroup.it` is **not** on this Cloudflare account (consistent with STATUS.md note).

## 6. Cloud Run service inventory

One service. Project `hotelops-suite` (942784312622), region `europe-west1`.

**`hotelops-hub`** — created 2026-06-13, generation 38, revision `hotelops-hub-00037-lck` (deployed 2026-07-14 by stefano@). Image built by Cloud Build from `--source` upload into Artifact Registry `cloud-run-source-deploy/hotelops-hub`. Ingress `all`; **IAP enabled** (`run.googleapis.com/iap-enabled: true`); invoker = **only the IAP service agent** (`service-942784312622@gcp-sa-iap`) — no `allUsers`, no `allAuthenticatedUsers`. SA = **default compute** `942784312622-compute@developer.gserviceaccount.com` (**roles/editor at project level** — see SEC-002). 1 CPU / 1 GiB / concurrency 80 / max 20 instances / timeout 300s / port 8080. No service env vars, no secret refs (BQ/GCS via ADC). No domain mappings. Adjacent projects (`anna-assistant-bot`, `economato-assistant`, `reception-494913`, `mcp-gmail-487209`) have the Cloud Run API disabled → no services there.

## 7. Cloud Run job inventory

All in `hotelops-suite`/`europe-west1`, image `europe-west1-docker.pkg.dev/hotelops-suite/hotelops/jobs:<tag>` (from `Dockerfile.jobs`, built via `scripts/cloud/10_build_image.sh`), triggered by Cloud Scheduler HTTP → Run API authenticated as `hotelops-jobs@`:

| Job | Tag | Command | SA | Secrets (names) | Schedule (Europe/Rome) | Last run |
|---|---|---|---|---|---|---|
| `reviews-scrape` | v1 | `python -m cli reviews --scrape` | hotelops-jobs@ | anthropic-api-key, apify-api-token, gmail-user, gmail-app-password | daily 07:00 | 2026-07-15 ✅ |
| `reviews-report` | v1 | `python -m cli reviews --report` | hotelops-jobs@ | anthropic-api-key, gmail-user, gmail-app-password | Mon 08:00 | 2026-07-13 ✅ |
| `spiaggia-corrispettivi` | v2 | `python -m ingest.drive_fetch --source-name RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT` | drive-audit@ (keyless ADC) | — | daily 09:00 | 2026-07-15 ✅ |
| `coperti` | v3 | `python -m ingest.flussi.ingest_coperti --gsheet --replace` | drive-audit@ | — | daily 12:00 | 2026-07-14 ✅ |

Note: jobs are pinned to image tags v1/v2/v3 — code fixes in the repo do **not** reach jobs until someone rebuilds and re-points the tag (manual, no trigger exists; `gcloud builds triggers list` = 0).

## 8. Cloudflare Worker inventory

| Worker | Route/domain | Bindings | Source | Status |
|---|---|---|---|---|
| `mutui-tracker` | workers.dev (enabled) | KV `SCENARIO_KV`, secret `ADMIN_TOKEN`, ASSETS | `~/dev/Projects/app-mutui` (gh mutui-tracker) | active (mod. 2026-07-14) |
| `reception-control-tower` | custom domain `reception.panorama-host.com`; workers.dev **disabled** | D1 `DB`, secret `ANTHROPIC_API_KEY`, plain `ACCESS_AUD`/`ACCESS_TEAM_DOMAIN`/`MODEL=claude-sonnet-5` | `panorama_apps/reception-control-tower` (local-only git) | active (mod. 2026-07-06) |
| `hotelops-hub` | workers.dev (enabled, **public**) | none | **unconfirmed** | **stale candidate** (frozen 2026-06-18) |
| `xitnode-newsletter-subscribe` | not inspected | — | `~/dev/Projects/xitnode/worker` | adjacent, non-Panorama |

## 9. Cloudflare storage inventory

- **KV:** 1 namespace — `SCENARIO_KV` (`34daf373…`), bound to mutui-tracker. The `bilancini` scaffold expects a future `CONTENT` namespace (not created).
- **D1:** 1 database — `reception-control-tower` (`4fbfc3b6…`), ~623 KB; API reports 0 tables (metadata oddity, not queried further).
- **R2:** not enabled on the account (API error 10042) → zero buckets.
- **Pages:** `finanza` (→ finanzaorti.com), `investimenti2026`, `excelllm`, `finanza-react-app` (all `.pages.dev`, GitHub-integrated except finanza-react-app = direct upload).

## 10. Authentication matrix

| Hostname | Cloudflare Access | Worker Auth | Cloud Run IAM | Google IAP | App Auth | Effective Exposure | Confidence |
|---|---|---|---|---|---|---|---|
| hub run.app URLs | — | — | invoker = IAP agent only | ✅ allowlist: `domain:panoramagroup.it` + stefano@ + ste.dellapietra@ + stedepi@; custom OAuth client | `roles.py` per-email grants, fail-closed | **private origin** | high |
| reception.panorama-host.com | ✅ allow panoramagroup.it + ste.dellapietra@ (730h session) | ✅ Access JWT verified in Worker | n/a | n/a | JWT-derived identity | **private origin** | high |
| mutui-tracker.workers.dev | — | writes only (Bearer ADMIN_TOKEN) | n/a | n/a | none for reads | **public** | high |
| hotelops-hub.workers.dev | — | — | n/a | n/a | — | **public (stale)** | high |
| finanzaorti.com | — | n/a | n/a | n/a | unknown | **public** | high |

These layers are distinct and were verified independently: IAP ≠ Cloud Run IAM (both checked); Cloudflare Access ≠ Worker JWT check (both present on reception); the hub's `roles.py` is a third, app-level layer on top of IAP.

## 11. Source-to-runtime mapping

| Runtime | Repo | Entrypoint | Build | Status |
|---|---|---|---|---|
| Cloud Run `hotelops-hub` | ste-hue/hotelops @ main | `verticals/hub/app.py` via root `Dockerfile` | Cloud Build (source deploy) | active |
| Cloud Run jobs ×4 | ste-hue/hotelops | `cli.py` / `ingest.*` via `Dockerfile.jobs` | `gcloud builds submit` | active |
| Worker `mutui-tracker` | ste-hue/mutui-tracker (local: app-mutui) | `src/worker.js` | none | active |
| Worker `reception-control-tower` | **local-only** `panorama_apps/reception-control-tower` | `src/index.js` | none | active |
| Worker `hotelops-hub` | unconfirmed | assets only | — | deployed but source unclear |
| Worker `bilancini` | **local-only** `panorama_apps/bilancini` | `src/index.js` | — | source exists, runtime unclear (planned) |
| Pages `finanza` | ste-hue/finanza@master (no local checkout found) | `npm run build` | Pages CI | active, stale content candidate |
| `verticals/condges/Dockerfile` | hotelops | `condges/app.py` (path doesn't exist at repo root) | — | dead-code candidate |
| `verticals/hub/publish/` (vetrina) | hotelops | assets | wrangler | retired runtime; source still in repo |
| NanoClaw | ste-hue/nanoclaw | — | — | runtime unknown |

## 12. Deployment-path mapping

| Runtime Component | Source Path | Build Method | Deployment Workflow | Destination | Last Known Deployment | Confidence |
|---|---|---|---|---|---|---|
| hotelops-hub (Cloud Run) | hotelops repo root | Dockerfile via Cloud Build | manual `gcloud run deploy --source .` from laptop | hotelops-suite / europe-west1 | 2026-07-14 17:44 UTC (rev 00037) | high |
| jobs image | hotelops repo | `Dockerfile.jobs` via `gcloud builds submit` | `scripts/cloud/10_build_image.sh` then re-point jobs | Artifact Registry `hotelops/jobs` | ≤2026-06-30 (tags v1–v3) | high |
| mutui-tracker | app-mutui | none | `npx wrangler deploy` | CF Worker | 2026-07-14 17:36 UTC | high |
| reception-control-tower | panorama_apps/… | none | `npx wrangler deploy` | CF Worker + custom domain | 2026-07-06 | high |
| hotelops-hub Worker | ? | ? | unknown (`triggered_by: upload`) | CF Worker | 2026-06-18 | low |
| finanza | gh ste-hue/finanza | `npm run build` | Pages GitHub integration | finanzaorti.com | 2025-08-07 | high |
| GitHub Actions (`test.yml`, `claude*.yml`) | hotelops | — | CI only — **no deploy workflow exists anywhere** | — | — | high |

## 13. Data-service dependencies

- **BigQuery** `hotelops-suite.hotelops` — read/write from hub (ADC as default compute SA) and jobs (hotelops-jobs@/drive-audit@: `bigquery.dataEditor` + `jobUser` at project level). Sole write gate in code: `core/bq/write.py::bq_write_validated`.
- **GCS** — `hotelops-raw`, `hotelops-raw-prod` (lineage raw objects, Object Versioning), `run-sources-*` + `*_cloudbuild` (deploy plumbing), `panorama-gws-takeout-20260506` (archive).
- **Google Drive/Sheets** — jobs run as `drive-audit@` (keyless ADC); workspace layer uses key files `~/.config/hotelops/{drive-audit-key,workspace-controller}.json` with domain-wide delegation (Gmail/Drive impersonation).
- **Secret Manager** — `anthropic-api-key`, `apify-api-token`, `gmail-user`, `gmail-app-password` (names only; injected into reviews jobs).
- **Cloudflare KV/D1** — SCENARIO_KV (mutui scenario), D1 reception-control-tower.
- **External APIs** — Anthropic (reviews NLP; reception triage `claude-sonnet-5`), Apify (scraping), Gmail SMTP (alerts), Looker Studio (Banche dashboard).

## 14. Unknowns and blind spots

See [`runtime-audit-gaps.md`](runtime-audit-gaps.md) — headline items: provenance of the stale `hotelops-hub` Worker (GAP-001); Zero Trust IdP configuration for `panoramagroup.cloudflareaccess.com` (GAP-002); Looker Studio ACL (GAP-005); NanoClaw runtime (GAP-006); intent of the bilancini Worker vs the hub Bilancini page (GAP-004); finanzaorti.com content sensitivity (GAP-003); ~40 `sys-*` GCP projects not enumerated (GAP-007).

## 15. Security observations

Ranked (details + evidence in YAML `security_observations`):

1. **SEC-002 (high)** — hub Cloud Run runs as default compute SA with project `roles/editor`; the hub is a write surface reachable by the whole `panoramagroup.it` domain via IAP.
2. **SEC-001 (medium)** — undocumented public Worker `hotelops-hub` serving the frozen June launcher; contradicts STATUS.md which records that surface as deleted.
3. **SEC-003 (medium)** — `mutui-tracker` exposes group debt/amortization data and the industrial-plan scenario to anyone with the URL (reads unauthenticated by design; writes token-gated).
4. **SEC-005 (medium)** — `reception-control-tower` and `bilancini` sources exist only on the laptop (git repos without remotes).
5. **SEC-006 (medium)** — plaintext credentials on the dev machine (`.env`, SA key files, `.dev.vars`) — all untracked/gitignored; **no committed secrets found in tracked files**.
6. **SEC-004 (low)** — IAP allowlist is domain-wide, broader than the per-email model documented in the hub README (mitigated by fail-closed `roles.py`).
7. **SEC-007 (low)** — broad project-level roles for job SAs; `drive-audit@` also holds `iam.serviceAccountTokenCreator`.
8. **SEC-008 (info)** — repo still contains deploy config for the retired vetrina Worker (accidental-redeploy footgun) and legacy URLs.
9. **SEC-009 (low)** — 730h Cloudflare Access sessions on reception.

## 16. Duplicate, stale, or dead-resource candidates

| Item | Class | Evidence |
|---|---|---|
| Worker `hotelops-hub` | stale candidate (live but frozen 2026-06-18, believed deleted) | curl 200; STATUS.md contradiction |
| `verticals/hub/publish/` + `hotelops-vetrina` refs | retired runtime, source remains | wrangler.toml, apps.json, 404 |
| `verticals/condges/Dockerfile` | dead-code candidate (copies `condges/` path that doesn't exist at build ctx root) | file content vs tree |
| Pages `finanza-react-app` | duplicate/stale candidate of `finanza` | direct upload, last deploy 2025-08-04 |
| Pages `finanza` content | stale candidate (last deploy 2025-08-07) | Pages API |
| `~/dev/Projects/finanza/app-mutui` | superseded copy (older remote ste-hue/app-mutui) | diff vs app-mutui |
| `.venv` in hotelops repo | orphan (documented in hub README) | README §Dev locale |
| `panorama_apps/reception` (Python project) | predecessor of control tower — runtime unknown | dir listing |

None of these were modified or deleted (read-only audit).

## 17. Audit limitations

- Wrangler token scopes (no Access-token for Zero Trust org settings): Access **apps/policies** were readable, IdP/team config was not attempted beyond that.
- `workers_get_worker_code` MCP tool failed on the assets-only Worker (schema error); code retrieval via raw API returned empty (assets-only) — content inferred from served HTML.
- Looker Studio, Streamlit-internal behavior, and BigQuery dataset ACLs were not enumerated.
- Adjacent GCP projects: only Cloud Run API state checked (disabled ⇒ conclusive for Cloud Run, not for other services).
- Live probes were unauthenticated GETs; no authenticated crawling of protected surfaces.
- Everything dated: this is a snapshot at 2026-07-15; manual deploy culture means drift is fast.
