# HotelOps — Migration Plan (current → target)

**Date:** 2026-07-15 · **Status: PLAN ONLY — no action in this document has been executed.** Every action below awaits explicit owner (Stefano) approval; actions marked *human verification required* must not be automated blindly.

Field legend per action: current → target, reason, affected, benefit, risk, prerequisites, complexity, reversibility, validation, rollback, priority, confidence, human-verify.

---

## KEEP — already aligned with the target

**KEEP-01 — Cloud Run hub behind IAP with origin IAM enforcement.** Verified private origin (302 + invoker=IAP agent). Confidence high.
**KEEP-02 — Cloud Run Jobs + Scheduler with keyless SAs** (drive-audit@ ADC pattern). Confidence high.
**KEEP-03 — reception-control-tower pattern**: Access at edge + JWT re-verification in Worker + `workers_dev=false` + custom domain. This is the satellite template. Confidence high.
**KEEP-04 — App-level authorization in code** (`roles.py`, S1/S2 invariants, fail-closed). Confidence high.
**KEEP-05 — BigQuery/GCS data plane with single write gate** (`bq_write_validated`) and lineage invariants. Confidence high.
**KEEP-06 — Cloudflare Pages GitHub integration** for static sites (the only currently automated deploy path — the model). Confidence high.
**KEEP-07 — Two-environment minimalism** (local + prod) with explicit dev bypass (`HUB_DEV_ALLOW_ALL`). Confidence high.
**KEEP-08 — Native observability**: Cloud Logging/Monitoring + existing job-failure alert channel; Workers observability. Confidence medium.

---

## CLARIFY — possibly correct, but undocumented or unverified

**CLA-01 — Bilancini Worker intent (GAP-004).**
Current: live hub page + undeployed Worker scaffold, same name, different auth planes. Target: one written decision (recommended: hub page is canonical; Worker deferred until a concrete non-Streamlit consumer exists). Reason: duplication risk on sensitive financial data. Affected: `panorama_apps/bilancini`, hub registry. Benefit: no parallel access story. Risk: none (decision, not change). Prereq: owner answer. Complexity low · reversible fully · validation = decision recorded in vault/ADR · rollback n/a · **P2** · confidence low on intent · **human verification required**.

**CLA-02 — Zero Trust IdP configuration (GAP-002).**
Current: Access verified working, IdP type unknown (Google OAuth vs One-Time-PIN). Target: dashboard check + one line in inventory. Reason: OTP-only IdP would weaken the reception gate to email possession. Complexity low · **P1** (security ambiguity) · confidence n/a · human dashboard access required.

**CLA-03 — Looker Studio "Banche" ACL (GAP-005).**
Current: hardcoded bind URL, sharing unknown. Target: sharing model verified + recorded; if "anyone with link", restrict. Reason: possible auth-bypass of the entire model for bank data. Complexity low · **P1** · human verification required.

**CLA-04 — finanzaorti.com purpose (GAP-003).**
Current: public Pages site, last deploy 2025-08, no local checkout. Target: keep-and-own (inventory row, owner, content review) or retire (see RET-04 path). Complexity low · **P2** · human verification required.

**CLA-05 — NanoClaw runtime (GAP-006).**
Current: ingest-capable WhatsApp agent, runtime unknown. Target: runtime + credentials documented in inventory; its BQ write path confirmed to pass the lineage gate. Complexity low-medium · **P2** · human verification required.

**CLA-06 — Account ownership record (personal Cloudflare + GitHub accounts).**
Current: org production on `ste.dellapietra@gmail.com` (CF) and `ste-hue` (GitHub), undocumented. Target: recorded in inventory `accounts:` with an escrow note (credentials in a password manager reachable by a second trusted person); org-account migration **deferred** (DEF-03) with trigger = second engineer or ownership handover. Reason: continuity, bus-factor. Complexity low (documenting) · **P2** · confidence high.

**CLA-07 — D1 schema state (GAP-008)** via one read-only `sqlite_master` SELECT or dashboard. **P3**.
**CLA-08 — IAP allowlist vs README (SEC-004).** Target: README updated to describe reality (domain-wide entry + fail-closed grants) *or* allowlist tightened to named emails — owner choice; document either. Complexity low · **P2** · human verification required.

---

## STANDARDIZE — same function, currently divergent implementations

**STD-01 — Deployment via GitHub Actions (keyless).**
Current: manual `gcloud run deploy` / `wrangler deploy` from one laptop; Actions = tests only. Target: `deploy-hub.yml` (WIF → `gcloud run deploy --source .`), `deploy-jobs.yml` (Cloud Build → `jobs:prod` tag → `run jobs update`), per-Worker `deploy.yml` (`wrangler-action`, scoped API token). Manual = documented break-glass. Reason: machine-independence, deploy history, prevents GAP-001-class orphans; works from macOS/Linux/nothing. Affected: 3 repos, new `github-deployer@` SA + WIF pool, CF API token. Benefit: reproducibility + auditability. Risk: misconfigured WIF blocks deploys (break-glass covers); token scoping errors. Prereq: HAR-02 (SA), repos on remotes (HAR-01). Complexity **medium** · reversible (delete workflows) · validation: one no-op deploy per target from CI, then from the *other* laptop OS doing nothing · rollback: revert workflow, redeploy manually · **P1** · confidence high · human approves token/WIF setup.

**STD-02 — Hostname namespace.**
Current: run.app + workers.dev + one custom domain. Target: every *satellite* on `<app>.panorama-host.com` behind Access; hub stays on run.app (documented exception); every hostname = one inventory row. Affected: mutui (see HAR-04), future apps. Complexity low-medium · **P2** · confidence medium.

**STD-03 — Jobs image lifecycle.**
Current: tags v1/v2/v3 pinned since 2026-06-30, drifting from HEAD. Target: single moving `jobs:prod` tag built by CI; jobs updated to it in the same workflow; repo HEAD = deployed code invariant. Risk: a bad merge reaches all 4 jobs — mitigated by job max-retries + failure alert + tag rollback (`gcloud run jobs update --image ...:prev`). Complexity low · reversible · validation: next scheduled runs green · **P2** · confidence high.

**STD-04 — Satellite Worker template.**
Current: reception implements Access-JWT verification; bilancini scaffold ports it by copy. Target: documented template (or tiny shared module) covering JWT check, `workers_dev=false`, custom domain, inventory row, remote repo. Complexity low · **P2** · confidence high.

**STD-05 — Revision-tag canary as the standard pre-release check for the hub.**
Current: deploy-then-look. Target: `gcloud run deploy --no-traffic --tag pr-N` → review on tagged URL (behind same IAP) → promote traffic. Formalizes the existing "Stefano sees real-data render before merge" gate with zero new infra. Complexity low · **P3** · confidence medium.

---

## CONSOLIDATE — duplicates converging

**CON-01 — One Bilancini surface** (executes CLA-01's decision). If hub-canonical: archive the scaffold with a README pointing at the hub page; delete the dangling `bilancini.panorama-host.com` plan or keep as dated design note. Complexity low · reversible (scaffold stays in git history) · **P2** · human decision first.

**CON-02 — Purge vetrina remnants from hotelops repo.**
Current: `verticals/hub/publish/` (wrangler.toml `hotelops-vetrina`, stale `site/apps.json` with dead URLs + legacy run.app alias), `publish-export` CLI path. Target: directory removed (or archived under `docs/attic/`), CLI command removed, README already marks it retired. Reason: SEC-008 accidental-redeploy footgun + stale references. Risk: none identified (exporter's only consumer was the vetrina); verify no cron/job calls `publish-export` first. Complexity low · reversible via git · validation: grep + test suite green · **P2** · confidence high · human sign-off on deletion.

**CON-03 — Retire duplicate copies**: `~/dev/Projects/finanza/app-mutui` (superseded local clone — archive/delete locally) and Pages project `finanza-react-app` (see RET-03). **P3**.

---

## HARDEN — security & reliability

**HAR-01 — Push laptop-only sources to remotes. (P0)**
Current: `reception-control-tower` (in production!) and `bilancini` exist only as local git repos on one machine (SEC-005). Target: private GitHub repos under the same owner; local repos gain `origin`. Reason: a dead laptop currently destroys the only source of a production Worker. Benefit: continuity; prerequisite for STD-01. Risk: none (additive). Complexity **low** · fully reversible · validation: `git remote -v` + fresh clone builds · rollback: delete remote · **P0** · confidence high · needs owner's GitHub auth.

**HAR-02 — Dedicated scoped SA for the hub. (P1)**
Current: default compute SA with project `roles/editor` runs an org-reachable write surface (SEC-002). Target: `hotelops-hub@` with `bigquery.dataEditor`+`jobUser` (+ dataset-scope where practical), `storage.objectAdmin` on `hotelops-raw*`, needed `secretAccessor`; service redeployed with `--service-account`; after a soak period, review whether default compute still needs `roles/editor` at all. Reason: blast-radius. Risk: missed permission → hub feature breaks; mitigated by canary tag (STD-05) + fast rollback. Complexity **medium** · reversible (redeploy with old SA) · validation: exercise every sensitive page (cashflow write, ingest, bilancini render) on canary before promote · rollback: `gcloud run services update --service-account <old>` · **P1** · confidence high · human verification required (write-path testing).

**HAR-03 — Retire the stale public `hotelops-hub` Worker. (P1)**
Current: public org-branded launcher frozen at 2026-06-18 (SEC-001), provenance unknown (GAP-001). Target: verify content/versions (10-minute read-only check), archive a copy of served assets into the repo attic, then `wrangler delete hotelops-hub`. Risk: something unknown links to it — check referrers unavailable; mitigation: it 404s like the vetrina did, acceptable. Complexity low · **partially reversible** (assets archived; name reusable) · validation: curl → 404 · rollback: redeploy archived assets · **P1** · confidence medium · **human verification required before deletion**.

**HAR-04 — Assign mutui-tracker to a plane. (P1)**
Current: public workers.dev, group debt data world-readable (SEC-003). Target (recommended): `mutui.panorama-host.com` + Access app (same policy family: org domain + stefano gmail + stedepi gmail), workers.dev disabled, hub iframe URL updated; ADMIN_TOKEN kept for writes. Alternative (owner may choose): recorded public-by-design decision + keep. Reason: today's exposure is inertia, not decision. Risk: Access breaks the hub iframe embed (Access on iframes needs same-browser session — org users are logged in; verify) and padre's access (stedepi@ must be in policy). Complexity **medium** · reversible (re-enable workers.dev) · validation: hub embed renders for a granted user; incognito → Access login · rollback: remove Access app, re-enable subdomain · **P1** · confidence medium · **human decision + verification required**.

**HAR-05 — KV scenario backup.** Nightly (or post-write) export of `SCENARIO_KV:current` to `gs://hotelops-raw*/backups/` or the repo. Complexity low · **P2** · confidence high.
**HAR-06 — Access session ≤168h** on reception (currently 730h) and future apps (SEC-009). Complexity trivial · **P3**.
**HAR-07 — Uptime checks asserting the *gates*:** hub URL expects **302** (200 = IAP fell off), reception expects **302** (200 = Access fell off). Cloud Monitoring uptime checks + existing email channel. Complexity low · **P2** · confidence high.
**HAR-08 — Secret hygiene pass:** eliminate `drive-audit-key.json` (impersonation for local runs), document `workspace-controller.json` DWD as the reviewed exception, record `ADMIN_TOKEN` holder + rotation date (GAP-010), confirm `.env`/`.dev.vars` gitignore coverage (already verified clean). Complexity low · **P2**.
**HAR-09 — Job SA scope tightening** to dataset/bucket level + drop `drive-audit@`'s `iam.serviceAccountTokenCreator` if unused (SEC-007). Requires usage check first. Complexity medium · **P3**.

---

## RETIRE — after verification only

**RET-01 — Worker `hotelops-hub`** → via HAR-03. **P1**.
**RET-02 — `verticals/condges/Dockerfile`** (GAP-009): `git log --follow` to confirm fossil, then delete. **P3** · reversible via git.
**RET-03 — Pages `finanza-react-app`**: confirm superseded by `finanza` (owner), then delete project. **P3** · reversible (redeployable from repo if one exists — verify before deleting).
**RET-04 — `finanzaorti.com` (conditional)**: only if CLA-04 concludes "dead" — retire Pages custom domain + project, keep zone parked, inventory row → retired. **P2** · human decision required.
**RET-05 — Legacy references cleanup**: stale run.app alias + dead vetrina URLs in committed docs/`apps.json` (subsumed by CON-02 where applicable). **P3**.

---

## DEFER — real ideas, no current problem

**DEF-01 — Terraform/IaC** — trigger: >10 CF Access/DNS objects, second operator, or failed rebuild drill (see target-architecture §12).
**DEF-02 — Staging environment** — revision tags + Worker previews cover today's need.
**DEF-03 — Org migration of Cloudflare + GitHub accounts** — trigger: second engineer or ownership handover; until then CLA-06 documents and escrows.
**DEF-04 — `hub.panorama-host.com` custom domain for the hub** — ergonomics only; IAP on run.app is fully functional.
**DEF-05 — Standalone bilancini Worker** — pending CLA-01; needs a concrete consumer that the hub page cannot serve.
**DEF-06 — hotelops-api keystone** (from STATUS backlog) — explicitly deferred by prior decision; nothing here changes that.
**DEF-07 — Kubernetes / mesh / Redis / queues / VMs / multi-region** — not currently justified; thresholds in target-architecture §18.

---

## Sequencing (recommended first phase ≈ one working day + reviews)

1. **HAR-01** (push repos — 15 min, P0)
2. **CLA-02 + CLA-03** (two dashboard checks — 20 min, P1 ambiguity closers)
3. **HAR-02** (hub SA — the one medium-risk change; canary + verify writes)
4. **STD-01** (CI deploys; hub first, Workers second, jobs third)
5. **HAR-03 + HAR-04** (stale Worker retirement; mutui plane decision)
Then P2 wave: CON-02, STD-02/03, HAR-05/07/08, CLA-01/04/05/06/08.

**Gap coverage check:** GAP-001→HAR-03 · GAP-002→CLA-02 · GAP-003→CLA-04/RET-04 · GAP-004→CLA-01/CON-01 · GAP-005→CLA-03 · GAP-006→CLA-05 · GAP-007→project rule (decision rules) · GAP-008→CLA-07 · GAP-009→RET-02 · GAP-010→HAR-08. SEC-001→HAR-03 · SEC-002→HAR-02 · SEC-003→HAR-04 · SEC-004→CLA-08 · SEC-005→HAR-01 · SEC-006→HAR-08 · SEC-007→HAR-09 · SEC-008→CON-02 · SEC-009→HAR-06.
