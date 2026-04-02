-- v_condges_banca_dettaglio: Bank transactions detail for Looker Studio
--
-- Transaction-level grain with normalized categories derived from
-- tipo_movimento. Enables drill-down dashboards: where is money going,
-- by category, supplier, bank, day/week/month.
--
-- Grain: one row per bank transaction (hash_riga)

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_condges_banca_dettaglio` AS

WITH mese_labels AS (
  SELECT offset + 1 AS mese, label AS mese_label
  FROM UNNEST([
    'Gennaio','Febbraio','Marzo','Aprile','Maggio','Giugno',
    'Luglio','Agosto','Settembre','Ottobre','Novembre','Dicembre'
  ]) AS label WITH OFFSET AS offset
),

raw AS (
  SELECT
    *,
    EXTRACT(YEAR FROM data_operazione)  AS anno,
    EXTRACT(MONTH FROM data_operazione) AS mese,

    -- ── Direction ────────────────────────────────────────────────────
    CASE
      WHEN importo_netto >= 0 THEN 'ENTRATA'
      ELSE 'USCITA'
    END AS direzione,

    -- ── Normalized category from tipo_movimento ─────────────────────
    CASE
      -- Incassi POS (hotel, online, etc.)
      WHEN tipo_movimento LIKE '%INCASSO TRAMITE P.O.S.%'
        OR tipo_movimento LIKE '%Incasso Tramite P.O.S.%'
        THEN 'POS_INCASSI'

      -- Contanti
      WHEN tipo_movimento LIKE '%VERSAMENTO DI CONTANTE%'
        THEN 'CONTANTI'

      -- Bonifici in arrivo (domestic + estero)
      WHEN tipo_movimento LIKE '%BONIFICO A VOSTRO FAVORE%'
        OR tipo_movimento LIKE '%Bonifico a tuo favore%'
        OR tipo_movimento LIKE '%Bonifico Dall%estero%'
        OR tipo_movimento LIKE '%BONIFICO DALL%ESTERO%'
        OR tipo_movimento LIKE '%Bonifico istantaneo%'
        OR tipo_movimento LIKE '%EROGAZIONE%FINANZIAMENT%'
        OR tipo_movimento LIKE '%Erogazione%Finanziamento%'
        THEN 'BONIFICI_IN'

      -- Bonifici in uscita (supplier payments)
      WHEN tipo_movimento LIKE '%VOSTRA DISPOSIZIONE A FAVORE%'
        OR tipo_movimento LIKE '%Disposizione Impartita%Telematico%'
        OR tipo_movimento LIKE '%BONIFICO SULL%ESTERO%'
        OR tipo_movimento LIKE '%Bonifico Per L%estero%'
        OR tipo_movimento LIKE '%Bonifico in uscita%'
        OR tipo_movimento LIKE '%Bonifico continuativo%'
        OR tipo_movimento LIKE '%Ordine permanente%addebito%'
        THEN 'BONIFICI_OUT'

      -- Stipendi
      WHEN tipo_movimento LIKE '%EMOLUMENTI%STIPENDI%'
        OR tipo_movimento LIKE '%Disposizione Per Emolumenti%'
        OR tipo_movimento LIKE '%Stipendio%'
        THEN 'STIPENDI'

      -- Imposte e tasse
      WHEN tipo_movimento LIKE '%IMPOSTE E TASSE%'
        OR tipo_movimento LIKE '%Imposte%tributi%'
        OR tipo_movimento LIKE '%Imposta di bollo%'
        OR tipo_movimento LIKE '%Imposta Di Bollo%'
        OR tipo_movimento LIKE '%PagoPA%'
        OR tipo_movimento LIKE '%F24%'
        OR tipo_movimento LIKE '%Cbill%'
        THEN 'IMPOSTE'

      -- Mutui e finanziamenti
      WHEN tipo_movimento LIKE '%RIMBORSO FINANZIAMENTI%'
        OR tipo_movimento LIKE '%Pagamento Rata Di Mutuo%'
        OR tipo_movimento LIKE '%EFFETTI RITIRATI%'
        OR tipo_movimento LIKE '%MAV%'
        OR tipo_movimento LIKE '%Ri.Ba%'
        THEN 'MUTUI'

      -- Pagamenti carte e POS uscita
      WHEN tipo_movimento LIKE '%PAGAMENTO TRAMITE POS%'
        OR tipo_movimento LIKE '%Pagamento POS%'
        OR tipo_movimento LIKE '%Pagamenti OnLine%'
        OR tipo_movimento LIKE '%UTILIZZO CARTE DI CREDITO%'
        OR tipo_movimento LIKE '%Mastercard%'
        OR tipo_movimento LIKE '%Addebito carta%'
        OR tipo_movimento LIKE '%Addebito Carta Monte%'
        THEN 'CARTE'

      -- SDD / Direct debit
      WHEN tipo_movimento LIKE '%Direct Debit%'
        THEN 'SDD'

      -- Commissioni e spese bancarie
      WHEN tipo_movimento LIKE '%Commissioni%'
        OR tipo_movimento LIKE '%COMMISSIONI%'
        OR tipo_movimento LIKE '%SPESE%'
        OR tipo_movimento LIKE '%Spese%'
        OR tipo_movimento LIKE '%CANONE%'
        OR tipo_movimento LIKE '%Canone%'
        OR tipo_movimento LIKE '%Oneri e commissioni%'
        OR tipo_movimento LIKE '%INTERESSI E COMPETENZE%'
        OR tipo_movimento LIKE '%Premio%Assicurazion%'
        OR tipo_movimento LIKE '%Premio Polizza%'
        THEN 'SPESE_BANCARIE'

      -- Storni / rimborsi
      WHEN tipo_movimento LIKE '%STORNO%'
        OR tipo_movimento LIKE '%Storno%'
        OR tipo_movimento LIKE '%Rimborso%'
        THEN 'STORNI'

      -- Pagamenti diversi (catch-all for numbered MPS causali)
      WHEN tipo_movimento LIKE '%PAGAMENTI DIVERSI%'
        OR tipo_movimento LIKE '%Altri pagamenti%'
        THEN 'PAGAMENTI_DIVERSI'

      -- Bonifico generico (Sella labels without direction)
      WHEN tipo_movimento = 'Bonifico'
        THEN CASE WHEN importo_netto >= 0 THEN 'BONIFICI_IN' ELSE 'BONIFICI_OUT' END

      ELSE 'ALTRO'
    END AS categoria,

    -- ── Extract counterparty from descrizione ───────────────────────
    -- Best-effort extraction. MPS descriptions are verbose and inconsistent.
    -- POS incassi: "INSEGNA:<name>"
    -- POS uscite: "ESERCENTE : <name> IMP."
    -- MPS/Intesa outgoing: last occurrence of "A FAVORE <name> IBAN"
    -- Incoming: "ORDINE/CONTO <name>" or "ORD: <name>"
    CASE
      WHEN descrizione LIKE '%INSEGNA:%'
        THEN TRIM(REPLACE(REGEXP_EXTRACT(descrizione, r'INSEGNA:([A-Z][A-Z0-9 .]+)'), '.', ''))
      WHEN descrizione LIKE '%ESERCENTE :%'
        THEN TRIM(REGEXP_EXTRACT(descrizione, r'ESERCENTE\s*:\s*(.+?)\s+IMP\.'))
      WHEN descrizione LIKE '%ORD: %'
        THEN TRIM(REGEXP_EXTRACT(descrizione, r'ORD:\s+(.+?)\s+(?:FILIALE|BON\.)'))
      WHEN descrizione LIKE '%ORDINE/CONTO %'
        THEN TRIM(REGEXP_EXTRACT(descrizione, r'ORDINE/CONTO\s+(.+?)\s{4,}'))
      ELSE NULL
    END AS controparte_raw

  FROM `hotelops-suite.hotelops.f_banche_movimenti`
)

SELECT
  r.societa_id                                              AS societa,
  r.banca_id                                                AS banca,
  r.anno,
  r.mese,
  r.data_operazione                                         AS data,
  DATE(r.anno, r.mese, 1)                                   AS data_mese,
  ml.mese_label,
  CONCAT(CAST(r.anno AS STRING), ' ', LPAD(CAST(r.mese AS STRING), 2, '0'),
         ' ', LEFT(ml.mese_label, 3))                        AS mese_sort_label,

  -- Dimensions
  r.direzione,
  r.categoria,
  r.tipo_movimento                                           AS tipo_movimento_raw,
  COALESCE(r.controparte_raw, '—')                           AS controparte,
  r.descrizione,

  -- Measures (always positive for Looker, use direzione to filter)
  ABS(r.importo_netto)                                       AS importo,
  r.importo_netto                                            AS importo_netto,
  COALESCE(r.importo_credito, CASE WHEN r.importo_netto > 0 THEN r.importo_netto ELSE 0 END)  AS entrata,
  COALESCE(r.importo_debito,  CASE WHEN r.importo_netto < 0 THEN ABS(r.importo_netto) ELSE 0 END) AS uscita,

  -- Metadata
  r.hash_riga,
  r.file_sorgente

FROM raw r
LEFT JOIN mese_labels ml ON ml.mese = r.mese
