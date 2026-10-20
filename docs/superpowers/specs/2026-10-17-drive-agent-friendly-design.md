# Drive acquisition and inventory — software contract

Date: 2026-10-17. Correction update: 2026-10-20. Audience: maintainers.
This public design describes the software contract. Runtime folder identifiers,
permission findings and business documents remain in private operational records.
It does not attest a cloud deployment, permission change or complete inventory.

Read AGENTS.md and the canonical architecture instructions first. I1 requires
validated writes; I2 requires explicit snapshot semantics; I5 keeps classification
deterministic; I9 governs raw provenance; I10 separates identity and authorization.

## Intended behavior

- Registry entries may identify one live Drive file or one intake folder, never
  both. Drive acquisition requires GCS raw storage. Native Google files need an
  explicit export MIME type.
- The scheduled fetch enumerates candidates, skips known content hashes and
  acquires new content through the existing intake gate. `--all` promotes only
  sources whose policy is AUTO. An explicit `--source-name` remains an operator
  action; `--no-promote` acquires only. Dry runs do not write pipeline receipts.
- Registry-resolved Drive intake requires actor `drive_sync`. This is a routing
  guard, not an IAM boundary, distributed lock or proof that arbitrary local
  files originated in Drive. Unclassified intake is not covered by this guard.
- Unsafe filename path components are rejected before download. Promotion
  rejection and partial failures must not produce a successful fetch receipt.
- The proposed daily inventory records metadata and permission observations.
  `hotelops drive status` and `manifest` render those observations; they do not
  approve access, alter sharing or establish that every folder was visible.
- Runtime roots and folder IDs come from a private YAML file selected by
  `HOTELOPS_DRIVE_MAP`. The committed template is empty and fails closed.

## Complete daily observations

Publication requires all roots in the current private map. A subset selected by
`--root` is inspection only and requires `--dry-run`; dry runs write neither raw
objects, inventory rows nor pipeline receipts. A traversal failure or Drive
`incompleteSearch` stops publication. Each root has its own observed row, even
when no children are visible. `root` is resolved to the authenticated principal's
actual root ID; it does not mean another user's Drive.

Rows are unique by `(snapshot_date, file_id)`. `root_keys` retains membership of
overlapping roots; `inventory_root_keys` identifies the configured root objects.
Publication calls `bq_write_validated` with one explicit DATE partition and
`natural_key=[snapshot_date]`. One `WRITE_TRUNCATE` load to `table$YYYYMMDD`
replaces that day, including deletions, without a preceding DELETE. The table
must already exist (`CREATE_NEVER`); schema inference is disabled. Validation
rejects rows outside the declared date before obtaining a client. Failed loads
retain the previous observation, and other days are untouched. The default
append and legacy snapshot branches of the gate are unchanged; this option
grants no actor identity, credentials or table authorization.

`v_drive_inventory_current` selects the newest complete observation with raw
provenance, consistent configured roots and observed root coverage. Legacy rows
without those fields are excluded. All inventory checks and manifests use this
selection; `v_drive_coverage` reports the same observation per root. Health
compares coverage with the current map, reports observation age, and returns
unavailable checks explicitly. A read does not renew the observation's date.
Malformed private-map YAML or structure is rejected by the loader as ValueError:
health reports unverifiable coverage, while inventory stops before any effects.

## Visibility and provenance

Completeness means completion of all configured traversals for the recorded API
principal. It cannot prove visibility of unshared objects or provide an atomic
point-in-time snapshot of a Drive tree changing during enumeration. Permission
fields absent or with hidden identities yield `permissions_observed=False`,
distinct from an observed empty list. Root permissions are observed separately;
unknown coverage remains visible in health and manifests, never a clean audit.

Exact API response pages, root metadata and the observed principal are retained
in a versioned JSON document through the existing intake/GCS path:
`gs://hotelops-raw/DRIVE_INVENTORY_GROUP_SNAPSHOT/YYYY/MM/drive-inventory.json`.
The raw manifest records its GCS generation. Each inventory row carries
`observation_raw_object_id`; the separate `raw_object_id` remains the MD5 bridge
to the business file's content. Acquisition of this metadata document is not
approval or promotion of any listed file. If raw capture succeeds but inventory
publication fails, the raw observation remains available without becoming the
current inventory.

## Known content and promotion recovery

Known hashes and deduplicated native exports consult `v_raw_objects_current`.
An unresolved rejection stays an error, including its reason, on later fetches.
Missing canonical state or a different source cannot imply promotion success.
The fetch does not download or automatically retry promotion of known content.
Recovery must use the existing governed reclassification/promotion path; only
its canonical `PROMOTED` state clears a pending promotion. `drive_sync` remains
a routing guard, never authentication or an ACL.

## Evidence and activation boundary

The six independently reproduced failures have regression coverage in
`tests/test_drive_regressions.py`. `tests/test_drive_snapshot.py` adds synthetic
complete reruns, deletion/empty roots, overlap, partial/unavailable traversal,
failed publication, unknown permissions, retained rejection and governed
recovery, exact API raw capture through the real intake with fake GCS/BQ clients,
partition scope and health coverage. Shared write-gate/intake/storage tests also
run offline. The external review probes remain unchanged. This evidence covers
Python behavior and load-job configuration, not a live BigQuery execution.

Before separately authorized activation, validate the additive inventory DDL
and SQL views against BigQuery. Apply the table schema first, then
`v_drive_inventory_current`, then `v_drive_coverage` and the four dependent
checks. Old draft rows are not backfilled or treated as complete. Supply the
private map and validate least-privilege runtime access, GCS generation retention
and visible coverage using that actual principal. Neither cloud setup nor SQL
execution was performed by this correction. The draft Cloud Run/Scheduler
script is not an activation instruction; preserve existing schedules until a
separate cutover is approved and verified.
