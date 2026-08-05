-- v_pec_novita: cosa il corpus non ha mai visto prima.
--
-- Il digest non calcola importanza (spec 2026-08-05, N1): risponde solo a
-- "l'ho gia' visto?". Tre campi, una regola sola — mittente, forma dell'oggetto
-- e forma dei nomi allegati, dove FORMA = il testo con ogni token che contiene
-- una cifra sostituito da '#'. Cosi' 'Pratica M26716Q2609 evasa' e
-- 'Pratica M26715Q2553 evasa' sono la stessa cosa vista due volte.
--
-- La storia e' il corpus stesso: la vista si autoaggiorna, nessuna tabella di
-- stato. La novita' e' RELATIVA AL MITTENTE, non globale: una forma rara in
-- assoluto ma abituale per quel mittente e' routine.
--
-- Base ristretta alla posta IN ARRIVO (N2): ACCETTAZIONE e CONSEGNA sono le
-- ricevute delle PEC che mandiamo noi, MESSAGGIO_INVIATO siamo noi.
--
-- "Mai visto" = prima riga della sua partizione (ROW_NUMBER = 1), ordinata per
-- data_caricamento con msgid a spareggio per determinismo. Niente NOT EXISTS
-- correlato ne' subquery scalari correlate: BigQuery non li de-correla, quindi
-- gli allegati arrivano da una CTE aggregata in LEFT JOIN.
--
-- La guardia `forma_allegati IS NOT NULL` su allegati_nuovi non e' cosmetica:
-- PARTITION BY raggruppa i NULL insieme, e senza guardia il primo messaggio
-- SENZA allegati di ogni mittente risulterebbe novita'.

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_pec_novita` AS

WITH allegati_per_msg AS (
  SELECT
    msgid,
    STRING_AGG(REGEXP_REPLACE(nome_file, r'\b\S*\d\S*\b', '#'), '|'
               ORDER BY nome_file) AS forma_allegati,
    ARRAY_AGG(nome_file ORDER BY nome_file) AS allegati
  FROM `hotelops-suite.hotelops.f_pec_allegati`
  GROUP BY msgid
),
base AS (
  SELECT
    m.msgid, m.mittente, m.subject, m.entity_id, m.casella,
    m.data_evento, m.data_caricamento,
    REGEXP_REPLACE(m.subject, r'\b\S*\d\S*\b', '#') AS forma_oggetto,
    ap.forma_allegati,
    IFNULL(ap.allegati, []) AS allegati
  FROM `hotelops-suite.hotelops.f_pec_messages` m
  LEFT JOIN allegati_per_msg ap USING (msgid)
  WHERE m.tipo = 'POSTA_CERTIFICATA' AND m.source_folder = 'RECEIVED'
)
SELECT
  * EXCEPT (rn_mittente, rn_oggetto, rn_allegati),
  rn_mittente = 1 AS mittente_nuovo,
  rn_oggetto = 1 AS oggetto_nuovo,
  forma_allegati IS NOT NULL AND rn_allegati = 1 AS allegati_nuovi
FROM (
  SELECT
    b.*,
    ROW_NUMBER() OVER (
      PARTITION BY mittente
      ORDER BY data_caricamento, msgid) AS rn_mittente,
    ROW_NUMBER() OVER (
      PARTITION BY mittente, forma_oggetto
      ORDER BY data_caricamento, msgid) AS rn_oggetto,
    ROW_NUMBER() OVER (
      PARTITION BY mittente, forma_allegati
      ORDER BY data_caricamento, msgid) AS rn_allegati
  FROM base b
)
