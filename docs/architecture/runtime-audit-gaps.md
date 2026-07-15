# Runtime audit — unresolved gaps (2026-07-15)

Companion to `runtime-inventory.{yaml,md}`. Each gap states what is unknown, what
evidence exists, and how to close it **safely** (read-only or dashboard-view).

## GAP-001 — Provenance of the live public Worker `hotelops-hub`
**Question:**
Who/what deployed the Worker `hotelops-hub` on 2026-06-18, from which exact source snapshot, and is it intentionally still live?
**Known evidence:**
- Deployed 2026-06-18T09:14Z, never modified; annotation `workers/triggered_by: upload`; no bindings.
- Serves HTML titled "Panorama · HotelOps — Direzione" + `/data/_meta.json` with `generated_at: 2026-06-18` — matches the static-edge/vetrina family in `verticals/hub/publish/site`.
- STATUS.md records a redundant "hub" Worker deleted 2026-06-16 and `hotelops-vetrina` deleted 2026-06-20; neither entry mentions this Worker.
- No local wrangler config with `name = "hotelops-hub"` exists (repo config says `hotelops-vetrina`).
**Missing evidence:**
- Worker deployment/version history (API `GET /accounts/{id}/workers/scripts/hotelops-hub/versions` or dashboard → Workers → Deployments).
- A diff of served assets vs repo `verticals/hub/publish/site` at commit of 2026-06-18.
**Confidence:** Medium (identity of content), Low (provenance).
**How to resolve safely:**
- Read the Worker's version list via API/dashboard; `git log --until=2026-06-19 -- verticals/hub/publish` and compare file hashes with fetched assets.
**Operational consequence:**
- A public, unowned surface with org branding; if forgotten it will drift further and could be mistaken for the real hub. Decision needed (delete vs document) — out of scope for this audit.

## GAP-002 — Cloudflare Zero Trust org configuration
**Question:**
Which identity providers, session policies, and other Access settings exist on team `panoramagroup.cloudflareaccess.com`? Are there Access apps or service tokens beyond "Reception Control Tower"?
**Known evidence:**
- `GET /access/apps` returned exactly one app with one allow policy (panoramagroup.it domain + ste.dellapietra@gmail.com), session 730h.
**Missing evidence:**
- IdP list (`/access/identity_providers`), service tokens, groups, team-level settings — not queried (wrangler OAuth token scope uncertainty; avoided speculative calls).
**Confidence:** Medium.
**How to resolve safely:**
- Zero Trust dashboard (read) or API `GET /accounts/{id}/access/identity_providers` and `/access/service_tokens` with a scoped read token.
**Operational consequence:**
- Login method (Google OAuth vs one-time PIN) determines the real strength of the reception gate; a One-Time-PIN IdP would make the email allowlist the only control.

## GAP-003 — `finanzaorti.com` content and sensitivity
**Question:**
What does the public `finanza` Pages site expose, and is its public exposure intended? Is it still in use (last deploy 2025-08-07)?
**Known evidence:**
- CNAME apex+www → finanza-63f.pages.dev, proxied, 200 public, GitHub source ste-hue/finanza@master, build `npm run build`. No local checkout found.
**Missing evidence:**
- Site content review; the GitHub repo itself; whether it embeds ORTI financial data.
**Confidence:** Low.
**How to resolve safely:**
- Browse the site; `gh repo view ste-hue/finanza` (read).
**Operational consequence:**
- The name suggests ORTI finance content on a public domain; if real numbers are published this is a data-exposure question, if dead it's a takedown candidate.

## GAP-004 — Intent of the `bilancini` Worker vs the hub Bilancini page
**Question:**
Is `panorama_apps/bilancini` (planned `bilancini.panorama-host.com`, KV `CONTENT`, Access JWT) meant to replace, mirror, or complement the live `bilancini` page inside the Streamlit hub (merged 2026-07-13/14)?
**Known evidence:**
- Scaffold committed ("porting reception-control-tower"), placeholders `REPLACE_AT_PROVISIONING`; no worker, no DNS record, no KV namespace named CONTENT.
- Hub page `verticals/hub/pages_/bilancini.py` is live, sensitive=True, granted to Rosa/gm.
**Missing evidence:**
- Any spec/decision doc linking the two (none found in hotelops repo or panorama_apps/STATUS.md — the latter was not read in full).
**Confidence:** Medium.
**How to resolve safely:**
- Read `panorama_apps/STATUS.md` and bilancini/README; ask the owner.
**Operational consequence:**
- Two parallel "Bilancini" surfaces with different auth models (IAP+grants vs Access) would fragment the access story for the same sensitive data.

## GAP-005 — Looker Studio "Banche" report ACL
**Question:**
Who can open the Looker Studio report the hub's "Banche" tile links to, and what BigQuery credentials does it use?
**Known evidence:**
- URL hardcoded in `verticals/hub/registry.py` (`_BANCHE_LOOKER`); tile visible to FINANZA grantees.
**Missing evidence:**
- Report sharing settings and data-source credential mode (owner's vs viewer's) — not inspectable via CLI.
**Confidence:** Low.
**How to resolve safely:**
- Open report → Share dialog (read); check data source credential setting.
**Operational consequence:**
- If shared "anyone with the link" with owner's credentials, bank movement data bypasses every auth layer documented here.

## GAP-006 — NanoClaw runtime location
**Question:**
Where does the NanoClaw WhatsApp agent actually run (laptop, container host, cloud?), and with which credentials does it reach hotelops ingest?
**Known evidence:**
- CLAUDE.md documents it as query+ingest channel using `ingest/classify.py`; repo `ste-hue/nanoclaw` exists locally with a `container/` directory. Not on Cloud Run `hotelops-suite`; not a CF Worker.
**Missing evidence:**
- Its deployment/config (`groups/hotelops/` config in that repo not inspected).
**Confidence:** Low.
**How to resolve safely:**
- Read nanoclaw repo config; `docker ps` on the machine that hosts it.
**Operational consequence:**
- An ingest-capable channel outside this inventory is an unaudited write path toward BigQuery.

## GAP-007 — Unenumerated GCP projects
**Question:**
Do any of the ~40 `sys-*` (Apps Script) projects or the 4 named adjacent projects (anna-assistant-bot, economato-assistant, reception-494913, mcp-gmail-487209) host Panorama-relevant runtimes beyond Cloud Run?
**Known evidence:**
- Cloud Run API disabled on all 4 named projects (conclusive: no Cloud Run). `sys-*` projects are Apps-Script-bound by naming.
**Missing evidence:**
- Other services (App Engine, Functions, GCE) in those projects; Apps Script attachments (e.g. "Gestione Servizi 2025", "transfers2026" clearly exist as scripts).
**Confidence:** Medium (low risk of hidden HTTP runtimes).
**How to resolve safely:**
- `gcloud services list --enabled --project=<id>` per project; Apps Script dashboard.
**Operational consequence:**
- Sheet-bound scripts may write to operational spreadsheets that hotelops later ingests — an invisible upstream dependency.

## GAP-008 — D1 `reception-control-tower` schema
**Question:**
Why does the D1 API report `num_tables: 0` while `file_size` ≈ 623 KB, and what does the database actually contain?
**Known evidence:**
- `d1_databases_list` output; worker binds it as `DB` with `migrations_dir: migrations`.
**Missing evidence:**
- Table list (a read `PRAGMA table_list` query was deliberately not run — write-adjacent tooling avoided).
**Confidence:** Low.
**How to resolve safely:**
- `wrangler d1 execute reception-control-tower --remote --command "SELECT name FROM sqlite_master WHERE type='table'"` (read-only SELECT), or dashboard.
**Operational consequence:**
- If migrations never ran in production, the board may be storing data somewhere unexpected (or the metadata is simply lagging).

## GAP-009 — `verticals/condges/Dockerfile` target
**Question:**
Is the condges standalone Dockerfile (entrypoint `condges/app.py`, path that doesn't exist at repo root) referenced by anything, or dead?
**Known evidence:**
- No Cloud Run service/job uses it; no build script references it; path layout predates `verticals/` move.
**Missing evidence:**
- Historical intent (git log of that file not reviewed).
**Confidence:** Medium (dead-code candidate).
**How to resolve safely:**
- `git log --follow verticals/condges/Dockerfile`.
**Operational consequence:**
- Only repo hygiene; misleading for future operators.

## GAP-010 — Secret rotation / ownership of `ADMIN_TOKEN` (mutui-tracker)
**Question:**
Who holds the mutui-tracker `ADMIN_TOKEN`, when was it set, and is there a rotation story?
**Known evidence:**
- Secret binding exists on the Worker; a `.dev.vars` file with the same variable name exists locally (value not read).
**Missing evidence:**
- Rotation history (not exposed by API), holder list.
**Confidence:** Low.
**How to resolve safely:**
- Owner interview; `wrangler secret list` per worker (names/dates only).
**Operational consequence:**
- The token is the only write gate on the shared industrial-plan scenario.
