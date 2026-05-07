-- v_raw_promotion_status: per-source × status counts for operational visibility.
-- Complements hotelops lineage --list and ad-hoc funnel queries.
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_raw_promotion_status` AS
SELECT
  COALESCE(r.source_name, '(unclassified)') AS source_name,
  COALESCE(c.current_status, 'RAW_ONLY') AS status,
  COUNT(*) AS n_objects,
  MIN(r.intake_at) AS oldest_intake_at,
  MAX(r.intake_at) AS latest_intake_at
FROM `hotelops-suite.hotelops.f_raw_objects` AS r
LEFT JOIN `hotelops-suite.hotelops.v_raw_objects_current` AS c
  USING (raw_object_id)
GROUP BY
  COALESCE(r.source_name, '(unclassified)'),
  COALESCE(c.current_status, 'RAW_ONLY')
ORDER BY source_name, status;
