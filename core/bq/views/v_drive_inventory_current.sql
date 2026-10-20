-- The single selection rule: only fully published observations with observed
-- roots, an API principal and raw provenance. Legacy/partial drafts are excluded.
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_drive_inventory_current` AS
WITH observations AS (
  SELECT snapshot_date, observation_raw_object_id, MAX(observed_at) AS observed_at,
    ANY_VALUE(configured_roots) AS expected,
    ARRAY_CONCAT_AGG(inventory_root_keys) AS covered,
    COUNT(DISTINCT TO_JSON_STRING(configured_roots)) AS configurations,
    COUNTIF(observer_email IS NULL OR observed_at IS NULL OR ARRAY_LENGTH(configured_roots) = 0) AS incomplete
  FROM `hotelops-suite.hotelops.f_drive_inventory`
  WHERE observation_raw_object_id IS NOT NULL
  GROUP BY snapshot_date, observation_raw_object_id
), complete AS (
  SELECT * FROM observations
  WHERE incomplete = 0 AND configurations = 1
    AND NOT EXISTS (SELECT k FROM UNNEST(expected) k EXCEPT DISTINCT SELECT k FROM UNNEST(covered) k)
    AND NOT EXISTS (SELECT k FROM UNNEST(covered) k EXCEPT DISTINCT SELECT k FROM UNNEST(expected) k)
), latest AS (
  SELECT * FROM complete
  QUALIFY ROW_NUMBER() OVER (ORDER BY snapshot_date DESC, observed_at DESC) = 1
)
SELECT i.* FROM `hotelops-suite.hotelops.f_drive_inventory` i
JOIN latest USING (snapshot_date, observation_raw_object_id);
