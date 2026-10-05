"""Budget camere per driver — letture da BigQuery (sola lettura).

`query` è iniettabile, come in verticals/condges/canone_fonti.py.
"""

from __future__ import annotations

from core.config import (
    D_CAMERE,
    F_BOOKINGS_TIPOLOGIA,
    F_PMS_STATISTICHE,
    F_PRODUZIONE_PMS,
)

BU = "HOTEL"


def _query(sql: str) -> list[dict]:
    from core.bq.client import get_client

    return [dict(r) for r in get_client().query(sql).result()]


def leggi_camere(query=_query) -> list[dict]:
    return query(
        f"SELECT room_id, cod_camera, tipologia FROM `{D_CAMERE}` "
        f"WHERE business_unit_id = '{BU}' ORDER BY room_id"
    )


def leggi_categorie(anno: int, query=_query) -> list[dict]:
    """Venduto giornaliero per tipologia VENDUTA; `caricato` = giorno dell'esportazione."""
    righe = query(
        f"""
        SELECT data, tipologia AS codice, SUM(camere) AS notti,
               SUM(ricavo_camera) AS ricavo, MIN(DATE(data_caricamento)) AS caricato
        FROM `{F_BOOKINGS_TIPOLOGIA}`
        WHERE business_unit_id = '{BU}' AND EXTRACT(YEAR FROM data) = {anno}
        GROUP BY data, tipologia
        """
    )
    if not righe:
        raise ValueError(f"f_bookings_tipologia: nessuna riga {BU} {anno}")
    return righe


def leggi_pms(anno: int, query=_query) -> list[dict]:
    """Notti dalle statistiche, ricavo camere dalla classe 01ROOM (base canonica)."""
    return query(
        f"""
        WITH s AS (
          SELECT DATE(data) AS data, SUM(camere_vendute) AS notti
          FROM `{F_PMS_STATISTICHE}`
          WHERE business_unit_id = '{BU}' AND EXTRACT(YEAR FROM data) = {anno}
          GROUP BY 1
        ), p AS (
          SELECT data, SUM(importo_imponibile) AS ricavo
          FROM `{F_PRODUZIONE_PMS}`
          WHERE business_unit_id = '{BU}' AND classe = '01ROOM'
            AND EXTRACT(YEAR FROM data) = {anno}
          GROUP BY 1
        )
        SELECT COALESCE(s.data, p.data) AS data, s.notti, p.ricavo
        FROM s FULL JOIN p USING (data)
        ORDER BY data
        """
    )
