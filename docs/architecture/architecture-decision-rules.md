# HotelOps — Architecture Decision Rules

**Date:** 2026-07-15. Concise defaults for future infrastructure decisions. Each rule: default, exceptions, prohibitions, required records. "Inventory" = `docs/architecture/runtime-inventory.yaml`. When a rule and reality diverge, either fix reality or amend the rule in the same PR — never let them drift silently.

## Rule: Use Cloud Run for substantial dynamic applications
**Default:** Any interactive, Python, or BigQuery-backed application runs on Cloud Run — and, before that, as a **page inside the existing hub** unless isolation is genuinely needed.
**Use an alternative when:** the app is JS-native, self-contained, ≲ a few hundred lines, touches no BigQuery, and benefits from edge execution, a custom domain, or Access-gating → Worker (reception pattern).
**Do not use it when:** the "app" is a static artifact (→ Pages/assets Worker) or a batch process (→ Job).
**Required records:** inventory row (service, SA, hostname, auth), registry row + grants if staff-facing, deploy workflow.

## Rule: Service vs Job
**Default:** No inbound HTTP need → **Cloud Run Job** (+ Scheduler if recurring). HTTP need → service.
**Use an alternative when:** an existing service can absorb the behavior as an endpoint at no isolation cost.
**Do not:** run batch work inside the hub's request path, or keep a service warm just to be invoked on a schedule.
**Required records:** inventory row (job, SA, secrets by name, schedule, source args), alert coverage confirmation.

## Rule: New Google Cloud project
**Default:** don't. HotelOps lives in `hotelops-suite`.
**Create one only when:** a new *product* needs a distinct security blast radius, distinct billing owner, or third-party access isolation.
**Do not:** create projects per app, per environment, or per experiment (experiments: use folders/labels or personal projects clearly named).
**Required records:** inventory `accounts/projects` entry with purpose + owner; otherwise the project is presumed abandoned by the next audit.

## Rule: New Cloudflare Worker
**Default:** don't — prefer a hub page or Pages.
**Create one only when:** the Cloud-Run-alternative test in Rule 1 passes, **and** you commit to the satellite template: own repo **with a GitHub remote**, `wrangler.jsonc` in-repo, custom domain on `panorama-host.com`, Access app, in-Worker JWT verification, `workers_dev = false`, CI deploy, inventory row.
**Do not:** deploy Workers ad-hoc from the CLI without a repo remote and inventory row — this is exactly how the orphan `hotelops-hub` Worker happened.
**Required records:** all of the above; deletion of a Worker also requires an inventory status change (→ retired), never a silent `wrangler delete`.

## Rule: New KV namespace
**Default:** don't. KV is for (a) pipeline-published derived documents and (b) small shared state (≤ tens of KB) with a single admin writer.
**Use an alternative when:** data is canonical/analytical (→ BigQuery), relational (→ D1 per its rule), or an object/file (→ GCS).
**Do not:** treat KV as a system of record without a scheduled export; never hand-edit KV values outside the owning pipeline.
**Required records:** inventory row (namespace, writer, backup ritual).

## Rule: D1 and R2
**Default:** **D1** only for Worker-local relational state where the Worker is the sole reader/writer (reception is the only sanctioned case). **R2: not currently justified** — it stays disabled; object storage is GCS.
**Use an alternative when:** any GCP workload needs the data too → BigQuery/GCS from the start.
**Do not:** replicate BigQuery facts into D1/KV "for convenience" — publish derived read-only documents instead.
**Required records:** inventory row; for D1, migrations directory in the repo and a note on backup/export.

## Rule: Creating a hostname
**Default:** `<app>.panorama-host.com`, production only, one DNS record = one inventory row = one auth model. Satellites always; the hub keeps its run.app URL as the single documented exception.
**Use an alternative when:** a public brochure site owns its own zone (finanzaorti.com class) — still one inventory row.
**Do not:** circulate `workers.dev` URLs for staff apps; do not create staging/dev hostnames (use revision tags / Worker previews).
**Required records:** inventory row before the record exists; retirement flips the row to `retired` and removes repo references in the same PR.

## Rule: Exposing a service publicly
**Default:** nothing staff-built is public.
**Exception path:** a written decision record (vault/ADR) naming the data exposed, the reason, and the owner — *then* the inventory row says `effective_exposure: public (by decision <ref>)`.
**Do not:** let exposure happen by default (mutui-tracker is the cautionary example — public by inertia, not decision).
**Required records:** decision record + inventory row; quarterly audit re-checks every public surface against its record.

## Rule: Protecting a Cloud Run origin
**Default:** private. Human-facing → IAP enabled + invoker = IAP service agent **only**. Service-to-service → invoker = calling SA (ID tokens).
**Do not:** grant `allUsers`/`allAuthenticatedUsers` invoker; do not rely on an edge proxy for origin protection; do not disable the post-deploy 302 check (it belongs in uptime monitoring — HAR-07).
**Required records:** inventory `public_invoker: false` + IAM member list.

## Rule: Creating a service account
**Default:** one SA per runtime identity (per service / per job family), named for its function, granted the narrowest roles that work (dataset/bucket scope preferred over project scope).
**Use an alternative when:** two workloads are genuinely the same trust domain (the 4 jobs legitimately share two SAs by data-access pattern).
**Do not:** reuse the default compute SA for anything new; do not mint SA JSON keys (WIF for CI, ADC/impersonation locally) — every key that must exist goes on a documented exception list.
**Required records:** inventory entry (SA, roles, used-by); annual scope review.

## Rule: Storing a secret
**Default:** GCP workloads → Secret Manager (referenced by name at deploy). Workers → Cloudflare secret bindings. CI → GitHub Actions secrets. Local dev → `.env`/`.dev.vars`, gitignored, values never in git or in docs.
**Do not:** put secrets in scripts, wrangler `vars`, container images, or KV; never echo values into logs or artifacts.
**Required records:** secret *names* in the inventory; rotation owner + date for long-lived tokens (e.g. mutui `ADMIN_TOKEN`).

## Rule: Adding application roles / grants
**Default:** authorization lives in versioned application code — `roles.py` for hub apps (S1: sensitive apps granted by name, never via group constants; S2: fail-closed). Satellites derive capability from the verified Access JWT email using the same email vocabulary.
**Do not:** encode who-sees-what in Cloudflare Access policies (Access = who enters the plane) or in IAP allowlists; do not invent per-app role vocabularies.
**Required records:** grants change = PR (it already is); README grants table kept in sync (CLA-08 lesson).

## Rule: Introducing infrastructure as code
**Default:** not yet. The declarative record is `runtime-inventory.yaml`; repeatable provisioning lives in idempotent `scripts/cloud/*.sh`; drift is caught by the quarterly read-only audit.
**Adopt Terraform (Cloudflare zone first) when:** Access apps + DNS records exceed ~10, a second operator joins, or a rebuild drill fails its time budget.
**Do not:** adopt IaC to "look mature" or to learn it in production.
**Required records:** if adopted, state backend + ownership documented before the first `apply`.

## Rule: Adding a new environment
**Default:** don't. local + production, with Cloud Run revision-tag canaries and Worker preview versions as the middle ground.
**Add staging only when:** a change class repeatedly causes production incidents that a tagged canary demonstrably could not catch.
**Do not:** create staging data platforms; the BigQuery write gate + lineage are the data safety net.
**Required records:** if ever added — separate config/secrets/IAM documented in the inventory, never shared credentials.

## Rule: Introducing Kubernetes
**Default:** not currently justified — measurable thresholds, all currently unmet: ≥10–15 independently deployed always-on services (today: 1 + 4 batch); sustained need for long-running non-HTTP daemons or custom scheduling (none); Cloud Run cost or capability ceiling actually reached (nowhere near); ≥2 platform operators (1); multi-region requirement (none).
**Do not:** adopt for learning (learning clusters live outside production estate); re-evaluate only when ≥3 thresholds are simultaneously met.
**Required records:** a written threshold assessment in an ADR before any cluster exists.

## Rule: Retiring a service
**Default order:** decision record → archive source/assets (git or `docs/attic/`) → remove traffic (DNS/route/registry row) → delete runtime resource → flip inventory row to `retired` (keep the row) → purge repo references — all in one tracked change set.
**Do not:** delete runtime without the inventory flip (the stale `hotelops-hub` Worker vs STATUS.md is the standing counterexample); do not leave deploy configs for dead services in the repo (vetrina lesson).
**Required records:** inventory row (`retired`, date, reason), decision reference.
