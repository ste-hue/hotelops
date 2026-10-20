-- Coverage is per configured root, scoped to the same complete observation.
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_drive_coverage` AS
SELECT r.snapshot_date, covered_root AS root_key, r.file_id AS root_file_id, r.path,
  r.observer_email, r.permissions_observed,
  COUNT(DISTINCT m.file_id) AS objects,
  COUNTIF(NOT COALESCE(m.permissions_observed, FALSE)) AS permissions_unknown
FROM `hotelops-suite.hotelops.v_drive_inventory_current` r
CROSS JOIN UNNEST(r.inventory_root_keys) AS covered_root
LEFT JOIN `hotelops-suite.hotelops.v_drive_inventory_current` m
  ON covered_root IN UNNEST(m.root_keys)
GROUP BY r.snapshot_date, covered_root, r.file_id, r.path, r.observer_email, r.permissions_observed;
