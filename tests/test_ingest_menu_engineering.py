"""Test parser menu engineering (RistoCube Engineering F&B Data.xlsx)."""

from datetime import date, datetime, timezone

from core.schemas import MenuEngineeringRow


def _row_base() -> dict:
    return {
        "hash_riga": "abc123",
        "societa_id": "ORTI",
        "business_unit_id": "HOTEL",
        "snapshot_date": date(2026, 7, 30),
        "sala": "BAR",
        "piatto": "SO000006",
        "descrizione": "COCA COLA ZERO CL.33",
        "tipo": "SOFT DRINK",
        "m_class": None,
        "prezzo_unitario": 4.55,
        "costo_unitario": 0.8088,
        "quantita": 561.0,
        "incidenza_pct": 0.0827,
        "costo_totale": 453.74,
        "listino": 2552.55,
        "vendita": 2528.62,
        "importo_addebitato": 1091.59,
        "importo_fatturato": 954.98,
        "file_sorgente": "Engineering F&B Data.xlsx",
        "raw_object_id": "98f431e0-f9e9-477d-948f-42345be90865",
        "data_caricamento": datetime.now(timezone.utc),
    }


def test_menu_engineering_row_valida():
    r = MenuEngineeringRow(**_row_base())
    assert r.piatto == "SO000006"
    assert r.snapshot_date == date(2026, 7, 30)
