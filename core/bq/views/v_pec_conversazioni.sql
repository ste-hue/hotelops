-- v_pec_conversazioni: un messaggio PEC + il suo ciclo certificato.
--
-- Grana: una riga per messaggio "primario" (MESSAGGIO_INVIATO dal sent,
-- POSTA_CERTIFICATA dal received). Le ricevute (ACCETTAZIONE/CONSEGNA/ANOMALIA)
-- si agganciano via ref_msgid. Ogni semantica derivata ("direzione", stato)
-- vive QUI, non nei fatti (I8).

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_pec_conversazioni` AS

WITH ricevute AS (
  SELECT
    ref_msgid,
    MIN(IF(tipo = 'ACCETTAZIONE', data_evento, NULL)) AS data_accettazione,
    MIN(IF(tipo = 'CONSEGNA',     data_evento, NULL)) AS data_consegna,
    COUNTIF(tipo = 'CONSEGNA')                        AS n_consegne,
    COUNTIF(tipo = 'ANOMALIA')                        AS n_anomalie
  FROM `hotelops-suite.hotelops.f_pec_messages`
  WHERE ref_msgid IS NOT NULL
  GROUP BY ref_msgid
)

SELECT
  m.msgid,
  m.source_folder,
  CASE m.source_folder WHEN 'SENT' THEN 'INVIATA' ELSE 'RICEVUTA' END AS direzione,
  m.data_evento,
  m.data_certificata,
  m.mittente,
  m.destinatari,
  m.subject,
  m.n_allegati,
  r.data_accettazione,
  r.data_consegna,
  r.n_anomalie,
  CASE
    WHEN m.source_folder = 'RECEIVED'   THEN 'RICEVUTA'
    WHEN r.n_anomalie > 0               THEN 'ANOMALIA'
    WHEN r.data_consegna IS NOT NULL    THEN 'CONSEGNATA'
    WHEN r.data_accettazione IS NOT NULL THEN 'ACCETTATA'
    ELSE 'SENZA_RICEVUTE'
  END AS stato,
  m.casella,
  m.societa_id
FROM `hotelops-suite.hotelops.f_pec_messages` m
LEFT JOIN ricevute r
  ON r.ref_msgid = m.msgid
WHERE m.tipo IN ('MESSAGGIO_INVIATO', 'POSTA_CERTIFICATA')
