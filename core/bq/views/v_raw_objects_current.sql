CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_raw_objects_current` AS
WITH latest_event AS (
  SELECT
    raw_object_id,
    to_status        AS current_status,
    event_at         AS last_event_at,
    pipeline_run_id  AS last_pipeline_run_id,
    reason           AS last_rejection_reason,
    ROW_NUMBER() OVER (
      PARTITION BY raw_object_id
      ORDER BY event_at DESC, event_id DESC
    ) AS rn
  FROM `hotelops-suite.hotelops.f_lineage_events`
  WHERE to_status IS NOT NULL
)
SELECT
  ro.*,
  COALESCE(le.current_status, 'RAW_ONLY') AS current_status,
  le.last_event_at,
  le.last_pipeline_run_id,
  le.last_rejection_reason
FROM `hotelops-suite.hotelops.f_raw_objects` ro
LEFT JOIN latest_event le
  ON le.raw_object_id = ro.raw_object_id
  AND le.rn = 1;
