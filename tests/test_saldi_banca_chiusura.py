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
        r
        for r in rows
        if r["societa_id"] == "ORTI"
        and r["banca_id"] == "MPS"
        and r["data_riferimento"] == "2026-04-30"
    )
    assert mps_apr["saldo_eur"] == 245171.52  # certificato 2026-06-12, corregge 251897.54
    # Kross fuori dall'anchor (deciso 2026-06-12, commit ee6ff55)
    assert not any(r["banca_id"] == "MPS_KROSS" for r in rows)
    intesa_apr = next(
        r
        for r in rows
        if r["societa_id"] == "ORTI"
        and r["banca_id"] == "INTESA"
        and r["data_riferimento"] == "2026-04-30"
    )
    assert intesa_apr["saldo_eur"] == 87439.92

