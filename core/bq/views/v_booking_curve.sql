-- v_booking_curve
-- Booking pace normalizzato per capacità (revman, issue #81).
-- Spec: docs/superpowers/specs/2026-07-11-revman-booking-curve-design.md
-- Grana: 1 riga = business_unit_id × mese_soggiorno × snapshot_date.
-- Base di misura: SEMPRE imponibile (vault BOOKING_PACE_E_BASI, basi omogenee).
-- Sequenza obbligatoria: selezione variante → aggregazione mensile → LAG
--   (mai window su righe alla granularità originaria).
-- Caveat:
--  * mesi già consumati: l'OTB include il consuntivo (la foto è "consumato +
--    futuro") — la curva ha senso pieno sui mesi >= mese della foto;
--  * aprile 2026 drogato dall'apertura anticipata (3/4 vs 16/4 2025): non si
--    aggiusta qui, si legge col benchmark giusto (concept §3);
--  * il benchmark LY assume calendario operativo comparabile: le colonne
--    diagnostiche ly_/cy_giorni_operativi e *_capacita_massima espongono
--    quando l'assunzione è debole (NON corrette in v1, solo esposte);
--  * gap_notti_target = notti mancanti al volume LY riproporzionato, NON la
--    capacità residua reale; adr_richiesto = ADR medio necessario su quelle
--    notti aggiuntive, non sulle camere fisicamente ancora disponibili.
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_booking_curve` AS
WITH source_ranked AS (
  -- una foto può esistere in più varianti dim_tipologia (stessa foto
  -- aggregata su dimensioni diverse — MAI sommarle): rank di preferenza
  SELECT
    DATE(snapshot_date) AS snapshot_date,
    business_unit_id,
    DATE(data)          AS data_soggiorno,
    camere,
    imponibile,
    DENSE_RANK() OVER (
      PARTITION BY snapshot_date, business_unit_id
      ORDER BY CASE dim_tipologia
        WHEN 'VENDUTA' THEN 1 WHEN 'ASSEGNATA' THEN 2 ELSE 3 END
    ) AS variante_rank
  FROM `hotelops-suite.hotelops.f_prenotazioni_otb`
),
selected_variant AS (
  SELECT * FROM source_ranked WHERE variante_rank = 1
),
otb_monthly AS (
  SELECT
    snapshot_date,
    business_unit_id,
    DATE_TRUNC(data_soggiorno, MONTH) AS mese_soggiorno,
    SUM(camere)     AS otb_notti,
    SUM(imponibile) AS otb_imponibile
  FROM selected_variant
  GROUP BY 1, 2, 3
),
otb_with_pickup AS (
  SELECT
    *,
    LAG(snapshot_date)  OVER w AS foto_precedente,
    LAG(otb_notti)      OVER w AS notti_foto_prec,
    LAG(otb_imponibile) OVER w AS imponibile_foto_prec
  FROM otb_monthly
  WINDOW w AS (
    PARTITION BY business_unit_id, mese_soggiorno
    ORDER BY snapshot_date
  )
),
pms_monthly AS (
  -- notti + diagnostiche calendario per BU × anno × mese (fonte statistiche)
  SELECT
    business_unit_id,
    EXTRACT(YEAR FROM DATE(data))  AS anno,
    EXTRACT(MONTH FROM DATE(data)) AS mese,
    SUM(camere_vendute)            AS notti,
    COUNTIF(camere_vendute > 0)    AS giorni_operativi,
    MAX(camere_totali)             AS capacita_massima
  FROM `hotelops-suite.hotelops.f_pms_statistiche`
  GROUP BY 1, 2, 3
),
room_revenue_monthly AS (
  -- ricavo camere imponibile per BU × anno × mese (decisione gate 2:
  -- 01ROOM di f_produzione_pms, NON revenue_room di f_pms_statistiche
  -- che è una base terza — ratio 1,09/1,04 vs 01ROOM)
  SELECT
    business_unit_id,
    EXTRACT(YEAR FROM DATE(data))  AS anno,
    EXTRACT(MONTH FROM DATE(data)) AS mese,
    SUM(importo_imponibile)        AS imponibile
  FROM `hotelops-suite.hotelops.f_produzione_pms`
  WHERE classe = '01ROOM'
  GROUP BY 1, 2, 3
),
ly_monthly AS (
  -- benchmark: l'anno N legge il PMS dell'anno N-1
  SELECT p.business_unit_id, p.anno + 1 AS anno_target, p.mese,
         p.notti AS ly_notti, r.imponibile AS ly_imponibile,
         p.giorni_operativi AS ly_giorni_operativi,
         p.capacita_massima AS ly_capacita_massima
  FROM pms_monthly p
  LEFT JOIN room_revenue_monthly r
    ON r.business_unit_id = p.business_unit_id
   AND r.anno = p.anno AND r.mese = p.mese
),
capacity_by_year AS (
  -- capacità dell'anno = capacità MODALE (valore più frequente) sui giorni
  -- operativi (camere_vendute > 0): robusta ai giorni di pre-apertura con
  -- inventario di config diverso (HOTEL mar 2025: 5 gg a 78) e alle
  -- anomalie puntuali (RESIDENCE 2025: giorni a 55)
  SELECT
    business_unit_id,
    EXTRACT(YEAR FROM DATE(data)) AS anno,
    APPROX_TOP_COUNT(camere_totali, 1)[OFFSET(0)].value AS capacita
  FROM `hotelops-suite.hotelops.f_pms_statistiche`
  WHERE camere_vendute > 0
  GROUP BY 1, 2
),
curve_metrics AS (
  SELECT
    o.snapshot_date,
    o.business_unit_id,
    o.mese_soggiorno,
    EXTRACT(YEAR FROM o.mese_soggiorno)  AS anno,
    EXTRACT(MONTH FROM o.mese_soggiorno) AS mese,
    -- 1. OTB (la foto)
    o.otb_notti,
    o.otb_imponibile,
    SAFE_DIVIDE(o.otb_imponibile, o.otb_notti) AS otb_adr,
    -- 2. pickup (foto vs foto precedente)
    DATE_DIFF(o.snapshot_date, o.foto_precedente, DAY) AS gg_tra_foto,
    o.otb_notti - o.notti_foto_prec           AS pickup_notti,
    o.otb_imponibile - o.imponibile_foto_prec AS pickup_imponibile,
    SAFE_DIVIDE(o.otb_notti - o.notti_foto_prec,
                DATE_DIFF(o.snapshot_date, o.foto_precedente, DAY)) AS pickup_notti_gg,
    SAFE_DIVIDE(o.otb_imponibile - o.imponibile_foto_prec,
                DATE_DIFF(o.snapshot_date, o.foto_precedente, DAY)) AS pickup_eur_gg,
    CASE
      WHEN o.notti_foto_prec IS NOT NULL
           AND (o.otb_notti - o.notti_foto_prec) > 0
      THEN (o.otb_imponibile - o.imponibile_foto_prec)
           / (o.otb_notti - o.notti_foto_prec)
    END AS adr_marginale,
    -- 3. LY, capacità, diagnostiche
    ly.ly_notti,
    ly.ly_imponibile,
    SAFE_DIVIDE(ly.ly_imponibile, ly.ly_notti) AS ly_adr,
    ly.ly_giorni_operativi,
    ly.ly_capacita_massima,
    cy.giorni_operativi AS cy_giorni_operativi_osservati,
    cy.capacita_massima    AS cy_capacita_massima,
    cap_cy.capacita        AS capacita_cy,
    SAFE_DIVIDE(cap_cy.capacita, cap_ly.capacita) AS cap_ratio,
    ly.ly_imponibile * SAFE_DIVIDE(cap_cy.capacita, cap_ly.capacita) AS target_imponibile,
    ly.ly_notti      * SAFE_DIVIDE(cap_cy.capacita, cap_ly.capacita) AS notti_attese
  FROM otb_with_pickup o
  LEFT JOIN ly_monthly ly
    ON ly.business_unit_id = o.business_unit_id
   AND ly.anno_target = EXTRACT(YEAR FROM o.mese_soggiorno)
   AND ly.mese        = EXTRACT(MONTH FROM o.mese_soggiorno)
  LEFT JOIN pms_monthly cy
    ON cy.business_unit_id = o.business_unit_id
   AND cy.anno = EXTRACT(YEAR FROM o.mese_soggiorno)
   AND cy.mese = EXTRACT(MONTH FROM o.mese_soggiorno)
  LEFT JOIN capacity_by_year cap_cy
    ON cap_cy.business_unit_id = o.business_unit_id
   AND cap_cy.anno = EXTRACT(YEAR FROM o.mese_soggiorno)
  LEFT JOIN capacity_by_year cap_ly
    ON cap_ly.business_unit_id = o.business_unit_id
   AND cap_ly.anno = EXTRACT(YEAR FROM o.mese_soggiorno) - 1
)
SELECT
  *,
  -- batteria: occupancy OTB vs capacità FISICA (il "luglio 80,7%" validato)
  SAFE_DIVIDE(otb_notti,
              capacita_cy * EXTRACT(DAY FROM LAST_DAY(mese_soggiorno))) AS saturazione_pct,
  -- progresso verso il volume LY riproporzionato (metrica diversa dalla batteria)
  SAFE_DIVIDE(otb_notti, notti_attese) AS avanzamento_volume_pct,
  target_imponibile - otb_imponibile   AS gap_target,
  notti_attese - otb_notti             AS gap_notti_target,
  CASE
    WHEN (notti_attese - otb_notti) > 0
    THEN (target_imponibile - otb_imponibile) / (notti_attese - otb_notti)
  END AS adr_richiesto
FROM curve_metrics
