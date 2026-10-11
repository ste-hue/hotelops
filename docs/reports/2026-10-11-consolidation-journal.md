# Consolidation journal — HotelOPS ecosystem (started 2026-10-11)

Execution journal for the cross-repo consolidation brief (Vault Loop single
source, PR audit, architecture coherence, incremental reconciliation, cloud
readiness). Resume from the **last verified checkpoint** below; do not repeat
completed audits. Everything here was verified in-session unless marked
*not verified*.

## Checkpoint 1 — 2026-10-11 (session `session_01Pwwt8NnFbyB2ZyRTFf8Wvv`)

### Current truth (inventory)

Repos: `hotelops` main `b1492a9` (public); `mgmt-os` main `e7b5f58` (private, pulled
+13); `mutui-tracker` main `6ef260c` (last push 2026-07-17; local clone
`~/dev/Projects/app-mutui` is 4 commits ahead, unpushed, incl. `962fada` 2026-09-02);
`panorama-businessplan` = one xlsx (July version, superseded by the "BP Solo Terzo"
of Sept/Oct); vault = private repo `ste-hue/obsidian-vault` master `a8c027e`, **14
files modified locally and uncommitted** (INDEX, PLATFORM, 8 workstreams, log.md…).
Local-only branch `feat/freshness-contract` (16 commits, 27 files, no PR, not pushed).
`gcloud` auth expired: Cloud Run jobs / Scheduler / BigQuery **not verified** this
session.

| Capability | State | Evidence |
| --- | --- | --- |
| Vault Loop spec | one canonical file after PR #143; `.agents` adapter | `.claude/commands/vault-loop.md`, PR #143 (+ fix `a88ef6c`) |
| Regia Worker `regia.panorama-host.com` | deployed, KV `html` is the **2026-10-06 export, pre PR #20/#21/#25** | Cloudflare bundle = `panorama_apps/regia/src/index.js`; `mgmt publish --history` empty |
| Regia shared backend (`mgmt.shared_server`, PR #21) | merged, **never deployed**, no deploy artefact, PyJWT tests skipped locally | `docs/regia-shared-state.md`; mgmt-os #16 open |
| Regia DB | SQLite on Stefano's laptop (`~/dev/Projects/mgmt_os/.mgmt/mgmt.db`) | not shared, no backup policy |
| Budget camere base (`hotelops budget base`) | implemented + 29 tests; xlsx only, no BQ, no versions | PR #130, `verticals/condges/budget_camere/` |
| Budget versions/approval, `f_budget_bozze`, budget API, 3 CdG→Regia views | **spec only** (PR #134/#135); plan for "piano 2" never written | hotelops #137/#138 open |
| Old budget retirement (decision 2026-10-04) | documented only: `bva`, `v_piano_finanziario_mensile` budget column still read `f_budget_mensile` | `cli.py`, `core/bq/views/` |
| `v_piano_finanziario_mensile` "budget lottery" (P1 in STATUS) | **fixed** `ac6f297` + PR #124, issue #70 closed; STATUS was stale → corrected | `core/bq/views/v_piano_finanziario_mensile.sql` |
| Canone engine | 22 tests green; cloud job `canone-push` defined in `scripts/cloud/80_canone.sh`; runs *not verified* | `verticals/condges/canone_sim.py` |
| Piano Industriale | 4 independent engines (mutui-tracker JS E1-E3, `canone_sim`, BP xlsx generator) + mgmt-os reader + PR #26 prototype; **debt service exists in 3 copies**, no contract | mutui-tracker issue #3 |
| `app_cdg` retirement (#140) | file + hub mount `kind="soon"` + `hotelops app pf` still present; registry comment says "in redesign" | `verticals/hub/registry.py:70-72` |
| Tests hotelops | 1393 passed (`~/.virtualenvs/hotelops_core`, `-m "not bq"`); `.venv` lacks optional deps | run 2026-10-11 |
| Tests mgmt-os | 360 passed, 9 skipped (PyJWT missing) | run 2026-10-11 |

### PR audit (hotelops unless noted)

| PR | Verdict | Done | Needs Stefano |
| --- | --- | --- | --- |
| [#143](https://github.com/ste-hue/hotelops/pull/143) Vault Loop single source | FIX THEN MERGE | fix pushed `a88ef6c` (I3 kept explicit, scoped to business names; vault path casing); checks green | **merge** |
| [#117](https://github.com/ste-hue/hotelops/pull/117) signature engine | MERGE | main merged into branch (`08854e6`, STATUS.md kept from main); 1393 tests green on merged tree; MERGEABLE | **merge** |
| [#106](https://github.com/ste-hue/hotelops/pull/106) portable paths | FIX THEN MERGE | README venv note restored (`copilot/github-actions-explanation` HEAD), title/body fixed, undrafted; 1384 green on merged tree | **merge** |
| [#97](https://github.com/ste-hue/hotelops/pull/97) stale Zapier gitlink | MERGE | nothing to fix (still draft) | **undraft + merge** |
| [#107](https://github.com/ste-hue/hotelops/pull/107) hub lazy loading | CLOSE | closed with rationale; `_lazy_page_target` + test named for reuse; branch kept | — |
| [#60](https://github.com/ste-hue/hotelops/pull/60) runtime state → BQ/GHA | CLOSE | closed; problem preserved as [#144](https://github.com/ste-hue/hotelops/issues/144); branch kept | — |
| [mgmt-os #26](https://github.com/ste-hue/mgmt-os/pull/26) growth-driver prototype | KEEP OPEN (recommend close without merge) | untouched | decide: merging a revenue calculator into the Regia repo seeds a second financial truth (#22) |

Merging was blocked for the agent by the auto-mode policy ("merge without
review"); all four MERGE candidates are prepared and green.

### Architecture decisions landed in this checkpoint

- ADR 0005 `docs/adr/0005-ai-native-operating-infrastructure.md`: durable vs
  replaceable components; one owner per truth; gates for mutations; drift measured.
- `AGENTS.md` / `CLAUDE.md` point to ADR 0005 and to the single Vault Loop spec;
  `CLAUDE.md` invariant count corrected (I1–I10).
- Vault Loop incremental tool: `scripts/vault_loop/reconcile.py`,
  `meta/vault-loop/{sources.yaml,README.md,vault-loop.yml}`, spec
  `docs/superpowers/specs/2026-10-11-vault-loop-incremental-design.md`,
  11 tests `tests/test_vault_loop_reconcile.py` (validation matrix 1-10 of the brief).
- Repo doc pointers fixed (dead `code_paths` in `docs/procedures/*`, `docs/protocols/*`).

### Validation results

Simulated (pytest): consistent world → CURRENT with no findings; stale "I1–I8"
claim traced to file + authority; repo architecture change without vault note →
REVIEW REQUIRED, resolves once cited; archived note edited → REVIEW REQUIRED, tool
never writes (tree hash unchanged); missing source → SOURCE UNAVAILABLE, its
checkpoint held, others advance; two runs idempotent (same IDs/states/SHAs);
crashing check → NOT VERIFIED, checkpoint held, findings not auto-resolved;
dirty tree checked but held; mgmt-os change attributed to mgmt-os authority;
pointer/wikilink mechanics; secrets/e-mails redacted from the report.

Real run (local, all three sources, all dirty → every checkpoint held, honest):
overall DRIFT DETECTED; open findings 147 (84 broken wikilinks LOW, 28 dead repo
pointers LOW, 17 repo-doc freshness, 11 archived-as-active MED, 7 stale "I1–I8/I9"
claims MED); second run: 147 open, 0 resolved, same IDs → idempotent on real data.
BigQuery: NOT VERIFIED (by design). Existing suite unaffected: 1392 passed on the
branch (one `bq`-independent test count change is PR #117's, not this branch).

### Vault lint (agent-run Mode C, 19 findings, 6 HIGH) — proposals, nothing written

HIGH: mgmt-os 2026-10-07..09 (shared state, mutation boundary, journal review) has
no vault trace; `app_cdg` cited as live CdG surface in LOOPS/PLATFORM/INDEX/loops;
HUB.md describes retired vetrina + iframe as live; REVIEWS.md says Mac crontab
(runtime is Cloud Run); vault LINEAGE_ARCHITECTURE/GCS_INTEGRATION diverge from
ADR 0004 and `core/lineage` while "Active"; two different `INGESTION_TREE.md`.
MED: INDEX "I1–I8" + archived ENTITY_REVIEW as live protocol; stale vertical
statuses; PLATFORM ghost apps + "I0"; LOOPS commands/tables misnamed; "digital
twin" still in `INVARIANTS.md:22` / `AI_INSTRUCTIONS.md:16` (frame = Company OS
since 2026-05-02, no decision note); 13 decisions since July without
`## Implementation`; Architecture_Gaps_Audit_2026-05-10 never closed.
All require Stefano (locally modified files, historical decisions, invariant
wording). Proposed `log.md` line: `## [2026-10-11] lint | full vault — 19 findings
(6 HIGH) + deterministic run 147 open`.

### Decisions awaiting approval

1. Merge #143, #117, #106, #97 (prepared, green).
2. mgmt-os #26: close without merge (recommended) or strip HTML + amounts.
3. Cloud automation: copy `meta/vault-loop/vault-loop.yml` into the private
   vault repo, add secret `MGMT_OS_READ_TOKEN` (or drop mgmt-os), run once by
   hand; enable the weekly cron only after that run is reviewed.
4. Vault edits from the lint (above) — especially committing/pushing the 14
   local vault files first, otherwise cloud runs reconcile a stale vault.
5. `INVARIANTS.md` / `AI_INSTRUCTIONS.md` "digital twin" → "Company OS" needs a
   paired decision note (vault-loop anti-goal: never edit invariants silently).
6. `feat/freshness-contract` (16 local commits): push as backup / open PR / drop.
7. `app-mutui` local commits (4, unpushed, incl. per-intervento durata/preamm):
   push + deploy, then update KV scenario to the September perimeter.

### Next executable actions (ranked by correctness risk → dependency → e2e → effort)

1. **Budget truth**: write the "piano 2" plan (versions/approval, `f_budget_versioni`,
   3 views) and switch `bva` / PF budget column off the retired budget behind a
   flag — removes the competing truth between `f_budget_mensile` and mgmt-os «Numeri» (#137).
2. **Regia persistence**: decide where `mgmt.db` lives (Cloud Run + volume vs
   tunnel), deploy `shared_server`, add Worker proxy `/api/regia/*`, republish the
   Quadro (live page still has the P0 #16 bug); version `panorama_apps/regia` in git.
3. **Debt service contract**: `debt_service_<date>.json` from mutui-tracker E1 →
   fourth `impegno` source in `canone_fonti.py` (mutui-tracker #3) — no new engine.
4. Vault pointer sweep from the deterministic report (28 dead pointers, 7 stale
   invariant claims, 11 archived-as-active) once the local vault edits are committed.
5. Enable weekly cloud reconciliation after the first manual run.
