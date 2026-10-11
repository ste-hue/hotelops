"""f_piano_finanziario_input: righe gemelle e revisioni del piano.

Two defects lived in the same write path (issue #120, P0 of the map):

1. LOSS — hash_riga was (societa, voce, anno, mese, fonte) and the batch dedup
   kept the last row for a hash ("last file wins"). Two legitimate rows of the
   same voce in the same month collapsed into one, before any write. Measured on
   the real master 2026-08-21: INTUR ENTRATE_AFFITTI_INTUR 2027-07 carries
   488.000 and 60.000 — 488.000 was being dropped.
2. FROZEN PLAN — load_to_bq skipped rows whose hash already existed, so a
   revised amount on an existing key never reached the table.

The table is declared SNAPSHOT in source_registry.yaml; the code appended.
Aligning it to a real snapshot fixes both.
"""

from ingest.flussi.ingest_piano_finanziario_xlsx import (
    assegna_occorrenze,
    make_hash,
    scrivi_su_bq,
)


def _riga(
    voce="ENTRATE_AFFITTI_INTUR", mese=7, importo=100.0, fonte="PIANO_FINANZIARIO"
):
    return {
        "societa_id": "INTUR",
        "voce_id": voce,
        "anno": 2027,
        "mese": mese,
        "importo": importo,
        "fonte": fonte,
        "note": None,
        "file_sorgente": "INTUR_PF.xlsx",
        "data_caricamento": "2026-08-21T00:00:00",
        "hash_riga": "",
        "raw_object_id": "raw-1",
    }


def test_twin_rows_of_the_same_voce_both_survive():
    """The real case: 488.000 and 60.000 on INTUR affitti 2027-07."""
    rows = assegna_occorrenze([_riga(importo=488000.0), _riga(importo=60000.0)])

    assert len(rows) == 2, "a row was dropped before the write"
    assert len({r["hash_riga"] for r in rows}) == 2, (
        "twin rows share a hash_riga — the collision gate would refuse the batch"
    )
    assert {r["importo"] for r in rows} == {488000.0, 60000.0}


def test_occurrence_is_stable_across_runs():
    """Re-parsing the same sheet must yield the same hashes, or the snapshot
    DELETE+INSERT would churn identities every run."""
    first = assegna_occorrenze([_riga(importo=488000.0), _riga(importo=60000.0)])
    second = assegna_occorrenze([_riga(importo=488000.0), _riga(importo=60000.0)])
    assert [r["hash_riga"] for r in first] == [r["hash_riga"] for r in second]


def test_distinct_voci_keep_distinct_hashes():
    rows = assegna_occorrenze(
        [_riga(voce="ENTRATE_AFFITTI_INTUR"), _riga(voce="USCITE_MUTUI")]
    )
    assert len({r["hash_riga"] for r in rows}) == 2


def test_make_hash_discriminates_on_occurrence():
    a = make_hash("INTUR", "ENTRATE_AFFITTI_INTUR", 2027, 7, "PIANO_FINANZIARIO", 1)
    b = make_hash("INTUR", "ENTRATE_AFFITTI_INTUR", 2027, 7, "PIANO_FINANZIARIO", 2)
    assert a != b


def test_write_is_a_snapshot_scoped_to_societa_fonte_and_period(monkeypatch):
    """A revised plan must REPLACE its perimeter, not append next to it.

    After #124 the view SUMs the rows of the winning fonte, so an appended
    revision would inflate the PF instead of superseding it.
    """
    calls = []
    monkeypatch.setattr(
        "ingest.flussi.ingest_piano_finanziario_xlsx.bq_write_validated",
        lambda table, rows, mode="append", natural_key=None: calls.append(
            (table, list(rows), mode, natural_key)
        ),
    )

    scrivi_su_bq(assegna_occorrenze([_riga(importo=488000.0)]))

    assert len(calls) == 1
    table, rows, mode, natural_key = calls[0]
    assert table.endswith("f_piano_finanziario_input")
    assert mode == "snapshot"
    assert natural_key is not None
    assert "fonte" in natural_key, (
        "without fonte in the key the DELETE would wipe SCADENZIARIO and BVA_2026"
    )
    assert set(natural_key) == {"societa_id", "fonte", "anno", "mese", "voce_id"}


def test_empty_batch_writes_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "ingest.flussi.ingest_piano_finanziario_xlsx.bq_write_validated",
        lambda *a, **k: calls.append(a),
    )
    scrivi_su_bq([])
    assert calls == []
