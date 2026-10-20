-- v_drive_lineage: il ponte Drive ↔ lineage per hash (concept vault
-- DRIVE_HASH_LINEAGE_BRIDGE). Due famiglie di righe:
--   IN_ATTESA   file in una cartella di atterraggio `_inbox/<SOURCE>` senza
--               raw_object_id: aspetta il giro di drive_fetch, o ha un nome
--               che non porta il periodo;
--   RAW_NON_GCS raw object con raw_uri che non inizia per gs:// (I9 violata).
-- Spec: docs/superpowers/specs/2026-10-17-drive-agent-friendly-design.md

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_drive_lineage` AS

WITH ultimo AS (
  SELECT MAX(snapshot_date) AS snapshot_date FROM `hotelops-suite.hotelops.v_drive_inventory_current`
),
inbox AS (
  SELECT
    i.snapshot_date,
    'IN_ATTESA' AS stato,
    REGEXP_EXTRACT(i.path, r'/_inbox/([A-Z0-9_]+)/') AS source_name,
    i.file_id,
    i.name,
    i.path,
    i.md5,
    i.created_time,
    CAST(NULL AS STRING) AS raw_object_id,
    CAST(NULL AS STRING) AS raw_uri,
    REGEXP_CONTAINS(i.name, r'\d{4}-\d{2}') AS nome_con_periodo
  FROM `hotelops-suite.hotelops.v_drive_inventory_current` i
  JOIN ultimo USING (snapshot_date)
  WHERE NOT i.is_folder AND NOT i.is_shortcut
    AND REGEXP_CONTAINS(i.path, r'/_inbox/[A-Z0-9_]+/')
    AND i.raw_object_id IS NULL
),
raw_non_gcs AS (
  SELECT
    (SELECT snapshot_date FROM ultimo) AS snapshot_date,
    'RAW_NON_GCS' AS stato,
    r.source_name,
    CAST(NULL AS STRING) AS file_id,
    r.file_name_original AS name,
    CAST(NULL AS STRING) AS path,
    r.content_hash AS md5,
    r.intake_at AS created_time,
    r.raw_object_id,
    r.raw_uri,
    CAST(NULL AS BOOL) AS nome_con_periodo
  FROM `hotelops-suite.hotelops.f_raw_objects` r
  WHERE r.raw_uri IS NULL OR NOT STARTS_WITH(r.raw_uri, 'gs://')
)
SELECT * FROM inbox
UNION ALL
SELECT * FROM raw_non_gcs
ORDER BY stato, created_time;
