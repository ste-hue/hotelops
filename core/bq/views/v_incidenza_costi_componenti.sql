-- v_incidenza_costi_componenti — base di calcolo dell'incidenza costi/ricavi (COMPETENZA, bilancino).
--
-- Contratto: docs/reports/2026-10-18-cdg-stato-reale-e-incidenza-costi.md §6 (PR #158), issue #157.
-- Grana: una riga per (societa_id, anno, mese). Fonte: f_bilancino, tipo_conto='CE', saldo cumulato YTD.
--
-- COSA ESPONE: i COMPONENTI del rapporto (ricavi, costi per classe, i singoli conti che le varianti di
-- perimetro includono o escludono), sia come YTD diretto dello snapshot sia come delta mensile
-- aggregato. NON espone rapporti, soglie, semafori o un perimetro di default: le varianti
-- (Q1..Q5, R0; per classe / per natura) e il confronto con il limite versionato stanno in
-- verticals/condges/incidenza.py, che richiede perimetro, natura e periodo espliciti.
--
-- Segni: f_bilancino.saldo = dare - avere (ricavi < 0). Qui importo = -saldo per la sezione Ricavi,
-- +saldo per Costi: tutto positivo. Un conto senza categoria in d_categorie_conti resta nella sua
-- sezione (il denominatore non perde ricavi non mappati) e viene contato in n_conti_da_definire.
--
-- REGOLA DEL MESE (mai un cumulato spacciato per mese, mai un conto assente imputato a zero):
--   *_ytd    = somma dei saldi dello snapshot del mese (sempre, secondo la copertura dello snapshot).
--   delta_*  = ytd(m) - ytd(m-1) SOLO se mese_derivabile, altrimenti NULL.
--   mese_derivabile = (mese == gennaio, dove il delta coincide con lo YTD)
--                  OR (esiste lo snapshot del mese precedente adiacente nello stesso anno
--                      AND i due snapshot coprono lo stesso dominio di conti:
--                      n_conti_solo_prec = 0 AND n_conti_solo_corr = 0).
--   Motivo: un conto presente in m-1 e assente in m (o viceversa) puo' essere un giroconto, un
--   livello saltato dal parser o uno snapshot incompleto: non e' distinguibile dal dato, quindi il
--   mese non si deriva. I conteggi n_conti_solo_* restano visibili per spiegare il NULL.
--   mese_parziale = il bilancino e' stato caricato prima della fine del mese a cui si riferisce.
--
-- CONTI DICHIARATI (CTE regole, versione 2026-10-18 — cambiare qui, con test e nota nel contratto):
--   651101   canone affitto ramo d'azienda ORTI -> INTUR (intercompany; escluso per decisione 16/10)
--   65010591 fitto Angelina Residence ORTI -> INTUR (intercompany; esclusione da decidere)
--   65010590 sublocazione CVM da Panorama Company (esclusione da decidere)
--   75.01.07 / .90 / .91 / .92 / .94 / .97 / .98, 75.90.02  servizi bancari, POS, bollo c/c
--            (classe 75 ma natura di servizio, OIC 12 B7/B14): esposti a parte.
--   Il resto della classe 75 = oneri finanziari veri (interessi mutui, oneri diversi).

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_incidenza_costi_componenti` AS
WITH ce AS (
  SELECT
    societa_id,
    mese,
    codice_conto,
    REPLACE(codice_conto, '.', '') AS cod,
    SUBSTR(REPLACE(codice_conto, '.', ''), 1, 2) AS classe,
    sezione,
    saldo,
    data_ingresso
  FROM `hotelops-suite.hotelops.f_bilancino`
  WHERE tipo_conto = 'CE'
),
cat AS (
  SELECT DISTINCT REPLACE(codice_conto, '.', '') AS cod
  FROM `hotelops-suite.hotelops.d_categorie_conti`
),
regole AS (
  SELECT '651101'   AS cod, 'canone_651101'      AS componente UNION ALL
  SELECT '65010591',        'angelina_65010591'                UNION ALL
  SELECT '65010590',        'cvm_65010590'                     UNION ALL
  SELECT '750107',          'servizi_bancari_75'               UNION ALL
  SELECT '750190',          'servizi_bancari_75'               UNION ALL
  SELECT '750191',          'servizi_bancari_75'               UNION ALL
  SELECT '750192',          'servizi_bancari_75'               UNION ALL
  SELECT '750194',          'servizi_bancari_75'               UNION ALL
  SELECT '750197',          'servizi_bancari_75'               UNION ALL
  SELECT '750198',          'servizi_bancari_75'               UNION ALL
  SELECT '759002',          'servizi_bancari_75'
),
righe AS (
  SELECT
    c.*,
    r.componente,
    CASE WHEN c.sezione = 'Ricavi' THEN -c.saldo ELSE c.saldo END AS importo,
    (k.cod IS NULL) AS da_definire
  FROM ce c
  LEFT JOIN regole r USING (cod)
  LEFT JOIN cat k USING (cod)
),
agg AS (
  SELECT
    societa_id,
    mese,
    CAST(SUBSTR(mese, 1, 4) AS INT64) AS anno,
    CAST(SUBSTR(mese, 6, 2) AS INT64) AS mm,
    SUM(IF(sezione = 'Ricavi', importo, 0))                                        AS ricavi_totali_ytd,
    SUM(IF(sezione = 'Costi' AND classe BETWEEN '55' AND '71', importo, 0))        AS costi_55_71_ytd,
    SUM(IF(componente = 'canone_651101', importo, 0))                              AS canone_651101_ytd,
    SUM(IF(componente = 'angelina_65010591', importo, 0))                          AS angelina_65010591_ytd,
    SUM(IF(componente = 'cvm_65010590', importo, 0))                               AS cvm_65010590_ytd,
    SUM(IF(classe = '75' AND componente = 'servizi_bancari_75', importo, 0))       AS servizi_bancari_75_ytd,
    SUM(IF(classe = '75' AND componente IS NULL, importo, 0))                      AS oneri_finanziari_75_ytd,
    SUM(IF(sezione = 'Costi' AND classe IN ('73', '77'), importo, 0))              AS amm_imposte_73_77_ytd,
    SUM(IF(sezione = 'Costi', importo, 0))                                         AS costi_totali_ce_ytd,
    COUNT(*)                                                                       AS n_conti_ce,
    COUNTIF(da_definire)                                                           AS n_conti_da_definire,
    COUNTIF(sezione = 'Ricavi' AND da_definire)                                    AS n_ricavi_da_definire,
    MAX(data_ingresso)                                                             AS letto_il,
    ARRAY_AGG(cod)                                                                 AS conti
  FROM righe
  GROUP BY societa_id, mese
),
seq AS (
  SELECT
    a.*,
    LAG(mm)                       OVER w AS mm_prec,
    LAG(conti)                    OVER w AS conti_prec,
    LAG(ricavi_totali_ytd)        OVER w AS p_ricavi,
    LAG(costi_55_71_ytd)          OVER w AS p_costi_55_71,
    LAG(canone_651101_ytd)        OVER w AS p_canone,
    LAG(angelina_65010591_ytd)    OVER w AS p_angelina,
    LAG(cvm_65010590_ytd)         OVER w AS p_cvm,
    LAG(servizi_bancari_75_ytd)   OVER w AS p_servizi,
    LAG(oneri_finanziari_75_ytd)  OVER w AS p_oneri,
    LAG(amm_imposte_73_77_ytd)    OVER w AS p_amm,
    LAG(costi_totali_ce_ytd)      OVER w AS p_costi_tot
  FROM agg a
  WINDOW w AS (PARTITION BY societa_id, anno ORDER BY mm)
),
dom AS (
  SELECT
    s.*,
    (SELECT COUNT(*) FROM UNNEST(COALESCE(conti_prec, [])) c WHERE c NOT IN UNNEST(conti))      AS n_conti_solo_prec,
    (SELECT COUNT(*) FROM UNNEST(conti) c WHERE c NOT IN UNNEST(COALESCE(conti_prec, [])))      AS n_conti_solo_corr,
    (mm_prec IS NOT NULL AND mm - mm_prec = 1)                                                   AS mese_prec_adiacente
  FROM seq s
),
fin AS (
  SELECT
    *,
    (mm = 1 OR (mese_prec_adiacente AND n_conti_solo_prec = 0 AND n_conti_solo_corr = 0)) AS mese_derivabile
  FROM dom
)
SELECT
  societa_id,
  anno,
  mm AS mese,
  mese AS mese_str,
  ricavi_totali_ytd,
  costi_55_71_ytd,
  canone_651101_ytd,
  angelina_65010591_ytd,
  cvm_65010590_ytd,
  servizi_bancari_75_ytd,
  oneri_finanziari_75_ytd,
  amm_imposte_73_77_ytd,
  costi_totali_ce_ytd,
  IF(mese_derivabile, ricavi_totali_ytd       - COALESCE(p_ricavi, 0),       NULL) AS delta_ricavi_totali,
  IF(mese_derivabile, costi_55_71_ytd         - COALESCE(p_costi_55_71, 0),  NULL) AS delta_costi_55_71,
  IF(mese_derivabile, canone_651101_ytd       - COALESCE(p_canone, 0),       NULL) AS delta_canone_651101,
  IF(mese_derivabile, angelina_65010591_ytd   - COALESCE(p_angelina, 0),     NULL) AS delta_angelina_65010591,
  IF(mese_derivabile, cvm_65010590_ytd        - COALESCE(p_cvm, 0),          NULL) AS delta_cvm_65010590,
  IF(mese_derivabile, servizi_bancari_75_ytd  - COALESCE(p_servizi, 0),      NULL) AS delta_servizi_bancari_75,
  IF(mese_derivabile, oneri_finanziari_75_ytd - COALESCE(p_oneri, 0),        NULL) AS delta_oneri_finanziari_75,
  IF(mese_derivabile, amm_imposte_73_77_ytd   - COALESCE(p_amm, 0),          NULL) AS delta_amm_imposte_73_77,
  IF(mese_derivabile, costi_totali_ce_ytd     - COALESCE(p_costi_tot, 0),    NULL) AS delta_costi_totali_ce,
  mese_derivabile,
  NOT mese_derivabile AS mese_non_derivabile,
  mese_prec_adiacente,
  n_conti_solo_prec,
  n_conti_solo_corr,
  n_conti_ce,
  n_conti_da_definire,
  n_ricavi_da_definire,
  letto_il,
  SAFE.PARSE_DATE('%Y-%m-%d', SUBSTR(letto_il, 1, 10)) < LAST_DAY(DATE(anno, mm, 1)) AS mese_parziale
FROM fin
