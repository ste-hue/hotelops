"""Saldi banca fine mese (manuali) — CSV + schema."""

from pathlib import Path

from core.schemas import SaldoBancaChiusuraMensileRow, validate_batch


def test_parse_importo_italiano_e_anglosassone():
    from core.bq.load.load_saldi_banca_chiusura_mensile import _parse_importo_eur

    assert _parse_importo_eur("52799.65") == 52799.65
    assert _parse_importo_eur("52.799,65") == 52799.65


def test_csv_parse_e_validate():
    from core.bq.load.load_saldi_banca_chiusura_mensile import parse_csv, setup_logger

    p = Path(__file__).resolve().parents[1] / "core" / "bq" / "dimensioni" / "d_saldi_banca_chiusura_mensile.csv"
    log = setup_logger()
    rows = parse_csv(p, log)
    assert len(rows) >= 5
    validate_batch(rows, SaldoBancaChiusuraMensileRow, "f_saldi_banca_chiusura_mensile")
    mps_apr = next(
        r for r in rows if r["banca_id"] == "MPS" and r["data_riferimento"] == "2026-04-30"
    )
    assert mps_apr["saldo_eur"] == 251897.54
    kross_apr = next(
        r for r in rows if r["banca_id"] == "MPS_KROSS" and r["data_riferimento"] == "2026-04-30"
    )
    assert kross_apr["saldo_eur"] == 33915.06
    intesa_apr = next(
        r for r in rows if r["banca_id"] == "INTESA" and r["data_riferimento"] == "2026-04-30"
    )
    assert intesa_apr["saldo_eur"] == 87439.92

