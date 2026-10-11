"""Dedup key of f_banche_movimenti: distinct movements must survive.

Regression for the loss found on 2026-08-21: hash_riga was built from
(societa, banca, data_operazione, data_valuta, importo_netto), so two genuinely
distinct movements on the same day for the same amount collapsed into one —
silently, because the append path filters on that hash. 248,65 € of real
movements were dropped across six homebanking exports.

Family: issue #120 (hash_riga is not a natural key).
"""

from pathlib import Path
from unittest.mock import MagicMock


def _sella_csv(tmp_path: Path, rows: str, name: str = "SELLA_ORTI_2026_08.csv") -> Path:
    f = tmp_path / name
    f.write_text(
        "Codice identificativo,Data operazione,Data valuta,Descrizione,Divisa,"
        "Debito,Credito,Categoria,Sottocategoria,Etichette,Note\n" + rows,
        encoding="utf-8",
    )
    return f


def _run(f: Path, monkeypatch, hashes=None) -> list:
    """Run the parser over one file, return the rows handed to the writer."""
    captured: list = []
    monkeypatch.setattr(
        "ingest.banca.ingest.bq_write_validated",
        lambda table, rows, mode="append", **kw: captured.extend(rows),
    )
    monkeypatch.setattr("ingest.banca.ingest.get_client", lambda: MagicMock())
    monkeypatch.setattr("ingest.banca.ingest.load_hashes", lambda _c: set(hashes or ()))
    monkeypatch.setattr("ingest.banca.ingest.load_mappings", lambda _p, _l: {})

    from ingest.banca.ingest import ingest_single_file

    ingest_single_file(
        file_path=f, raw_object_id="raw-test", societa="ORTI", dry_run=False
    )
    return captured


def test_twin_movements_same_day_same_amount_are_both_kept(tmp_path, monkeypatch):
    """Two SEPA transfers of 150,70 on the same day are two payments, not one.

    Real case: ORTI/MPS 17/08/2026, three transfers of -150,70 to three
    different people — only one survived.
    """
    rows = _run(
        _sella_csv(
            tmp_path,
            "TXN1,17/08/2026,17/08/2026,BONIFICO A FAVORE LAMBERTI,EUR,150.70,,USCITE,,,\n"
            "TXN2,17/08/2026,17/08/2026,BONIFICO A FAVORE TASCIONE,EUR,150.70,,USCITE,,,\n"
            "TXN3,17/08/2026,17/08/2026,BONIFICO A FAVORE MERA,EUR,150.70,,USCITE,,,\n",
        ),
        monkeypatch,
    )
    assert len(rows) == 3, f"expected 3 distinct movements, wrote {len(rows)}"
    assert len({r.hash_riga for r in rows}) == 3, "hash_riga must discriminate"


def test_movements_identical_in_every_field_are_both_kept(tmp_path, monkeypatch):
    """Two identical POS charges are still two charges on the statement.

    Real case: INTUR/SELLA 06/07/2026, two 'POS 0307 AMAZON* NQ33L0ET4' of 9,82
    — identical in description too, so no free-text field can separate them.
    """
    rows = _run(
        _sella_csv(
            tmp_path,
            "TXN1,06/07/2026,06/07/2026,POS 0307 AMAZON,EUR,,9.82,ENTRATE,,,\n"
            "TXN2,06/07/2026,06/07/2026,POS 0307 AMAZON,EUR,,9.82,ENTRATE,,,\n",
        ),
        monkeypatch,
    )
    assert len(rows) == 2, f"expected 2 movements, wrote {len(rows)}"
    assert len({r.hash_riga for r in rows}) == 2


def test_re_ingesting_the_same_file_writes_nothing(tmp_path, monkeypatch):
    """Idempotence: the same export twice must not duplicate."""
    f = _sella_csv(
        tmp_path,
        "TXN1,17/08/2026,17/08/2026,BONIFICO UNO,EUR,150.70,,USCITE,,,\n"
        "TXN2,17/08/2026,17/08/2026,BONIFICO DUE,EUR,150.70,,USCITE,,,\n",
    )
    first = _run(f, monkeypatch)
    again = _run(f, monkeypatch, hashes={r.hash_riga for r in first})
    assert again == [], f"re-ingest wrote {len(again)} duplicate rows"


def test_value_date_correction_does_not_duplicate(tmp_path, monkeypatch):
    """The bank may restate data_valuta between exports — same movement.

    Real case: INTUR/SELLA 'EURO CARBURANTI CARDITO NA' -80,01 of 03/08, value
    date moved 03/08 → 05/08 in the later export, landing twice in BQ.
    """
    first = _run(
        _sella_csv(
            tmp_path,
            "TXN1,03/08/2026,03/08/2026,EURO CARBURANTI CARDITO NA,EUR,80.01,,USCITE,,,\n",
            name="SELLA_ORTI_prima.csv",
        ),
        monkeypatch,
    )
    again = _run(
        _sella_csv(
            tmp_path,
            "TXN1,03/08/2026,05/08/2026,EURO CARBURANTI CARDITO NA,EUR,80.01,,USCITE,,,\n",
            name="SELLA_ORTI_dopo.csv",
        ),
        monkeypatch,
        hashes={r.hash_riga for r in first},
    )
    assert again == [], "value-date restatement must not create a duplicate"


def _fake_bq_rows(written):
    """What the load_hashes query returns for rows already stored in BQ.

    Mirrors the SQL: ROW_NUMBER() over (societa, banca, day, amount) ordered by
    data_valuta, descrizione, hash_riga.
    """
    from types import SimpleNamespace

    ordered = sorted(written, key=lambda r: (r.data_valuta, r.descrizione, r.hash_riga))
    seen: dict = {}
    out = []
    for r in ordered:
        key = (
            r.societa_id,
            r.banca_id,
            str(r.data_operazione),
            f"{r.importo_netto:.2f}",
        )
        seen[key] = seen.get(key, 0) + 1
        out.append(
            SimpleNamespace(
                hash_riga=r.hash_riga,
                societa_id=r.societa_id,
                banca_id=r.banca_id,
                d_op=str(r.data_operazione),
                netto=f"{r.importo_netto:.2f}",
                occorrenza=seen[key],
            )
        )
    return out


def test_load_hashes_rebuilds_the_keys_of_stored_rows(tmp_path, monkeypatch):
    """The next export must dedup against history, not duplicate it.

    Changing the key formula duplicates the whole table on the first run unless
    load_hashes recomputes it for stored rows — the migration risk called out in
    issue #120.
    """
    from unittest.mock import MagicMock

    # Bind the real function before _run() monkeypatches the module attribute.
    from ingest.banca.ingest import load_hashes

    f = _sella_csv(
        tmp_path,
        "TXN1,17/08/2026,17/08/2026,BONIFICO UNO,EUR,150.70,,USCITE,,,\n"
        "TXN2,17/08/2026,17/08/2026,BONIFICO DUE,EUR,150.70,,USCITE,,,\n"
        "TXN3,18/08/2026,18/08/2026,VERSAMENTO,EUR,,240.00,ENTRATE,,,\n",
    )
    written = _run(f, monkeypatch)
    assert len(written) == 3

    client = MagicMock()
    client.query.return_value.result.return_value = _fake_bq_rows(written)

    stored = load_hashes(client)
    assert {r.hash_riga for r in written} <= stored, (
        "hashes rebuilt from BQ do not match the ones the parser produces — "
        "the next export would duplicate every row"
    )

    assert _run(f, monkeypatch, hashes=stored) == []
