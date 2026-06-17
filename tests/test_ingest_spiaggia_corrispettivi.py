from datetime import date, datetime, timezone
import pytest
from core.schemas import SpiaggiaCorrispettivoRow


def _now():
    return datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)


def test_corrispettivo_row_valid():
    r = SpiaggiaCorrispettivoRow(
        societa_id="INTUR",
        business_unit_id="LIDO",
        location_id="LIDO",
        data=date(2026, 6, 16),
        anno=2026,
        mese=6,
        corrispettivo_spiaggia=561.0,
        corrispettivo_bar=517.5,
        corrispettivo_totale=1078.5,
        rt_matricola="RT2CFL018343",
        file_sorgente="registro_2026.xlsx",
        hash_riga="abc",
        data_caricamento=_now(),
    )
    assert r.societa_id == "INTUR"
    assert r.corrispettivo_totale == 1078.5


def test_corrispettivo_row_rejects_bad_societa():
    with pytest.raises(Exception):
        SpiaggiaCorrispettivoRow(
            societa_id="PIPPO", business_unit_id="LIDO",
            data=date(2026, 6, 16), anno=2026, mese=6,
            corrispettivo_spiaggia=1.0, corrispettivo_bar=1.0,
            corrispettivo_totale=2.0,
            file_sorgente="x.xlsx", hash_riga="x", data_caricamento=_now(),
        )
