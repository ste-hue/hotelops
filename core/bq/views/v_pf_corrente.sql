-- v_pf_corrente — generazione corrente di f_piano_finanziario_input.
--
-- fonte PIANO_FINANZIARIO: le righe sono generazionali (una per file post-rotate
-- ingerito, chiave raw_object_id). Qui si collassa a latest-generation-wins per
-- (societa_id, voce_id, anno, mese). Righe pre-lineage (raw_object_id NULL) hanno
-- data_caricamento più vecchio e perdono naturalmente.
--
-- Tutte le altre fonti (CLI, APP, PARTITE, SCADENZIARIO, BVA_2026): pass-through.
-- La priorità tra fonti NON vive qui — resta in v_piano_finanziario_mensile.
-- Spec: docs/superpowers/specs/2026-06-12-pf-generazionale-design.md
WITH generazioni AS (
  SELECT
    *,
    ROW_NUMBER() OVER (
      PARTITION BY societa_id, voce_id, anno, mese
      ORDER BY data_caricamento DESC, raw_object_id DESC
    ) AS rn
  FROM `hotelops-suite.hotelops.f_piano_finanziario_input`
  WHERE fonte = 'PIANO_FINANZIARIO'
)

SELECT * EXCEPT (rn) FROM generazioni WHERE rn = 1

UNION ALL

SELECT *
FROM `hotelops-suite.hotelops.f_piano_finanziario_input`
WHERE fonte != 'PIANO_FINANZIARIO'
