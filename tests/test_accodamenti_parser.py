"""Tests for core.parsers.accodamenti event classification.

Event type MUST be determined by account codes in GEN records (39.05.21 = caparra),
NOT by progressivo value (a fragile positional heuristic).
"""

import logging

from core.parsers.accodamenti import parse_movimenti


def _gen_line(*, conto="", dare="0", avere="0", progressivo=1, data="01042026", desc=""):
    """Build a pipe-delimited GEN line matching Esolver accodamenti format."""
    fields = [""] * 23
    fields[0] = "GEN"
    fields[2] = "701"
    fields[4] = data
    fields[5] = "77"
    fields[8] = str(progressivo)
    fields[10] = conto
    fields[17] = avere
    fields[18] = dare
    fields[22] = desc
    fields.append("BON")  # metodo_pagamento = last field
    return "|".join(fields)


def _par_line(*, conto="", importo="0", data="01042026"):
    """Build a PAR line (partita reference)."""
    fields = [""] * 52
    fields[0] = "PAR"
    fields[2] = "701"
    fields[4] = data
    fields[8] = "1"
    fields[10] = conto
    fields[44] = "42"
    fields[48] = importo
    fields[50] = importo
    return "|".join(fields)


def _write_movimenti(tmp_path, lines, prefix="H_"):
    path = tmp_path / f"{prefix}Movimenti.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


# ── Caparra account (39.05.21) → incasso_caparra ─────────────────────────────


def test_gen_with_caparra_leg_is_incasso_caparra_regardless_of_progressivo(tmp_path):
    """Key regression: 390521 + progressivo=77 → incasso_caparra.

    OLD parser used progressivo==0 heuristic → real caparre with progressivo>0
    were mis-classified as movimento_generico. NEW parser classifies via
    caparra account presence.
    """
    path = _write_movimenti(
        tmp_path,
        [
            _gen_line(conto="199007", dare="0", avere="276", progressivo=77),
            _gen_line(conto="390521", dare="276", avere="0", progressivo=77),
        ],
    )
    events = parse_movimenti(path)
    assert len(events) == 1
    assert events[0]["type"] == "incasso_caparra"


def test_gen_with_caparra_leg_and_progressivo_zero_is_still_incasso_caparra(tmp_path):
    """Legacy case stays working: progressivo=0 + 390521 leg → incasso_caparra."""
    path = _write_movimenti(
        tmp_path,
        [
            _gen_line(conto="199001", dare="50", avere="0", progressivo=0),
            _gen_line(conto="390521", dare="0", avere="50", progressivo=0),
        ],
    )
    events = parse_movimenti(path)
    assert len(events) == 1
    assert events[0]["type"] == "incasso_caparra"


def test_gen_with_dotted_caparra_account_is_incasso_caparra(tmp_path):
    """Defensive: if Esolver ever emits dotted format, still classify correctly."""
    path = _write_movimenti(
        tmp_path,
        [
            _gen_line(conto="19.90.01", dare="50", avere="0", progressivo=5),
            _gen_line(conto="39.05.21", dare="0", avere="50", progressivo=5),
        ],
    )
    events = parse_movimenti(path)
    assert len(events) == 1
    assert events[0]["type"] == "incasso_caparra"


# ── No caparra account → movimento_generico ──────────────────────────────────


def test_gen_without_caparra_leg_is_movimento_generico(tmp_path):
    """No 390521 leg anywhere → movimento_generico (honest fallback)."""
    path = _write_movimenti(
        tmp_path,
        [
            _gen_line(conto="199001", dare="100", avere="0", progressivo=99),
            _gen_line(conto="790101", dare="0", avere="100", progressivo=99),
        ],
    )
    events = parse_movimenti(path)
    assert len(events) == 1
    assert events[0]["type"] == "movimento_generico"


def test_gen_progressivo_zero_without_caparra_leg_is_movimento_generico(tmp_path):
    """Critical regression: OLD parser misclassified this as incasso_caparra.

    With the new logic, progressivo==0 alone is NOT sufficient — the caparra
    account must be present.
    """
    path = _write_movimenti(
        tmp_path,
        [
            _gen_line(conto="190303", dare="30", avere="0", progressivo=0),
            _gen_line(conto="790101", dare="0", avere="30", progressivo=0),
        ],
    )
    events = parse_movimenti(path)
    assert len(events) == 1
    assert events[0]["type"] == "movimento_generico"


# ── PAR present → giro_caparra (unchanged, regression safety) ────────────────


def test_gen_with_par_record_is_giro_caparra(tmp_path):
    """PAR present always means giro_caparra — unchanged behavior."""
    path = _write_movimenti(
        tmp_path,
        [
            _gen_line(conto="390521", dare="100", avere="0", progressivo=1),
            _par_line(conto="390521", importo="100"),
            _gen_line(conto="110301", dare="0", avere="100", progressivo=1),
        ],
    )
    events = parse_movimenti(path)
    assert len(events) == 1
    assert events[0]["type"] == "giro_caparra"
    assert events[0]["par"] is not None
    assert events[0]["par"]["num_doc_partita"] == 42


# ── Struttura detection: unknown filename prefix logs warning ────────────────


def test_parse_movimenti_unknown_struttura_logs_warning(tmp_path, caplog):
    """Filename prefix not in {H_, R_, C_} → struttura='unknown' + warning.

    Previously silent: unknown struttura propagated to aggregator and rendered
    as '???' in Excel with no upstream signal.
    """
    path = tmp_path / "X_Movimenti.txt"
    path.write_text(
        _gen_line(conto="199001", dare="100", progressivo=1) + "\n",
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING, logger="core.parsers.accodamenti"):
        events = parse_movimenti(str(path))
    assert len(events) == 1
    assert events[0]["struttura"] == "unknown"
    assert any("prefisso" in rec.message.lower() or "unknown" in rec.message.lower()
               for rec in caplog.records)


def test_detect_struttura_promotion_tempfile_prefix(tmp_path):
    """La promotion scarica il blob come `hotelops_raw_<rand>_H_Movimenti.txt`:
    il prefisso BU non è più in testa al nome. La detection deve ancorarsi alla
    coda del filename (regressione: righe finite tutte su HQ, 2026-07-06)."""
    path = tmp_path / "hotelops_raw_v3_18897_H_Movimenti.txt"
    path.write_text(
        _gen_line(conto="199001", dare="100", progressivo=1) + "\n",
        encoding="utf-8",
    )
    events = parse_movimenti(str(path))
    assert len(events) == 1
    assert events[0]["struttura"] == "hotel"
