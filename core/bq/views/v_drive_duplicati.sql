-- v_drive_duplicati: stesso contenuto (md5) in più percorsi Drive, nell'ultima
-- fotografia di f_drive_inventory. Scorciatoie e cartelle escluse: una
-- scorciatoia è la risposta giusta a un duplicato, non un duplicato.
-- Spec: docs/superpowers/specs/2026-10-17-drive-agent-friendly-design.md

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_drive_duplicati` AS

WITH ultimo AS (
  SELECT MAX(snapshot_date) AS snapshot_date FROM `hotelops-suite.hotelops.f_drive_inventory`
),
file AS (
  SELECT i.*
  FROM `hotelops-suite.hotelops.f_drive_inventory` i
  JOIN ultimo USING (snapshot_date)
  WHERE NOT i.is_folder AND NOT i.is_shortcut AND i.md5 IS NOT NULL
),
gruppi AS (
  SELECT
    md5,
    COUNT(*) AS copie,
    MIN(created_time) AS prima_copia,
    ARRAY_AGG(STRUCT(file_id, path, owner_email, created_time) ORDER BY created_time) AS percorsi
  FROM file
  GROUP BY md5
  HAVING COUNT(*) > 1
)
SELECT
  f.snapshot_date,
  f.md5,
  g.copie,
  f.name,
  f.size_bytes,
  f.path,
  f.file_id,
  f.owner_email,
  f.created_time,
  f.created_time = g.prima_copia AS e_la_prima,
  f.raw_object_id,
  g.percorsi
FROM file f
JOIN gruppi g USING (md5)
ORDER BY g.copie DESC, f.md5, f.created_time;
