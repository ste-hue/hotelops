-- v_budget: Budget mensile pivottato per cod_conto, 12 colonne mensili.
--
-- Reshape only — precedence/suppression live in v_budget_canonical.
-- Spec: docs/superpowers/specs/2026-04-17-budget-fonte-priority-design.md

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_budget` AS

SELECT
  societa_id,
  anno,
  cod_conto,
  codice_conto_display,
  descrizione,
  tipo_costo,
  categoria_ce,
  fonte,
  SUM(IF(mese =  1, importo, 0)) AS gen,
  SUM(IF(mese =  2, importo, 0)) AS feb,
  SUM(IF(mese =  3, importo, 0)) AS mar,
  SUM(IF(mese =  4, importo, 0)) AS apr,
  SUM(IF(mese =  5, importo, 0)) AS mag,
  SUM(IF(mese =  6, importo, 0)) AS giu,
  SUM(IF(mese =  7, importo, 0)) AS lug,
  SUM(IF(mese =  8, importo, 0)) AS ago,
  SUM(IF(mese =  9, importo, 0)) AS sett,
  SUM(IF(mese = 10, importo, 0)) AS ott,
  SUM(IF(mese = 11, importo, 0)) AS nov,
  SUM(IF(mese = 12, importo, 0)) AS dic,
  SUM(importo) AS totale_annuo
FROM `hotelops-suite.hotelops.v_budget_canonical`
GROUP BY
  societa_id, anno, cod_conto, codice_conto_display,
  descrizione, tipo_costo, categoria_ce, fonte
ORDER BY societa_id, categoria_ce, cod_conto;
