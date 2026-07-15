# Runtime audit — command log (2026-07-15, read-only)

Every command executed during the audit, why, outcome, and a sanitized summary.
No tokens, secret values, or credential payloads appear here. No state-changing
command was run; two `gcloud run services list` calls on API-disabled projects
prompted "enable and retry (y/N)?" and were **declined automatically** (non-interactive
default N → error), enabling nothing.

## Phase 1 — Repository inspection (hotelops + sibling repos)

| # | Command | Why | Outcome |
|---|---|---|---|
| 1 | `git remote -v; git status --short; git branch --show-current; git log -n 15 --oneline` | Repo identity | ✅ `ste-hue/hotelops`, branch main, clean except untracked `scratchpad/` |
| 2 | `find . … Dockerfile*/docker-compose*/cloudbuild*/wrangler*/…` + `ls .github/workflows` | Locate infra files | ✅ `Dockerfile`, `Dockerfile.jobs`, `verticals/condges/Dockerfile`, `verticals/hub/publish/wrangler.toml`; workflows: test.yml, claude.yml, claude-code-review.yml. No Terraform/Pulumi/K8s/compose |
| 3 | `cat` the 3 Dockerfiles + wrangler.toml | Runtime + deploy evidence | ✅ hub Streamlit (port 8080, IAP noted), jobs batch image, vetrina assets-only Worker |
| 4 | `grep -rniE "gcloud run deploy\|gcloud builds submit\|gcloud scheduler\|run jobs (create…)"` | Deploy commands in repo | ✅ CLAUDE.md, hub README, `scripts/cloud/*.sh`, cutover plan doc |
| 5 | `grep -rniE "panoramahost\|panoramagroup\|workers.dev\|cloudflare\|run.app"` (file list) | Domain/CF evidence | ✅ 40 files listed |
| 6 | `cat verticals/hub/README.md scripts/cloud/*.sh` | Deploy + access model | ✅ IAP 2-level model, custom OAuth client note, 6 cloud scripts (bootstrap/build/4 jobs/alerts) |
| 7 | `cat .github/workflows/*.yml` | CI/CD check | ✅ tests + Claude bots only; **no deploy workflow** |
| 8 | `ls verticals/hub/…; grep IAP/roles in hub *.py` | Auth code | ✅ `roles.py` reads `X-Goog-Authenticated-User-Email` / `Cf-Access-Authenticated-User-Email` |
| 9 | `cat verticals/hub/registry.py verticals/hub/roles.py` | App registry + grants | ✅ 12 apps, grants map, S1/S2 invariants |
| 10 | `cat docs/architecture/SYSTEM_MAP.md; head publish/export.py; cat meta/skills/hub-bind/SKILL.md` | Architecture docs | ✅ |
| 11 | `grep -oE "https?://…(workers.dev\|run.app\|pages.dev)\|panoramahost"` | Hostname extraction | ✅ 2 run.app aliases, mutui-tracker workers.dev; **no panorama-host.com in repo** |
| 12 | `sed/cat pages_/mutui.py, publish/site/apps.json; ls site/` | Embed + manifest | ✅ mutui iframe URL, stale apps.json |
| 13 | `grep STATUS.md (mutui/vetrina/cloudflare/worker)`; `ls -a`; `find .env*/credentials` | History + secret files | ✅ vetrina retired 06-20, app-mutui repo, hub Worker "deleted" 06-16 claim, IAP gmail fix 07-13; `.env` present (untracked) |
| 14 | `grep -oE '^[A-Z_]*=' .env \| tr -d '='` | Env var **names only** | ✅ APIFY_API_TOKEN, ANTHROPIC_API_KEY, GMAIL_USER, GMAIL_APP_PASSWORD (values never read) |
| 15 | `ls ~/dev/Projects; find *mutui*` | Locate sibling repos | ✅ app-mutui, finanza/app-mutui, panorama_apps, investimenti2026, … |
| 16 | `grep vetrina/static-edge docs for worker/route/access` | CF design history | ✅ account = ste.dellapietra@gmail.com; Access planned, deploy manual |
| 17 | `app-mutui: git remote/log; cat wrangler.jsonc`; diff vs finanza/app-mutui | Worker source | ✅ ste-hue/mutui-tracker; KV SCENARIO_KV; older copy superseded |
| 18 | `grep '^VAR=' app-mutui/.dev.vars; grep auth src/worker.js; head worker.js` | Worker auth (names only) | ✅ ADMIN_TOKEN (name only); Bearer + SHA-256 timing-safe compare |
| 19 | `head workspace/auth.py; grep publish-export cli.py; grep SA refs` | Workspace auth layer | ✅ domain-wide delegation via `workspace-controller.json`; drive key path |
| 20 | `grep SA_KEY_PATH workspace/config.py` | Key file path | ✅ `~/.config/hotelops/workspace-controller.json` |
| 21 | `cd panorama_apps/*; git remote/log; cat wrangler configs` (reception, bilancini, investimenti2026, finanza) | Worker sources | ✅ reception matches deployed worker; bilancini scaffold; **both without git remote**; finanza dir not a git repo |
| 22 | `cd panorama_apps; git remote` + `ls`; `bilancini git remote`; `ls panorama_apps/reception`; `ls nanoclaw` | Repo boundaries | ✅ panorama_apps not a repo; each app own local git; nanoclaw = gh ste-hue/nanoclaw |

## Phase 2 — Google Cloud (all read-only)

| # | Command | Why | Outcome |
|---|---|---|---|
| 23 | `gcloud auth list; gcloud config list` | Auth context (unchanged) | ✅ active stefano@panoramagroup.it, project hotelops-suite |
| 24 | `gcloud projects list` | Project inventory | ✅ hotelops-suite + 4 named projects + ~40 `sys-*` (Apps Script) |
| 25 | `gcloud run services list / jobs list --project=hotelops-suite` | Runtime inventory | ✅ 1 service, 4 jobs |
| 26 | same lists on anna-assistant-bot / economato-assistant / reception-494913 / mcp-gmail-487209 | Rule out other Cloud Run | ⚠️ Cloud Run API **disabled** on all 4 (enable prompt declined; nothing enabled) → no Cloud Run there |
| 27 | `gcloud run services describe hotelops-hub --format=yaml` | Service detail | ✅ IAP enabled, ingress all, default compute SA, rev 00037, 2 URLs |
| 28 | `gcloud run services get-iam-policy hotelops-hub` | Invoker policy | ✅ only IAP service agent; no allUsers/allAuthenticatedUsers |
| 29 | `gcloud beta run domain-mappings list` | Custom domains | ✅ 0 items |
| 30 | `gcloud run jobs describe ×4 (yaml + json/jq for command/args)` | Job details | ✅ images v1/v2/v3, SAs, secret names, commands |
| 31 | `gcloud scheduler jobs list --location=europe-west1` | Triggers | ✅ 4 enabled HTTP schedulers |
| 32 | `gcloud artifacts repositories list` | Images | ✅ `cloud-run-source-deploy`, `hotelops` |
| 33 | `gcloud builds triggers list (europe-west1 + global)` | CI triggers | ✅ 0 — deploys are manual |
| 34 | `gcloud projects get-iam-policy … \| jq (filter 3 SAs)` | SA roles | ✅ default compute = roles/editor; job SAs project-level BQ/GCS roles; drive-audit has tokenCreator |
| 35 | `gcloud iap settings get (cloud-run/hotelops-hub)` | IAP OAuth config | ✅ custom clientId set (client secret NOT retrieved; only its hash is returned by API and it was not recorded) |
| 36 | `gcloud iap web get-iam-policy` | IAP allowlist | ✅ domain:panoramagroup.it + 3 users |
| 37 | `gcloud storage ls --project=hotelops-suite` | Buckets | ✅ hotelops-raw, hotelops-raw-prod, cloudbuild, run-sources, takeout archive |

## Phase 3 — Cloudflare (read-only)

| # | Command / tool | Why | Outcome |
|---|---|---|---|
| 38 | `wrangler --version; wrangler whoami` | Account context | ✅ 4.42.0; OAuth ste.dellapietra@gmail.com; account 8a6fdb9f…; scopes listed |
| 39 | MCP `workers_list` | Deployed Workers | ✅ 4: reception-control-tower, hotelops-hub, mutui-tracker, xitnode-newsletter-subscribe |
| 40 | MCP `kv_namespaces_list` | KV | ✅ 1 (SCENARIO_KV) |
| 41 | MCP `d1_databases_list` | D1 | ✅ 1 (reception-control-tower) |
| 42 | MCP `r2_buckets_list` | R2 | ⚠️ 403 code 10042 — R2 not enabled ⇒ 0 buckets |
| 43 | CF API: `GET /zones`, `/workers/subdomain`, `/workers/domains`, per-worker `/settings` + `/subdomain` | Zones, custom domains, bindings | ✅ 4 zones incl. panorama-host.com; custom domain reception.panorama-host.com→reception-control-tower; bindings per worker (secret names only) |
| 44 | MCP `workers_get_worker_code hotelops-hub` | Identify mystery worker | ❌ MCP schema error (assets-only worker) — recorded as tool failure |
| 45 | CF API: DNS records for panorama-host.com + finanzaorti.com; zone worker routes; `GET /access/apps` | DNS + Access | ✅ 1 record on panorama-host, 2 CNAME on finanzaorti; 0 zone routes; 1 Access app |
| 46 | CF API: Access app policies; Pages projects list + details | Access policy, Pages sources | ✅ allow panoramagroup.it + 1 gmail; 4 Pages projects with GitHub sources |
| 47 | CF API: `GET /workers/scripts/hotelops-hub` (code) | Worker body | ✅ empty script body (assets-only) — content inferred from HTTP |

## Phase 4 — Live probes (unauthenticated GET/HEAD, no writes)

| # | Command | Why | Outcome |
|---|---|---|---|
| 48 | `curl -s -o /dev/null -w "%{http_code} %{redirect_url}"` on both hub run.app URLs | Verify IAP at edge | ✅ 302 → accounts.google.com via iap.googleapis.com (custom client) |
| 49 | same on mutui-tracker `/` and `/api/scenario` | Verify public exposure | ✅ 200 / 200 (unauthenticated) |
| 50 | same on hotelops-vetrina.workers.dev | Verify retirement | ✅ 404 |
| 51 | `curl` hotelops-hub.workers.dev `/`, `/apps.json`, `/data/_meta.json` | Characterize stale worker | ✅ 200 launcher HTML ("Panorama · HotelOps — Direzione"); /apps.json 404; `_meta.json` 200 with `generated_at: 2026-06-18` |
| 52 | `curl` reception.panorama-host.com | Verify Access at edge | ✅ 302 → panoramagroup.cloudflareaccess.com login |
| 53 | `curl` finanzaorti.com | Verify Pages exposure | ✅ 200 public |
| 54 | `date -u` | Timestamp artifacts | ✅ |

## Phase 5 — Artifact validation

| # | Command | Why | Outcome |
|---|---|---|---|
| 55 | `python … yaml.safe_load(runtime-inventory.yaml)` | YAML validity | ✅ (see final validation) |
| 56 | `grep` artifacts for secret-shaped strings | No-secrets check | ✅ none found |

**Failures / access gaps encountered:** Cloud Run API disabled on 4 adjacent projects (conclusive for Cloud Run absence); MCP `workers_get_worker_code` schema error; R2 not enabled (403). No permission denials on hotelops-suite or the Cloudflare account.
