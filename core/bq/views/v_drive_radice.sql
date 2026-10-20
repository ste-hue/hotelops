-- v_drive_radice: file sciolti fermi nelle radici che devono restare vuote
-- (inbox_only in core/drive_map.yaml: oggi solo «Il mio Drive»), più vecchi di
-- 7 giorni. Le cartelle non contano: la regola è «la radice ha solo cartelle».
-- Spec: docs/superpowers/specs/2026-10-17-drive-agent-friendly-design.md

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_drive_radice` AS

SELECT
  i.snapshot_date,
  i.root_key,
  i.file_id,
  i.name,
  i.mime_type,
  i.size_bytes,
  i.created_time,
  DATE_DIFF(i.snapshot_date, DATE(i.created_time), DAY) AS giorni_in_radice,
  i.raw_object_id
FROM `hotelops-suite.hotelops.v_drive_inventory_current` i
WHERE i.in_inbox_root
  AND NOT i.is_folder
  AND DATE(i.created_time) < DATE_SUB(i.snapshot_date, INTERVAL 7 DAY)
ORDER BY i.created_time;
