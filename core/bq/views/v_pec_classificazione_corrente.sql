-- v_pec_classificazione_corrente: ultima classificazione per msgid.
--
-- Precedenza: override umano (override_source = 'HUMAN') > ruleset più
-- recente (classified_at DESC). f_pec_classificazioni è APPEND-only — questa
-- vista è l'unica fonte di "verità corrente" per category/importance/
-- document_type (I-PEC-8).

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_pec_classificazione_corrente` AS

SELECT * EXCEPT (rn) FROM (
  SELECT c.*,
         ROW_NUMBER() OVER (
           PARTITION BY msgid
           ORDER BY (override_source = 'HUMAN') DESC, classified_at DESC
         ) AS rn
  FROM `hotelops-suite.hotelops.f_pec_classificazioni` c
)
WHERE rn = 1
