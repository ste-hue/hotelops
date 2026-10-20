-- v_drive_permessi: cosa è visibile fuori. Oggetti con permesso «chiunque con
-- il link» o condivisi con indirizzi fuori dal dominio, nell'ultima fotografia.
-- Spec: docs/superpowers/specs/2026-10-17-drive-agent-friendly-design.md

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_drive_permessi` AS

SELECT
  i.snapshot_date,
  i.file_id,
  i.name,
  i.path,
  i.is_folder,
  i.owner_email,
  i.perm_anyone,
  i.perm_outside_domain,
  CASE
    WHEN NOT COALESCE(i.permissions_observed, FALSE) THEN 'NON_OSSERVATI'
    WHEN i.perm_anyone THEN 'ANYONE'
    ELSE 'FUORI_DOMINIO'
  END AS esposizione,
  i.modified_time
FROM `hotelops-suite.hotelops.v_drive_inventory_current` i
WHERE NOT COALESCE(i.permissions_observed, FALSE) OR i.perm_anyone OR ARRAY_LENGTH(i.perm_outside_domain) > 0
ORDER BY i.perm_anyone DESC, i.path;
