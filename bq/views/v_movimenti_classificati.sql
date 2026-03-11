-- View: hotelops.v_movimenti_classificati
-- Tutti i movimenti bancari con classificazione macro_tipo e flag intercompany.
--
-- macro_tipo:
--   POS_ENTRATA      — incassi POS / terminale
--   CONTANTE_ENTRATA — versamenti contante
--   BONIFICO_ENTRATA — bonifici in entrata
--   BONIFICO_USCITA  — bonifici in uscita
--   POS_USCITA       — pagamenti con carta aziendale
--   STIPENDI         — emolumenti / stipendi
--   TASSE            — F24, PagoPA, imposte
--   MUTUI            — rate mutuo
--   FINANZIAMENTO    — erogazioni finanziamento
--   PAYBYLINK        — Stripe / Pay by Link
--   COMMISSIONI      — spese bancarie e commissioni
--   ALTRO            — tutto il resto
--
-- is_intercompany: TRUE se il movimento è tra INTUR e ORTI.

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_movimenti_classificati` AS

SELECT *,
  CASE
    WHEN tipo_movimento LIKE '%(09)%'  OR tipo_movimento LIKE '%INCASSO%P.O.S%'  OR tipo_movimento LIKE '%Incasso Tramite P.O.S%' THEN 'POS_ENTRATA'
    WHEN tipo_movimento LIKE '%(78)%'  OR tipo_movimento LIKE '%VERSAMENTO%CONTANTE%'                                              THEN 'CONTANTE_ENTRATA'
    WHEN tipo_movimento LIKE '%(48)%'  OR tipo_movimento LIKE '%(ZI)%'           OR tipo_movimento = 'Bonifico a tuo favore'
      OR (tipo_movimento IN ('Bonifico','Bonifico istantaneo','Bonifico Dall estero') AND importo_netto > 0)                      THEN 'BONIFICO_ENTRATA'
    WHEN tipo_movimento LIKE '%(26)%'  OR tipo_movimento LIKE '%Disposizione Impartita%' OR tipo_movimento LIKE '%(ZL)%'
      OR tipo_movimento = 'Bonifico continuativo'
      OR (tipo_movimento IN ('Bonifico','Bonifico istantaneo') AND importo_netto < 0)                                             THEN 'BONIFICO_USCITA'
    WHEN tipo_movimento LIKE '%(43)%'  OR tipo_movimento = 'Pagamento POS'       OR tipo_movimento LIKE '%Mastercard%'
      OR tipo_movimento LIKE '%Maestro%'                                                                                          THEN 'POS_USCITA'
    WHEN tipo_movimento LIKE '%(39)%'  OR tipo_movimento LIKE '%Emolumenti%'     OR tipo_movimento = 'Stipendio'                  THEN 'STIPENDI'
    WHEN tipo_movimento LIKE '%(19)%'  OR tipo_movimento IN ('F24','PagoPA')     OR tipo_movimento LIKE '%Imposte%'
      OR tipo_movimento LIKE '%Tributi%'                                                                                          THEN 'TASSE'
    WHEN tipo_movimento LIKE '%(15)%'  OR tipo_movimento LIKE '%Rata%Mutuo%'                                                      THEN 'MUTUI'
    WHEN tipo_movimento LIKE '%Erogazione%Finanziamento%' OR tipo_movimento LIKE '%(ZS)%'                                         THEN 'FINANZIAMENTO'
    WHEN LOWER(descrizione) LIKE '%stripe%' OR LOWER(descrizione) LIKE '%pay by link%' OR LOWER(descrizione) LIKE '%paybylink%'   THEN 'PAYBYLINK'
    WHEN tipo_movimento LIKE '%Commissioni%' OR tipo_movimento LIKE '%Spese%'    OR tipo_movimento LIKE '%(66)%'
      OR tipo_movimento LIKE '%(16)%'                                                                                             THEN 'COMMISSIONI'
    ELSE 'ALTRO'
  END AS macro_tipo,

  CASE
    WHEN LOWER(descrizione) LIKE '%intur%' AND LOWER(descrizione) LIKE '%orti%'          THEN TRUE
    WHEN LOWER(descrizione) LIKE '%giroconto%intur%' OR LOWER(descrizione) LIKE '%girofondi%intur%' THEN TRUE
    WHEN LOWER(descrizione) LIKE '%a favore%intur%'  OR LOWER(descrizione) LIKE '%favore intur%'    THEN TRUE
    WHEN LOWER(descrizione) LIKE '%giroconto%orti%'  OR LOWER(descrizione) LIKE '%girofondi%orti%'  THEN TRUE
    ELSE FALSE
  END AS is_intercompany

FROM hotelops.f_banche_movimenti;
