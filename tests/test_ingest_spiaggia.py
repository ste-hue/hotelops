from datetime import date, datetime, timezone

import pytest

from core.schemas import (
    SpiaggiaCashFlowRow,
    SpiaggiaReservationRow,
    SpiaggiaSpotRow,
)


def _now():
    return datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc)


def test_reservation_row_valid():
    r = SpiaggiaReservationRow(
        societa_id="INTUR",
        business_unit_id="LIDO",
        location_id="LIDO",
        oggetto_id="7",
        id=4402425,
        spot_type="umbrella",
        spot_name="7",
        status=1,
        seasonal=False,
        deleted=False,
        online=True,
        start_date=date(2020, 6, 19),
        end_date=date(2020, 6, 19),
        beds=2,
        chairs=0,
        first_name="Jessica",
        last_name="Neely",
        email="jess@example.com",
        gross_booking_value=35.0,
        file_sorgente="dump.json",
        hash_riga="abc",
        data_caricamento=_now(),
    )
    assert r.id == 4402425
    assert r.societa_id == "INTUR"


def test_reservation_row_rejects_bad_societa():
    with pytest.raises(Exception):
        SpiaggiaReservationRow(
            societa_id="PIPPO",
            business_unit_id="LIDO",
            id=1,
            seasonal=False,
            deleted=False,
            online=False,
            file_sorgente="d.json",
            hash_riga="x",
            data_caricamento=_now(),
        )


def test_cash_flow_row_valid_negative_amount():
    c = SpiaggiaCashFlowRow(
        societa_id="INTUR",
        business_unit_id="LIDO",
        id=3055414,
        reservation_id=4402426,
        method=1,
        method_label="metodo_1",
        amount=-35.0,
        date=date(2020, 6, 10),
        deleted=False,
        file_sorgente="dump.json",
        hash_riga="def",
        data_caricamento=_now(),
    )
    assert c.amount == -35.0


def test_spot_row_valid():
    s = SpiaggiaSpotRow(
        societa_id="INTUR",
        business_unit_id="LIDO",
        location_id="LIDO",
        oggetto_id="7",
        id=1394619,
        uuid="7be4bfed-9905-4ec3-836e-5a745bf3d558",
        name="7",
        type="umbrella",
        sector=0,
        file_sorgente="dump.json",
        hash_riga="ghi",
        data_caricamento=_now(),
    )
    assert s.type == "umbrella"


from datetime import date as _date

from ingest.flussi.ingest_spiaggia import (
    extract_table,
    find_prefix,
    method_label,
    to_bool,
    to_float,
    to_int,
    to_str,
    unix_to_date,
    unix_to_ts,
)



def test_coercion_helpers():
    assert to_int(None) is None
    assert to_int("") is None
    assert to_int(5) == 5
    assert to_float("35.00") == 35.0
    assert to_float("-10.50") == -10.5
    assert to_float(None) is None
    assert to_float("") is None
    assert to_bool(1) is True
    assert to_bool(0) is False
    assert to_bool(None) is False
    assert to_str("  x ") == "x"
    assert to_str("") is None
    assert to_str(None) is None


def test_unix_conversions():
    assert unix_to_date(1592524800) == _date(2020, 6, 19)
    assert unix_to_date(0) is None
    assert unix_to_date(None) is None
    assert unix_to_ts(0) is None
    assert unix_to_ts(1652133848).year == 2022


def test_method_label():
    assert method_label(None) == "sconosciuto"
    assert method_label(1) == "metodo_1"
    assert method_label(14) == "metodo_14"


def test_find_prefix_and_extract():
    dump = {
        "it-sa-84010-panorama-beach_reservations": {
            "columns": ["id", "spot_name", "amount"],
            "rows": [[1, "7", "35.00"], [2, "8", "40.00"]],
        }
    }
    prefix = find_prefix(dump)
    assert prefix == "it-sa-84010-panorama-beach_"
    recs = extract_table(dump, prefix, "reservations")
    assert recs == [
        {"id": 1, "spot_name": "7", "amount": "35.00"},
        {"id": 2, "spot_name": "8", "amount": "40.00"},
    ]


from datetime import datetime as _dt
from datetime import timezone as _tz

from ingest.flussi.ingest_spiaggia import (
    build_cash_flow_rows,
    build_reservation_rows,
    build_spot_rows,
)

_NOW = _dt(2026, 6, 13, tzinfo=_tz.utc)


def test_build_reservation_rows():
    recs = [{
        "id": 4402425, "license_code": "it-sa-84010-panorama-beach",
        "spot_type": "umbrella", "spot_name": "7", "status": 1,
        "seasonal": 0, "deleted": 0, "online": 1, "hotel": "",
        "hotel_room": None, "start_date": 1592524800, "end_date": 1592524800,
        "beds": 2, "chairs": 0, "first_name": "Jessica", "last_name": "Neely",
        "email": "jess@example.com", "phone_area_code": None,
        "phone_number": "6128192966", "list_total": None, "paid_total": None,
        "gross_booking_value": 35, "discount": None, "channel": "",
        "invoice_number": None, "invoice_company": None,
        "utm_source": None, "utm_medium": None, "utm_campaign": None,
        "created_at": 1652133848, "updated_at": None,
    }]
    rows = build_reservation_rows(recs, "dump.json", "raw-1", _NOW)
    assert len(rows) == 1
    r = rows[0]
    assert r.id == 4402425
    assert r.societa_id == "INTUR"
    assert r.business_unit_id == "LIDO"
    assert r.oggetto_id == "7"          # spot_name
    assert r.online is True
    assert r.seasonal is False
    assert r.start_date.year == 2020
    assert r.phone == "6128192966"
    assert r.gross_booking_value == 35.0
    assert r.raw_object_id == "raw-1"


def test_build_cash_flow_rows_negative():
    recs = [{
        "id": 3055414, "reservation_id": 4402426, "method": None,
        "amount": "-35.00", "date": 1591786050, "receipt_id": None,
        "invoice_id": None, "deleted": 1, "created_at": 1652133848,
        "updated_at": None,
    }]
    rows = build_cash_flow_rows(recs, "dump.json", "raw-1", _NOW)
    c = rows[0]
    assert c.amount == -35.0
    assert c.method_label == "sconosciuto"
    assert c.deleted is True
    assert c.societa_id == "INTUR"


def test_build_spot_rows():
    recs = [{
        "id": 1394619, "uuid": "abc", "name": "7", "type": "umbrella",
        "sector": 0, "price_list_id": None, "pos_x": 617, "pos_y": 73,
        "element_type": "passerella",
    }]
    rows = build_spot_rows(recs, "dump.json", "raw-1", _NOW)
    s = rows[0]
    assert s.id == 1394619
    assert s.oggetto_id == "7"          # name
    assert s.type == "umbrella"
    assert s.business_unit_id == "LIDO"
