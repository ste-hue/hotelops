# Drive acquisition and inventory — draft awaiting acceptance

Date: 2026-10-17. Review update: 2026-10-18. Audience: maintainers.
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

## Merge and activation blockers from independent review

1. **Snapshot completeness and replacement.** Current `(snapshot_date, file_id)`
   replacement deletes only keys present in the new batch. A same-day rerun can
   retain disappeared files; overlapping roots can insert the same file twice.
   A partial `--root` run can also make the global newest date look complete.
   Decide and implement complete-run/root identity, empty-root semantics and
   publication of only complete observations before activation.
2. **Permission coverage and identity.** `root` means the authenticated
   principal's Drive. A service account does not inherit another user's root.
   Enumerating children omits the configured root's own permission record;
   absent permission metadata currently looks like no external sharing.
   Missing/insufficient coverage must remain unknown, not a green audit result.
3. **Promotion recovery.** A raw object acquired successfully but rejected during
   promotion is skipped as a known hash on the next fetch. Define recovery using
   canonical lineage state without duplicate intake or automatic approval.
4. **Raw provenance.** The inventory registry declares GCS raw storage while the
   implementation writes API-derived rows directly. Establish the metadata
   observation contract and raw capture or a documented applicable exception.
5. **Health completeness.** Object count currently spans all snapshot days;
   individual missing views can raise after the metadata query succeeds.
   Latest complete observation, staleness, partial visibility and unavailable
   checks must be represented explicitly.

## Required acceptance evidence

Use synthetic Drive/BQ clients first: identical rerun, changed/deleted/empty
folder, overlapping roots, partial traversal, permission metadata unavailable,
failed promotion followed by recovery, and dry run without writes. Confirm
only the intended observation scope is replaced and earlier dates survive.
No successful count or fresh date may hide an incomplete run.

The draft Cloud Run/Scheduler script is not an activation instruction. Before
any authorized activation, resolve the blockers above, review least-privilege
permissions, provide the private runtime map, build the intended image and
verify job output against the selected roots. Keep existing schedules until a
separate cutover has been approved and verified. Deployment and data mutation
are outside this code review.
