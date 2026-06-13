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
