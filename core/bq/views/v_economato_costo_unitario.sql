-- v_economato_costo_unitario: Costo unitario per persona (pax-notte) per reparto × articolo × mese
--
-- Mario (ECONOMATO) uses this to see:
--   "quanto costa una cosa a persona, per reparto × mese"
--
-- Thin wrapper on f_coefficienti_consumo (già aggregato a quel grain).
-- Denominatore: pernottamenti (pax × notti) — sempre. NON coperti.
-- Motivo: coperti non ha denominatore pulito per reparti non-F&B (HSK, manutenzione).
-- Pernottamenti è una scala uniforme che funziona per ogni reparto.
--
-- Agnostico sull'anno: appena f_coefficienti_consumo viene popolato con 2026,
-- le righe appaiono automaticamente e il confronto YoY funziona lato Looker
-- (stesso anno, mese, reparto, articolo → affiancati).
--
-- Grain: una riga per (societa, anno, mese, reparto, descrizione_articolo)

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_economato_costo_unitario` AS

WITH mese_labels AS (
  SELECT offset + 1 AS mese, label AS mese_label
  FROM UNNEST([
    'Gennaio','Febbraio','Marzo','Aprile','Maggio','Giugno',
    'Luglio','Agosto','Settembre','Ottobre','Novembre','Dicembre'
  ]) AS label WITH OFFSET AS offset
),

reparto_labels AS (
  SELECT code, label FROM UNNEST([
    STRUCT('BRK' AS code, 'Colazione' AS label),
    ('CUCINA', 'Cucina'),
    ('BAR_HOTEL', 'Bar Hotel'),
    ('BAR_BEACH', 'Bar Spiaggia'),
    ('CANTINA', 'Cantina'),
    ('BANCHETTI', 'Banchetti'),
    ('EVENTO', 'Eventi'),
    ('DIPENDENTI', 'Mensa Dipendenti'),
    ('HSK_HOTEL', 'Housekeeping Hotel'),
    ('HSK_AR', 'Housekeeping Residence'),
    ('HSK_CVM', 'Housekeeping CVM'),
    ('DIREZIONE', 'Direzione'),
    ('LAVANDERIA', 'Lavanderia'),
    ('RECEPTION', 'Reception'),
    ('MANUTENZIONE', 'Manutenzione'),
    ('AMMINISTRAZIONE', 'Amministrazione'),
    ('SPIAGGIA', 'Spiaggia/Lido'),
    ('PISCINA', 'Piscina'),
    ('SPA', 'SPA'),
    ('IMBARCAZIONE', 'Imbarcazione'),
    ('DEPERIMENTO', 'Deperimento'),
    ('SPESE', 'Spese generali'),
    ('ECONOMATO', 'Economato'),
    ('SERVIZI', 'Servizi'),
    ('SPA_WELLNESS', 'SPA/Wellness')
  ])
)

SELECT
  c.societa_id,
  c.anno,
  c.mese,
  DATE(c.anno, c.mese, 1)                            AS data_mese,
  ml.mese_label,
  CONCAT(LPAD(CAST(c.mese AS STRING), 2, '0'),
         ' ', LEFT(ml.mese_label, 3))                AS mese_sort_label,

  c.reparto,
  COALESCE(rl.label, c.reparto)                      AS reparto_label,

  c.categoria,
  c.classe,
  c.descrizione_articolo,
  c.unita_misura,

  c.pernottamenti,
  ROUND(c.quantita, 2)                               AS quantita,
  ROUND(c.importo, 2)                                AS importo,
  ROUND(c.coeff_per_pax, 6)                          AS coeff_per_pax,
  ROUND(c.costo_per_pax, 4)                          AS costo_per_pax,

  -- ABC ranking per (anno, mese, reparto) — posizione dell'articolo nel reparto di quel mese
  ROW_NUMBER() OVER (
    PARTITION BY c.anno, c.mese, c.reparto
    ORDER BY c.importo DESC
  )                                                  AS rank_in_reparto_mese,

  -- ABC ranking per (anno, reparto) — posizione dell'articolo nel reparto sull'intero anno
  DENSE_RANK() OVER (
    PARTITION BY c.anno, c.reparto
    ORDER BY y.importo_anno DESC
  )                                                  AS rank_in_reparto_anno

FROM `hotelops-suite.hotelops.f_coefficienti_consumo` c
LEFT JOIN mese_labels   ml ON ml.mese = c.mese
LEFT JOIN reparto_labels rl ON rl.code = c.reparto
LEFT JOIN (
  SELECT anno, reparto, descrizione_articolo, SUM(importo) AS importo_anno
  FROM `hotelops-suite.hotelops.f_coefficienti_consumo`
  GROUP BY 1, 2, 3
) y ON y.anno = c.anno AND y.reparto = c.reparto AND y.descrizione_articolo = c.descrizione_articolo
