# HotelOps — Golden Path for a New Application

**Date:** 2026-07-15. The standard procedure for introducing a new HotelOps application, from either macOS or Linux, with no dependence on undocumented local state. Two tracks: **Track A (default): a page in the hub** · **Track B (exception): a satellite Worker**. Which track: apply `architecture-decision-rules.md` → "Use Cloud Run for substantial dynamic applications" / "New Cloudflare Worker". When in doubt: Track A.

Prerequisites (both OSes): `git`, Python ≥3.11 (Track A), Node ≥20 (Track B), a browser. `gcloud`/`wrangler` are optional conveniences once CI deploys exist (STD-01); nothing below requires local Docker (Cloud Build builds remotely).

---

## Track A — page in the hub (default)

**1. Source directory.** Domain logic in the owning vertical (`verticals/<vertical>/…`), exposing a `render()` that takes no args and never calls `st.set_page_config`. Thin wrapper in `verticals/hub/pages_/<app_id>.py`. (Contract details: skill `hub-bind`.)

**2. Registry entry.** One row in `verticals/hub/registry.py::APPS` — id, title, icon, group, `kind="page"`, `render`, subtitle, and **`sensitive=True` if it writes or mutates state** (S1). `validate()` runs at import; tests in `tests/test_hub_mounts.py` style.

**3–4. Build & runtime.** Nothing to choose: the app rides the existing hub container (root `Dockerfile`) on Cloud Run. New standalone Cloud Run services need a written isolation reason (decision rules).

**5. Service account.** Inherited: `hotelops-hub@` (post HAR-02). If the page needs a *new* dataset/bucket, extend that SA's scoped grants — never widen to project level.

**6. Secrets.** Page needs a secret → Secret Manager + `--set-secrets` on the service (name recorded in inventory). Local dev → `.env`.

**7. Deployment.** Merge to `main` → `deploy-hub.yml` (WIF, keyless) deploys. Pre-merge review of a risky page: `gcloud run deploy hotelops-hub --source . --no-traffic --tag pr-<n>` and review the tagged URL (behind the same IAP). **Gate (constitutional):** no hub page merges without the owner seeing the render with real data.

**8–9. Hostname / Cloudflare.** None — the page lives under the hub's URL. No Cloudflare involvement.

**10. Human authentication.** Inherited: IAP. If a *new person* needs access: IAP allowlist (Console) + grant row — both, in that order.

**11. Application authorization.** Grant the app id in `roles.py::_GRANTS` per person or via group constants (never for sensitive apps — S1). Default is nobody sees it (fail-closed).

**12. Logging.** Automatic (Cloud Logging). Add structured `st`-side error surfacing per hub conventions; no new tooling.

**13. Documentation.** Update: hub README grants table (if grants changed), `runtime-inventory.yaml` only if the app introduced a new secret/SA-grant/downstream (a plain page needs no inventory change — the registry *is* its record), STATUS.md entry.

**14. Ownership.** The registry row's PR author is the owner unless the subtitle/README says otherwise; name a person for sensitive apps.

**15. Retirement.** Follow the retirement rule: registry row removed (or `kind="soon"` if pausing, like CdG), grants cleaned, wrapper deleted, STATUS note. No infra to touch.

**Validation checklist (A):** `pytest` green (registry/roles tests) · canary render reviewed with real data · grants verified as the target user (or `HUB_DEV_ALLOW_ALL=1` locally, then live spot-check) · post-deploy: hub URL still 302s anonymously. **Rollback:** revert the PR (previous revision redeploys), or `gcloud run services update-traffic --to-revisions <prev>=100` for instant traffic rollback.

---

## Track B — satellite Worker (exception; reception is the reference)

**1. Repository.** New private GitHub repo `ste-hue/<app>` (or the org, post DEF-03), cloned wherever — **a remote is mandatory before first deploy** (HAR-01 lesson). Layout: `src/index.js`, `public/`, `wrangler.jsonc`, `migrations/` (if D1), `README.md`, `.dev.vars` (gitignored).

**2. Naming.** Worker name = repo name = subdomain: `<app>.panorama-host.com`. No environment suffixes.

**3. Runtime config (`wrangler.jsonc`).** Copy the reception template: `workers_dev: false`, `routes: [{pattern: "<app>.panorama-host.com", custom_domain: true}]`, compatibility date current, bindings declared (KV/D1 per decision rules), `vars`: `ACCESS_TEAM_DOMAIN=panoramagroup.cloudflareaccess.com`, `ACCESS_AUD=<from step 6>`.

**4. Local development.** `npx wrangler dev` (works on macOS/Linux); secrets in `.dev.vars`; Access check must no-op cleanly in dev (env-guarded, fail-closed in prod).

**5. Service identity / machine access.** Workers get no Google identity. If the app needs HotelOps data: **publish** derived JSON from a pipeline into KV (BQ→KV export job) — never embed GCP credentials in a Worker.

**6. Authentication (Cloudflare).** Zero Trust → Access → new self-hosted app on the hostname; policy: `email_domain panoramagroup.it` + named externals; session ≤168h. Copy the app AUD into `ACCESS_AUD`. The Worker **must verify the Access JWT** (port reception's check) — edge config alone is not origin protection.

**7. Authorization.** Capability decisions from the verified JWT email, using the same email vocabulary as `roles.py`. Admin-write micro-APIs may additionally use a bearer secret (mutui pattern) — timing-safe compare, secret via `wrangler secret put`, rotation owner recorded.

**8. Secrets.** `wrangler secret put NAME` (values never in git); names recorded in the inventory row.

**9. Deployment.** `deploy.yml` with `cloudflare/wrangler-action` + scoped API token (Actions secret). First provision (custom domain, Access app, KV/D1 creation) is manual-with-record: do it, then update inventory the same day. Pre-release: `wrangler versions upload` preview.

**10. Hostname/DNS.** Created automatically by the custom-domain route; verify one inventory row exists for it *before* announcing the URL.

**11. Logging/monitoring.** `observability: {enabled: true}` in wrangler config; optional uptime check asserting **302** for anonymous requests (the gate test).

**12. Documentation & registry.** Inventory row (worker, hostname, bindings, secrets by name, owner, sensitivity). If staff-facing, add a hub tile: `HubApp(<id>, …, kind="bind", target="https://<app>.panorama-host.com")` + grants — satellites must be discoverable through the hub (the reception omission is the counterexample).

**13. Ownership.** Named in the inventory row.

**14. Validation checklist (B):** anonymous curl → 302 to `panoramagroup.cloudflareaccess.com` · authorized user reaches the app · `workers.dev` URL → nothing (subdomain disabled) · JWT check rejects a missing/forged assertion (dev test) · CI deploy green from a fresh clone on the *other* OS.

**15. Rollback.** `wrangler rollback` / redeploy previous version; Access app and DNS are independent of code versions.

**16. Retirement.** Decision record → archive repo → remove hub tile + grants → delete Access app → delete custom domain/DNS → `wrangler delete` → inventory row `retired` → grep repo references. In that order.

---

## Machine-independence guarantees (both tracks)

- Source of truth: GitHub. A stolen/dead laptop loses nothing but uncommitted work.
- Deploys: CI (keyless WIF / scoped token). Local `gcloud`/`wrangler` = break-glass, re-authenticated via browser on any machine.
- Secrets: Secret Manager / CF secrets / Actions secrets. Local `.env`/`.dev.vars` are recreatable conveniences, listed by *name* in the inventory.
- Knowledge: this document set + `runtime-inventory.yaml` + hub README. If a step required something not written here, the fix is to write it here.
