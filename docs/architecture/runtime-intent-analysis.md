# HotelOps — Runtime Intent Analysis

**Date:** 2026-07-15 · **Inputs:** the five `runtime-*` audit artifacts (2026-07-15), repo docs (`INVARIANTS.md`, `AI_INSTRUCTIONS.md`, hub README, superpowers specs/plans, STATUS.md), git history. · **Mode:** analysis only — no infrastructure touched.

Every conclusion is tagged **observed** / **inferred** / **recommended** with confidence.

## 1. Executive conclusion

HotelOps is not an accident, and it is not finished. The observed system is a **deliberately minimal two-cloud design** — Cloud Run + BigQuery as the product plane, Cloudflare as the satellite/edge plane — executed by one operator who consistently chose managed services and consciously deferred automation. The divergences that matter are not design flaws but **incomplete transitions**: a front-door consolidation that left one Worker behind (stale public `hotelops-hub`), an authentication convergence started but not finished (IAP today, Cloudflare Access scaffolded for tomorrow), a hostname namespace (`panorama-host.com`) created but populated with a single record, and sources/accounts that still live on one laptop and one personal identity. The target architecture should therefore be a **completion, not a redesign**: finish the transitions, write down the rules the operator already follows implicitly, and remove the leftovers.

## 2. Current architecture summary (observed, high confidence)

See `runtime-inventory.md` for full detail. In one paragraph: a single IAP-gated Cloud Run Streamlit monolith (`hotelops-hub`) is the interactive product, mounting ~10 pages over BigQuery with app-level per-email grants (`roles.py`); four Cloud Scheduler–triggered Cloud Run Jobs feed BigQuery from Drive/Apify/PMS exports; Cloudflare hosts satellites — public `mutui-tracker` (Worker+KV), Access-gated `reception-control-tower` (Worker+D1) on `reception.panorama-host.com`, public Pages site `finanzaorti.com` — plus one stale public Worker; all deploys are manual from the laptop; there is no staging, no IaC, no CI/CD deploy path.

## 3. Likely original intent (inferred)

The repo states the goal explicitly: *"HotelOps è il Company OS"* (CLAUDE.md) with three layers — code (how the twin operates), BigQuery (what it observes), vault (human meta-knowledge). Runtime intent, reconstructed from specs and history:

1. **One front door** for staff: the hub on Cloud Run behind IAP ("front-door unico", STATUS 2026-06-20, after retiring the Cloudflare vetrina).
2. **Satellites at the edge** for self-contained artifacts that don't need live BigQuery (mutui-tracker pattern, codified in the `hub-bind` skill as cases B1/B2).
3. **Batch = Cloud Run Jobs + Scheduler**, keyless where possible (2026-06-30 cloud-only cutover plan, executed).
4. **A canonical hostname namespace** (`panorama-host.com`) with **Cloudflare Access** as staff gate for edge apps — begun with reception, scaffolded for bilancini, anticipated in `roles.py` (`Cf-Access-Authenticated-User-Email` header support).
5. **Automation deferred consciously** — plans repeatedly say "deploy manuale slice 1", "Access/automazione dopo".

## 4–6. Major inferences (matches and divergences)

### Inference: Cloud Run is the intended standard dynamic runtime
**Observed:** The only dynamic HTTP app runs on Cloud Run; the retired Streamlit-on-Cloudflare experiments (vetrina) were consciously rolled back to Cloud Run ("il soffitto Streamlit era il bug blanket-CSS… Streamlit ora piace di nuovo", STATUS 06-20). Jobs also standardized on Cloud Run.
**Inferred intent:** Cloud Run as the default runtime for anything substantial/Pythonic; Workers only where edge-native.
**Evidence:** Dockerfile comments, hub README deploy section, cloud-only-jobs plan, vetrina retirement decision.
**Confidence:** High.
**Divergence:** None material.
**Consequence:** The target can ratify this as a rule rather than change anything.

### Inference: Workers were intended as edge utilities / static satellites, not general app runtimes
**Observed:** Both live Panorama Workers are assets-plus-thin-API (mutui: static + one KV endpoint; reception: static board + D1 + AI triage). The one attempt to move a *product surface* to the edge (vetrina launcher) was retired.
**Inferred intent:** Workers = cheap, always-on, self-contained artifacts ("è online a costo zero" — static-edge spec 2026-06-13); the hub-bind skill explicitly reserves bespoke JS for "superfici brand/vetrina, non strumenti dati".
**Confidence:** High.
**Divergence:** `reception-control-tower` is drifting past "utility" — it has a database (D1), an LLM integration, and its own auth. That's a small *application*, not an edge utility.
**Consequence:** Harmless today (it works, it's protected), but it sets the precedent question the decision rules must answer: when is a Worker app legitimate? (Answer proposed: when the app is small, JS-native, low-data, and benefits from Access + custom domain — reception qualifies; anything BigQuery-heavy does not.)

### Inference: Cloudflare Access is the intended staff-auth layer for the edge plane — not (yet) a replacement for IAP
**Observed:** One Access app (reception), policy = org domain + owner gmail; `roles.py` already parses the Access header; bilancini scaffold ports the JWT check; vetrina plan Task 9 specified Access before retirement.
**Inferred intent:** Access gates everything on `panorama-host.com`; IAP gates the Cloud Run hub. Two gates, one per plane, both resolving the same Google identities.
**Confidence:** Medium-high for the dual-plane model; low for any intent to *unify* on one gate.
**Divergence:** `mutui-tracker` predates the model and sits on neither gate (public workers.dev).
**Consequence:** The dual model is coherent and cheap; the real gap is mutui's non-membership and the absence of a written rule saying which gate applies when.

### Inference: Cloud Run IAM was intended to protect the origin independently — and does
**Observed:** invoker = IAP service agent only; verified 302 on both run.app URLs. README instructs verifying the 302 after every deploy.
**Inferred intent:** Origin-level enforcement, not edge-only trust.
**Confidence:** High. **Divergence:** none. **Consequence:** This is the pattern to preserve; the audit's warning against "protected only at the edge" is already satisfied on the GCP plane. On the Cloudflare plane, reception matches it in spirit (in-Worker JWT verification + workers.dev disabled — the Worker *is* the origin).

### Inference: the hub is the intended application registry and navigation surface
**Observed:** `registry.py` ("una sola fonte di verità", 1 app = 1 row), grants in `roles.py`, tiles for external apps (`bind`), the hub-bind skill making registration the mandatory path.
**Inferred intent:** Every staff-facing surface is *discoverable and governed* through the registry, even when it runs elsewhere (Mutui embed, Banche Looker bind).
**Confidence:** High.
**Divergence:** `reception-control-tower` is live but absent from the registry (no tile, no grant row) — confirmed by the operator as an app "che metto nel hub" in intent. `finanzaorti.com` and the Pages projects are entirely outside it.
**Consequence:** The registry is the natural seed of the service inventory; divergence is harmless per-app but erodes the "one place to see everything" property the hub was built for.

### Inference: `panorama-host.com` is the intended canonical hostname namespace
**Observed:** Zone active, one record (`reception.`), bilancini scaffold hard-codes `bilancini.panorama-host.com`; `panoramagroup.it` is deliberately *not* on Cloudflare (STATUS 06-20 note).
**Inferred intent:** A Cloudflare-controlled, org-neutral namespace for staff apps, decoupled from the corporate website domain.
**Confidence:** Medium (two data points, no written decision).
**Divergence:** The two largest surfaces (hub, mutui) don't use it; workers.dev and run.app URLs circulate instead.
**Consequence:** Hostnames are currently traceable only through the audit inventory, not through a naming convention. Completing the namespace is cheap and high-clarity.

### Inference: KV is a publish-target / shared-document store, not an improvised database
**Observed:** One namespace, one key (`current`), single JSON scenario document, admin-token writes, explicit ontology in mutui issue #2 ("tracker=fatti, piano=proiezioni"); bilancini scaffold plans KV as BQ→edge publish target (`/data.json`).
**Inferred intent:** KV holds small, derived or explicitly non-canonical documents at the edge — consistent with the 2026-06-19 governance decision that projections stay out of the BigQuery `f_*` pool.
**Confidence:** High.
**Divergence:** The scenario document is nonetheless a *system of record* with no backup/export.
**Consequence:** Acceptable usage, missing durability ritual (harden, not redesign).

### Inference: Google Cloud project layout is deliberate at the center, accumulated at the edges
**Observed:** `hotelops-suite` holds everything HotelOps; the 4 named sibling projects have Cloud Run disabled and serve other experiments; ~40 `sys-*` are Apps-Script artifacts.
**Inferred intent:** One project per product; no environment/sensitivity split intended at this scale.
**Confidence:** High for hotelops-suite; the siblings are historical accumulation (harmless).
**Consequence:** No consolidation needed; a rule for *new* projects is needed so accumulation doesn't continue silently.

### Inference: deployments were intended to be automated *eventually*; manual is a conscious interim
**Observed:** Zero deploy CI (0 Cloud Build triggers, Actions = tests only), but idempotent `scripts/cloud/*.sh`, README deploy rituals, and repeated "automation later" notes in plans.
**Inferred intent:** Manual-first to ship, automation when the ritual becomes a liability.
**Confidence:** High.
**Divergence:** The liability threshold has arguably been crossed: deploys depend on one laptop's `gcloud`/`wrangler` login state, the audit found a Worker nobody remembers deploying (GAP-001), and jobs are pinned to stale image tags (v1–v3) that only a manual rebuild refreshes.
**Consequence:** This is the highest-leverage standardization in the target architecture.

### Inference: environment separation was intentionally omitted
**Observed:** local (`streamlit run`, `HUB_DEV_ALLOW_ALL=1`) and production; no staging anywhere; production BigQuery is used from local dev.
**Inferred intent:** Two-environment minimalism, accepted risk for a one-operator shop.
**Confidence:** High.
**Divergence:** none vs intent; the gap vs *safety* shows up as "merge gates" in process (CLAUDE.md: no hub page merges without Stefano seeing real-data render) instead of infrastructure.
**Consequence:** Keep the minimalism; add the free native middle ground (Cloud Run revision tags) rather than a staging stack.

### Inference: infrastructure ownership is implicit and personal — the largest unstated assumption
**Observed:** Cloudflare account, GitHub account (`ste-hue`), wrangler/gcloud logins, SA key files, `.env`, and two **remote-less git repos** all resolve to one person and one machine. The IAP fix history (custom OAuth client) exists only in STATUS/README prose.
**Inferred intent:** None — this is unexamined default, not design.
**Confidence:** High.
**Consequence:** Continuity risk (P0-adjacent). The target must make ownership explicit and remove single-machine state, without pretending a team exists that doesn't.

### Inference: direct run.app URLs are pragmatic, not intended as final
**Observed:** Hub circulated via run.app (README: "chi ha già il link non va riavvisato"); legacy alias still referenced in committed `apps.json`.
**Inferred:** Acceptable interim because IAP rides on run.app for free and `panoramagroup.it` isn't on Cloudflare.
**Confidence:** Medium. **Consequence:** Acceptable to keep (documented exception) or complete via domain mapping later; not urgent.

### Inference: application-level authorization is coherent — and is the layer intended to survive any edge change
**Observed:** `roles.py` grants with S1/S2 invariants + import-time tripwires; sensitive apps named explicitly; same grant model consumed regardless of which edge header supplies identity.
**Inferred intent:** Edge answers "who enters", app answers "who sees what" — deliberately independent layers.
**Confidence:** High. **Divergence:** reception implements its own (JWT-derived) authorization separately — acceptable for a satellite, but there are now two grant vocabularies.
**Consequence:** Keep `roles.py` as the model; don't centralize authorization into Cloudflare.

## 7. Historical accumulation and accidental complexity (observed)

| Item | Class |
|---|---|
| Stale public Worker `hotelops-hub` (frozen 2026-06-18) | leftover of the vetrina experiments; contradicts STATUS.md |
| `verticals/hub/publish/` + vetrina wrangler config + stale `apps.json` | retired-runtime source remnants |
| `verticals/condges/Dockerfile` (paths that no longer exist) | pre-`verticals/` fossil |
| Pages `finanza-react-app` (direct upload, 2025-08) | superseded duplicate of `finanza` |
| `~/dev/Projects/finanza/app-mutui` | superseded local copy |
| Jobs image tags v1/v2/v3 drifting from repo HEAD | accumulation by omission (no rebuild trigger) |
| 4 named + ~40 `sys-*` sibling GCP projects | benign accumulation outside HotelOps |

## 8. Components with unclear purpose

1. **Worker `hotelops-hub`** — no owner, no source mapping, no deploy record (GAP-001). Retirement candidate pending a 10-minute verification.
2. **`bilancini` Worker scaffold vs live hub Bilancini page** (GAP-004) — same name, two surfaces, two auth models; intent split unrecorded.
3. **`finanzaorti.com`** (GAP-003) — public finance-named site, last deployed 2025-08, no local checkout.
4. **NanoClaw** (GAP-006) — ingest-capable channel with unknown runtime.
5. **`panorama_apps/reception` (Python)** — apparent predecessor of the control tower; runtime unknown.

## 9. Security-model interpretation

The *de facto* model, made explicit: **two planes, one identity source, three layers.**

- **Plane A (Google):** run.app hostname → IAP (custom OAuth client; allowlist domain + named externals) → Cloud Run (invoker = IAP agent only) → `roles.py` grants. Verified end-to-end. Weakness is not the gate but the **blast radius behind it** (default compute SA with project `roles/editor` — SEC-002) and the **allowlist/documentation mismatch** (SEC-004: whole org can *enter*, README says per-email; grants fail closed, so the practical effect is org users see an empty hub).
- **Plane B (Cloudflare):** `panorama-host.com` hostname → Access (org domain + owner) → Worker verifying the Access JWT itself, workers.dev disabled. Also correct — notably, it independently satisfies "don't trust the edge alone".
- **Unassigned:** `mutui-tracker` (public by inertia, writes token-gated) and `finanzaorti.com` (public, purpose unclear). These aren't broken layers; they're surfaces that never got assigned to a plane.

Interpretation (inferred, high confidence): the operator understands layered auth well — both planes independently verify at origin. The problems are *classification* problems (which surface belongs to which plane) and *least-privilege* problems (the hub's SA), not conceptual ones.

## 10. Deployment-model interpretation

Everything ships by hand from one authenticated laptop: `gcloud run deploy --source .` (hub), `scripts/cloud/*.sh` then tag-pinned jobs, `npx wrangler deploy` (Workers), Pages via GitHub integration (the only automated path — and, tellingly, the only one that never produced an orphan). The manual ritual has produced exactly the failure modes automation prevents: an orphan Worker, image tags drifting from source, deploy knowledge living in READMEs and memory, and a hard dependency on one machine's credential state. Intent was "automate later" (inferred, high confidence); *later has arrived* (recommended).

## 11. Confidence summary and unresolved assumptions

| Conclusion | Confidence |
|---|---|
| Cloud Run = intended standard runtime; Workers = satellites | High |
| Dual-plane auth (IAP for GCP plane, Access for CF plane) is the intended end-state | Medium |
| `panorama-host.com` = intended canonical namespace | Medium |
| KV = publish/shared-document store by design | High |
| Manual deploys were interim, not doctrine | High |
| mutui-tracker public exposure is inertia, not decision | Medium (no decision record found either way) |
| bilancini Worker = intended Access-gated twin for non-Streamlit consumption | Low — must be asked, not inferred |

**Unresolved assumptions carried into the target:** (1) the operator wants satellites consolidated under `panorama-host.com` + Access; (2) org-account migration (Cloudflare/GitHub) is acceptable eventually but not urgent; (3) reception's D1/AI footprint is a deliberate exception, not the new default. Each is flagged where it affects a recommendation.
