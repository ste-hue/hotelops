# HotelOps — Target Architecture

**Date:** 2026-07-15 · **Basis:** `runtime-inventory.*` (audit), `runtime-intent-analysis.md` · **Companions:** `target-topology.mmd`, `migration-plan.md`, `architecture-decision-rules.md`, `golden-path-new-service.md`.

Recommendation classes used throughout: **required** / **recommended** / **optional** / **not currently justified**.

## 1. Executive recommendation

Keep the shape; finish the edges. The target architecture is the system that already exists — **Cloud Run + BigQuery as the product plane, Cloudflare as the satellite plane, two managed identity gates (IAP and Access) resolving the same Google identities, app-level grants in code** — completed along four axes:

1. **Continuity** (required): every source in a remote; every deploy reproducible from GitHub Actions on either laptop; no production knowledge that lives only in one head or one `~/.config`.
2. **Least privilege** (required): the hub gets a dedicated service account; `roles/editor` leaves the runtime path.
3. **Classification** (required): every hostname is assigned to a plane and an auth model — including mutui-tracker and the stale Worker — and recorded in the inventory.
4. **Namespace** (recommended): `panorama-host.com` becomes the canonical staff-app namespace on the Cloudflare plane; run.app remains the documented exception for the hub.

No new infrastructure categories. No Kubernetes, no Terraform, no proxies, no databases beyond what exists.

## 2. Architecture principles

In priority order (ties break upward):

1. **Security** — every surface has exactly one declared human gate + independent origin enforcement; machine access is keyless where the platform allows it.
2. **Operational clarity** — an engineer who has never met the operator can answer "which hostname → which runtime → which source → which policy" from the repo alone.
3. **Recoverability** — production rebuildable from GitHub + Secret Manager + this documentation; laptop loss costs hours, not knowledge.
4. **Reproducibility** — deploys are workflows, not rituals; same result from macOS, Linux, or CI.
5. **Low maintenance** — managed services; two clouds, no third; fewest moving parts that satisfy 1–4.
6. **Developer speed** — the golden path for a new internal app is one page + one registry row + one merged PR.
7. **Cost efficiency** — scale-to-zero everywhere; batch as jobs.
8. **Extensibility** — new needs enter through the decision rules, not ad-hoc.

## 3. Responsibility boundaries

**Google Cloud (`hotelops-suite`) owns:** dynamic application runtime (Cloud Run), scheduled/event batch (Cloud Run Jobs + Scheduler), analytical + canonical data (BigQuery), raw evidence (GCS), secrets for GCP workloads (Secret Manager), images (Artifact Registry), builds (Cloud Build via `--source` or Actions), logs/monitoring/alerting (Cloud Logging/Monitoring), machine identities (service accounts, keyless via WIF for CI).

**Cloudflare owns:** DNS for `panorama-host.com` (and other zones), proxying/TLS, **Access** (staff gate for the edge plane), Workers for small self-contained satellites, KV for small derived/shared documents, D1 for Worker-local relational state (reception only, for now), Pages for static GitHub-built sites. **Not enabled / not used by default:** R2 (GCS covers object storage), Queues, Durable Objects.

**Does not belong in Cloudflare by default:** anything that reads/writes BigQuery, Python workloads, application authorization for hub apps, secrets consumed by GCP workloads, business logic over canonical data.

**Does not belong in Google Cloud by default:** static brochure sites (Pages is cheaper/simpler), pure edge redirects.

## 4. Runtime decision matrix

| Workload | Default Runtime | Exceptions |
|---|---|---|
| Static assets / self-contained artifact | Cloudflare Pages (GitHub-built) or assets-only Worker | Worker only when a custom domain + Access gate or an API endpoint is needed alongside the assets |
| Redirects, header logic, lightweight edge transformation | Cloudflare Worker | None. Never build these into the Streamlit app |
| Dynamic HTTP application (Python, BigQuery-backed, interactive) | **Cloud Run service** — preferably a *page inside the existing hub*, a new service only when isolation is required | Worker only if JS-native, low-data, ≤ a few hundred lines, and edge execution or Access-gating is materially useful (reception pattern) |
| Scheduled batch | **Cloud Run Job + Cloud Scheduler** (keyless SA) | A service endpoint only if something must invoke it ad-hoc over HTTP |
| Event-driven batch | Cloud Run Job (Scheduler/Eventarc trigger) | Function-style only if cold-start latency of the jobs image ever matters (it doesn't today) |
| Stateful workload | BigQuery (analytical/canonical), GCS (objects), D1 (Worker-local relational), KV (small shared docs) | Never durable state in a container filesystem; a managed SQL instance only when a real OLTP need appears (none exists) |
| Cluster orchestration | **Not currently justified** | See §18 thresholds |

## 5. Cloudflare model

- **DNS:** `panorama-host.com` records owned via the runtime inventory (every record must have an inventory row); other zones (`finanzaorti.com`, personal) listed but out of the HotelOps golden path.
- **Access:** one Access application per staff-facing edge hostname; policy baseline = `email_domain: panoramagroup.it` + named externals; session ≤ 168h (recommended; current 730h on reception is a harden item). Access is the **only** public entry to edge apps: `workers_dev = false` on every Access-gated Worker (reception already does this — make it the rule).
- **Workers:** verdicts on current inventory — **`mutui-tracker`: retained + moved** behind `mutui.panorama-host.com` with Access (or an explicit recorded public-by-design decision — owner call); **`reception-control-tower`: retained unchanged** (already the reference implementation), plus source pushed to a remote; **`hotelops-hub` Worker: retired** after GAP-001 verification; **`xitnode-newsletter-subscribe`: left unchanged** (non-Panorama); **`bilancini` scaffold: deferred** until GAP-004 is answered — do not provision by default.
- **KV:** allowed for (a) BQ→edge published documents, (b) small shared state ≤ tens of KB with a single admin writer. Every namespace gets an inventory row + a backup note. **Not** a system of record without an export ritual (mutui scenario: add periodic export — harden item).
- **D1:** reception-only until a second concrete case appears. **R2: not currently justified** (disabled — keep it that way; GCS exists).
- **Pages:** fine for public static sites; each project must map to a live GitHub repo and a named owner or be retired (`finanza-react-app` is a retire candidate).

## 6. Google Cloud model

- **One project (`hotelops-suite`) for all HotelOps runtime + data.** No environment/sensitivity split at this scale (see §10). Sibling projects: leave, but record them as out-of-scope in the inventory; new projects only per decision rule (one per *product* with distinct blast radius, not per app).
- **Service accounts (required changes):**
  - `hotelops-hub@` — NEW dedicated SA for the Cloud Run service: `bigquery.dataEditor` + `bigquery.jobUser` (dataset-scoped where practical) + `storage.objectAdmin` on the two `hotelops-raw*` buckets + `secretAccessor` on what it needs. Replaces default compute SA (which keeps `roles/editor` today — SEC-002).
  - `hotelops-jobs@`, `drive-audit@` — keep; tighten to dataset/bucket scope opportunistically (P3); review `drive-audit@`'s `iam.serviceAccountTokenCreator`.
  - `github-deployer@` — NEW, used only via **Workload Identity Federation** from GitHub Actions (no keys): `run.developer`/`run.admin` on the service+jobs, `cloudbuild.builds.editor`, `artifactregistry.writer`, `iam.serviceAccountUser` on the runtime SAs.
- **Secrets:** Secret Manager stays the single store for GCP workloads (already true for jobs). The Cloudflare API token and Worker secrets live in the Cloudflare secret store + GitHub Actions secrets. SA **key files** on the laptop become the exception list: `workspace-controller.json` (domain-wide delegation — documented, reviewed yearly), `drive-audit-key.json` (eliminate: jobs are already keyless; local runs can impersonate).
- **Logging/monitoring:** native only (see §14).

## 7. Authentication model

**Human authentication — two gates, one rule each (required):**

| Plane | Gate | Applies to | Identity source |
|---|---|---|---|
| Google plane | **IAP** (custom OAuth client `hotelops-hub-iap`) | Cloud Run staff apps (today: the hub) | Google accounts (org + named externals) |
| Cloudflare plane | **Cloudflare Access** (team `panoramagroup.cloudflareaccess.com`) | everything on `panorama-host.com` | Same Google identities via Access IdP (verify IdP config — GAP-002) |
| Public | none, **by recorded decision only** | brochure sites (`finanzaorti.com` if confirmed) | — |

No third mechanism. No application login screens. Public access is a decision with a decision record, never a default.

**Origin protection (required):** Cloud Run origins stay **private** — invoker = IAP agent (or invoking SA for service-to-service). Never `allUsers`. Access-gated Workers keep `workers_dev = false` and verify the Access JWT in-Worker (reception pattern — already the strongest layer in the system; make it the template). *Edge auth alone is never treated as origin protection on either plane.*

**Application authorization (required):** stays **in application code**, versioned in git — `roles.py` grants for hub apps (S1/S2 invariants preserved), JWT-email → capability checks in Workers. Cloudflare Access answers *who enters the plane*, never *who sees which app*. One addition (recommended): satellites' allowed-email logic should read from a small shared convention (same emails as `roles.py`) rather than inventing per-app vocabularies.

**Machine-to-machine (required default):** Google **service accounts with ambient/OIDC identity** — Scheduler→Jobs already uses OAuth-as-SA (keep); CI→GCP uses WIF OIDC (new); service→service on Cloud Run would use ID-token invoker grants (none needed today). Exceptions: Cloudflare deploys use a scoped **API token** (no OIDC equivalent) stored in GitHub secrets; the mutui `ADMIN_TOKEN` bearer write-gate is an accepted micro-exception (single admin, timing-safe) — document + rotate. **API keys and SA JSON keys are last resorts** with an inventory entry each.

## 8. Authorization model

Summarized from above: three layers, each with one owner — **Access/IAP** (entry, infra-config, mirrored in inventory), **origin IAM / JWT check** (enforcement, platform-config + code), **app grants** (visibility/capability, git). A sensitivity flag (`sensitive=True` in the registry) marks write-capable surfaces; S1 (no sensitive app inherited via groups) and S2 (fail-closed) remain constitutional and extend to satellites.

## 9. Domain model

- **Canonical base domain:** `panorama-host.com` (Cloudflare plane). Convention: `<app>.panorama-host.com`, production only, lowercase, no environment infixes.
- **Hub exception (documented):** the hub stays on its run.app URL behind IAP. Optional later: `hub.panorama-host.com` via Cloud Run domain mapping (DNS-only CNAME, IAP unchanged) — **optional**, only if link ergonomics ever matter.
- **Staging/development hostnames:** none. Staging = Cloud Run **revision tags** (`https://<tag>---hotelops-hub-….run.app`, behind the same IAP) and `wrangler versions upload` preview URLs — both free, both ephemeral, both gated.
- **Direct Cloud Run URLs:** allowed only for IAP-gated services; never for anything public.
- **Every staff application gets exactly one hostname** (or one hub route) recorded in `runtime-inventory.yaml` with origin + auth. **Retired hostnames:** DNS record deleted, inventory row moved to `status: retired` (never silently dropped), repo references cleaned in the same PR — the vetrina taught this lesson.
- **Ownership:** DNS records and Worker routes are owned by the inventory file; a record with no inventory row is a finding.

## 10. Project and environment model

- **Projects:** keep `hotelops-suite` as the only HotelOps project. Division by environment/BU/billing: **not currently justified** (one operator, one billing account, IAP+IAM give adequate separation). Rule for new projects: only for a new *product* with a distinct security blast radius or distinct billing owner.
- **Environments:** **local + production**, deliberately. Staging infrastructure: **not currently justified** — replaced by (a) revision-tag canaries on Cloud Run, (b) Worker preview versions, (c) the existing process gate ("no hub page merges without real-data render review"). Environment-specific config = env vars set at deploy; secrets = Secret Manager (prod) vs `.env` (local, gitignored); data = production BigQuery for both, guarded by the write-gate (`bq_write_validated`) and lineage invariants — an accepted, documented risk at this scale.

## 11. Deployment model

**Standard path (required): GitHub Actions on `main`, keyless.**

| Target | Workflow | Mechanism |
|---|---|---|
| Cloud Run `hotelops-hub` | `deploy-hub.yml` on push to `main` (paths: app-relevant) | WIF → `gcloud run deploy --source .` (identical to today's manual command, just moved into CI) |
| Jobs image | `deploy-jobs.yml` on demand/on tag | WIF → `gcloud builds submit` (Dockerfile.jobs) → single moving tag `jobs:prod` + `gcloud run jobs update --image` per job |
| Workers (mutui, reception, future) | per-repo `deploy.yml` | `cloudflare/wrangler-action` with scoped API token |
| KV-backed content (bilancini-style publishes) | job or workflow step | `wrangler kv key put` from the exporter — never hand-edited |
| Static sites | Cloudflare Pages GitHub integration (already automated — the model citizen) | — |
| Infrastructure changes (IAM, Access apps, DNS, scheduler) | manual, **but recorded**: the change lands as an inventory + runbook edit in the same day | scripts/cloud pattern for anything repeatable |
| Emergency | manual `gcloud run deploy` / `wrangler deploy` from any authenticated machine — documented break-glass, followed by a catch-up commit | — |

What stays manual and why: IAM/Access/DNS mutations (rare, high-blast-radius, cheaper to review by hand than to automate); first-time provisioning (bootstrap scripts); `hotelops` CLI data operations (they are product, not infra). This model works identically from macOS and Linux because the laptop's only required tools are git + a browser; `gcloud`/`wrangler` become conveniences, not dependencies.

## 12. Infrastructure-as-code decision

**Terraform/Pulumi/Ansible: not currently justified.** Resource count (~1 service, 4 jobs, 4 schedulers, 3 Workers, 1 zone, 1 Access app), change frequency (months), and team size (1) put the maintenance cost above the drift risk. The failure mode IaC prevents (unrecorded drift) is addressed at this scale by **inventory-as-code**: `runtime-inventory.yaml` as the declarative record + idempotent `scripts/cloud/*.sh` for anything provisioned twice + a quarterly re-run of the read-only audit to diff reality against the inventory.

Per-resource assessment: DNS (2 records — inventory suffices), Access apps (1 — revisit at ~5+, Cloudflare provider then becomes attractive), Workers (wrangler.jsonc *is* declarative config — keep), KV namespaces (inventory), Cloud Run (deploy command in CI is the record), IAM/SAs (bootstrap script + inventory), Scheduler (scripts/cloud), secrets (names in inventory, values in stores), BigQuery datasets (out of scope here — schema truth is BQ + repo views, already governed).

**Trigger to revisit:** >10 Access apps/DNS records, a second operator, or a real rebuild exercise taking >1 day.

## 13. Configuration, state, and secrets model

| Value type | Correct storage | Current violations / ambiguities |
|---|---|---|
| Non-sensitive source-controlled config | repo (`registry.py`, `roles.py`, `wrangler.jsonc`, `source_registry.yaml`) | ✔ compliant |
| Environment-specific non-secret config | deploy-time env vars / workflow files | ✔ (little exists) |
| Secret | Secret Manager (GCP) / Cloudflare secret store / GitHub Actions secrets | `drive-audit-key.json` on disk (eliminate); `workspace-controller.json` (documented exception, DWD); `.env` + `.dev.vars` (fine — local only, gitignored) |
| Lightweight edge config / published docs | KV, written by pipeline only | mutui scenario = system of record without backup (**harden**) |
| Durable application data | BigQuery / GCS / D1 | ✔; D1 schema unverified (GAP-008) |
| Analytical data | BigQuery | ✔ |
| Build artifact | Artifact Registry | jobs tags v1–v3 stale vs HEAD (**standardize** via CI) |
| Local developer override | `.env`, `HUB_DEV_ALLOW_ALL` | ✔ explicit and fail-closed |

## 14. Observability standard

Minimum per production service (required), using **native tooling only** — no Prometheus/Grafana/Loki (not currently justified; no gap demonstrated):

- **Logs:** Cloud Logging (services/jobs — automatic); Workers observability enabled (mutui ✔; enable on reception).
- **Deploy history:** Cloud Run revisions + GitHub Actions run log (once CI lands); Workers versions.
- **Errors/alerts:** existing Monitoring policy "Cloud Run Job failed" (✔ keep) + one uptime check on `reception.panorama-host.com` and the hub URL expecting 302 (recommended — a 200 would mean the gate fell off, exactly the regression class the audit hunts).
- **Metadata per service (in inventory):** owner, environment, source repo+path, service account, hostname, alert destination. Source commit: emitted by CI into the deploy description (recommended).

## 15. Ownership model

Canonical records (all in-repo, all updated in the same PR as the change):

| Concern | Canonical record |
|---|---|
| Runtime inventory (hosts, origins, auth, SAs) | `docs/architecture/runtime-inventory.yaml` |
| Staff-app registry + grants | `verticals/hub/registry.py` + `roles.py` |
| Architecture decisions | `docs/architecture/` ADRs + vault decisions |
| Runbooks / recovery | `docs/architecture/golden-path-new-service.md` + hub README + `scripts/cloud/` |
| Ownership | `owner:` field per inventory entry (default: stefano@panoramagroup.it — make the default explicit rather than implicit) |
| Sensitivity | `sensitive=` in registry (hub) / inventory field (satellites) |

Update matrix — when a service is **created/deployed/renamed/moved/exposed/protected/retired**, the required edits are: inventory row (always), registry+grants (if staff-facing), golden-path checklist sign-off (created), decision record (exposed publicly or retired). A service without an inventory row does not exist, and a live resource without a row is an incident-of-record (the stale Worker is the proof).

## 16. Golden path for new applications

Full procedure in `golden-path-new-service.md`. Summary: default = **a page in the hub** (new module + `render()` + one registry row + grants + PR + CI deploy). Satellite Worker path only when the decision rules say so (reception template: Access + custom domain + JWT check + `workers_dev=false` + remote repo + inventory row).

## 17. Recovery model

Rebuild after loss of the development machine (target state): clone repos from GitHub (all sources have remotes — required fix for reception/bilancini) → authenticate `gcloud`/`wrangler` in a browser → production untouched throughout (CI kept deploying) → secrets never lived on the laptop except documented exceptions → re-run bootstrap scripts only if GCP resources themselves were lost. Recovery of *knowledge*: this document set + inventory. Explicitly recorded residual dependencies: Google Workspace admin access, Cloudflare/GitHub account credentials (password-manager escrow recommended — organizational, not technical).

## 18. Technologies explicitly not justified — and what would change that

| Technology | Verdict | Would become justified when |
|---|---|---|
| Kubernetes | not currently justified | ≥10–15 independently deployed always-on services **and** (custom scheduling / long-running non-HTTP daemons / Cloud Run cost sustained ≫ current spend / multi-region) **and** ≥2 platform operators. None met: 1 service, 4 batch jobs, 1 operator |
| Nginx / Caddy | not justified | never at the edge (Cloudflare) or on Cloud Run (platform terminates) — would only appear with a VM, itself unjustified |
| Service mesh | not justified | multiple services with east-west traffic (there is no east-west traffic) |
| Terraform / Pulumi / Ansible | not justified (see §12) | >10 CF Access/DNS objects, second operator, failed rebuild drill |
| Self-hosted CI runners | not justified | build minutes cost or private-network builds (none) |
| Dedicated VMs / local production servers / homelab deps | not justified — the target explicitly removes the last machine-dependence | a workload Cloud Run cannot run (none foreseen) |
| Self-hosted DBs / Redis / message queues | not justified | real OLTP or queueing need; today BQ+GCS+D1+KV+Scheduler cover everything |
| Multi-region | not justified | availability requirement beyond a single-region SLA for internal tooling |
| VPN / zero-trust overlays | not justified | IAP + Access already provide identity-aware access to everything |
| Custom identity systems | never — Google identities via IAP/Access only | — |

Learning any of these remains a valid *personal* goal — in sandboxes, never in this production estate.

## 19. Concern table

| Concern | Current State | Likely Intent | Recommended State | Reason | Priority | Confidence |
|---|---|---|---|---|---|---|
| Dynamic runtime | Cloud Run (hub monolith) | Cloud Run standard | unchanged; ratified as rule | works, cheap, managed | — | high |
| Batch | 4 Jobs + Scheduler, keyless SAs | as-is | unchanged + CI-built image tag `prod` | tag drift v1–v3 | P2 | high |
| Hub SA | default compute, `roles/editor` | expedient interim | dedicated `hotelops-hub@`, scoped | SEC-002 blast radius | **P1** | high |
| Source continuity | 2 repos laptop-only | none (oversight) | all sources on GitHub remotes | SEC-005, machine loss | **P0** | high |
| Deploys | manual from laptop | automate later | GitHub Actions (WIF + wrangler-action), manual break-glass | GAP-001-class orphans, machine dependence | **P1** | high |
| Stale Worker `hotelops-hub` | live, public, frozen | none | verify (GAP-001) then retire | SEC-001 | P1 | medium |
| mutui-tracker exposure | public workers.dev | inertia | `mutui.panorama-host.com` + Access, or recorded public decision | SEC-003 | P1 | medium |
| Staff auth | IAP (GCP) + Access (CF), undocumented split | dual-plane | same, written as rule; sessions ≤168h | classification clarity | P2 | high |
| IAP allowlist | domain-wide vs per-email docs | unclear | align README to reality (grants already fail closed) | SEC-004 | P2 | high |
| Hostnames | run.app + workers.dev + 1 custom | panorama-host.com namespace | complete namespace for satellites; hub run.app documented exception | traceability | P2 | medium |
| Bilancini duality | hub page live + Worker scaffold | unresolved (GAP-004) | keep hub page; defer Worker pending owner decision | duplication risk | P2 | low |
| KV scenario | system of record, no backup | facts/projections ontology | keep + scheduled export to GCS/repo | durability | P2 | high |
| IaC | none | none | inventory-as-code + scripts; no Terraform | scale doesn't justify | — | medium |
| Environments | local + prod | minimalism | unchanged + revision-tag canaries | staging not justified | P3 | high |
| Observability | native + job-fail alert | as-is | + uptime checks (302 assertions), Worker logs on reception | gate-regression detection | P2 | medium |
| Account ownership | personal CF/GitHub accounts | unexamined | document now; org migration deferred with trigger | continuity, not urgent | P2 | medium |
| Cloudflare storage | KV×1, D1×1, R2 off | pragmatic | unchanged; R2 stays off | no need | — | high |
| finanzaorti.com | public, stale, unclear | unknown (GAP-003) | clarify → keep-and-own or retire | unowned public surface | P2 | low |

## 20. Technology decision table

| Technology | Current Use | Concrete Problem Solved | Cost of Not Using | Recommendation |
|---|---|---|---|---|
| Cloud Run | hub service | managed HTTPS runtime for Python/Streamlit over BQ, scale-to-zero, IAP-native | self-managed VM + TLS + auth | **retain (standard)** |
| Cloud Run Jobs | 4 batch ingests | scheduled batch without servers; keyless Drive/BQ access | cron on a laptop (the pre-06/30 world) | **retain (standard)** |
| Cloudflare Workers | 2 live apps + 1 stale | zero-cost always-on satellites; Access integration; custom domains | Cloud Run min-instances or worse ergonomics for tiny apps | **retain, bounded by decision rules; retire the stale one** |
| Cloudflare Access | reception gate | staff SSO on edge apps with org identities | building auth into each satellite | **retain, expand to all panorama-host.com hosts** |
| KV | mutui scenario | shared mutable document with admin writes | a database for one JSON doc | **retain + backup ritual** |
| D1 | reception board | relational state co-located with Worker | external DB + latency + creds | **retain, reception-scoped; no new D1 without rule** |
| R2 | none (disabled) | — | — | **not currently justified** (GCS exists) |
| Docker (via Cloud Build) | image builds | reproducible runtimes | unbuildable services | **retain** (no local Docker daemon needed — `--source` builds remotely; Podman locally optional) |
| Nginx / Caddy | none | — | — | **not currently justified** |
| Kubernetes | none | — | — | **not currently justified** (thresholds §18) |
| Terraform | none | — | manual drift, mitigated by inventory-as-code at this scale | **not currently justified** (revisit triggers §12) |
| Ansible | none | — | — | **not currently justified** |
| GitHub Actions | tests + Claude bots | (target) reproducible keyless deploys from any machine, deploy history | laptop-bound deploys, orphan risk (proven by GAP-001) | **adopt for deploys (P1)** |
| Cloud Build | implicit via `--source` | container builds without local Docker | local builds | **retain as build backend** (triggers stay unused; Actions orchestrates) |
