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

3. MIXED VERSIONS (2026-10-28) — the snapshot key was the cell (societa, fonte,
   anno, mese, voce): a cell Rosa zeroed or moved yields no row (the parser skips
   zeros), so it was never deleted and the previous file's row survived next to
   the new ones. Measured on the live table: rows of three files per company,
   +732.000 INTUR / +498.488 ORTI of canone absent from the September sheet.
   The key is now the plan itself (societa, fonte): every ingest replaces the
   whole plan of that company. Decided by Stefano on 2026-10-29.
"""

from types import SimpleNamespace

import pytest

from core.bq.write import _snapshot
from ingest.flussi.ingest_piano_finanziario_xlsx import (
    NATURAL_KEY,
    SOGLIA_SOTTILE,
    assegna_occorrenze,
    make_hash,
    piani_sottili,
    scrivi_su_bq,
)


def _tabella_vuota(monkeypatch):
    monkeypatch.setattr(
        "ingest.flussi.ingest_piano_finanziario_xlsx.righe_in_tabella",
        lambda client=None: {},
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


def test_write_is_a_snapshot_of_the_whole_plan_per_societa_and_fonte(monkeypatch):
    """A new version must REPLACE the whole plan of its company, not its cells.

    After #124 the view SUMs the rows of the winning fonte, so anything left
    behind (an appended revision, or a cell the new sheet no longer has)
    inflates the PF instead of superseding it.
    """
    calls = []
    _tabella_vuota(monkeypatch)
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
    assert set(natural_key) == {"societa_id", "fonte"}, (
        "a key with anno/mese/voce keeps the rows of cells the new sheet dropped"
    )


def test_empty_batch_writes_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "ingest.flussi.ingest_piano_finanziario_xlsx.bq_write_validated",
        lambda *a, **k: calls.append(a),
    )
    scrivi_su_bq([])
    assert calls == []


class _ClientFinto:
    """Cattura la DELETE di _snapshot; l'INSERT va a vuoto."""

    def __init__(self):
        self.sql = []

    def query(self, sql, job_config=None):
        self.sql.append(sql)
        return SimpleNamespace(result=lambda: None)

    def load_table_from_json(self, rows, table, job_config=None):
        return SimpleNamespace(result=lambda: None)


def test_the_delete_covers_the_whole_plan_of_the_company_not_the_cells():
    """Il file di settembre non ha più il canone a ottobre e dicembre (zeri):
    con la chiave per cella quelle righe di luglio restavano; con (societa, fonte)
    la DELETE è una sola tupla per società, qualunque sia il contenuto del file."""
    settembre = assegna_occorrenze(
        [
            _riga(voce="ENTRATE_AFFITTI_INTUR", mese=9, importo=244000.0),
            _riga(voce="ENTRATE_AFFITTI_INTUR", mese=6, importo=244000.0),
            _riga(voce="USCITE_UTENZE", mese=10, importo=3750.0),
        ]
    )
    client = _ClientFinto()
    _snapshot(client, "p.d.f_piano_finanziario_input", settembre, NATURAL_KEY)

    assert len(client.sql) == 1
    delete = " ".join(client.sql[0].split())
    assert delete == (
        "DELETE FROM `p.d.f_piano_finanziario_input` "
        "WHERE (societa_id, fonte) IN ( ('INTUR', 'PIANO_FINANZIARIO') )"
    )
    assert "anno" not in delete and "mese" not in delete and "voce_id" not in delete


def test_the_delete_never_touches_another_fonte_or_company():
    client = _ClientFinto()
    _snapshot(
        client,
        "p.d.f_piano_finanziario_input",
        assegna_occorrenze([_riga()]),
        NATURAL_KEY,
    )
    delete = client.sql[0]
    assert (
        "SCADENZIARIO" not in delete
        and "BVA_2026" not in delete
        and "ORTI" not in delete
    )


# ── Recinto per il file sottile (soglia misurata sui 22 file archiviati, 29/10/2026) ──


def test_la_soglia_separa_le_versioni_legittime_dai_file_sottili_misurati():
    """Peggior legittimo sui 22 file: INTUR 2026-08 56 righe dopo 69 (0,81). File sottili
    misurati: INTUR 2026-05 16 su 65, ORTI 2026-05 23 su 97, ORTI 2026-06 18 su 80."""
    assert SOGLIA_SOTTILE == 0.5
    k = ("INTUR", "PIANO_FINANZIARIO")
    assert piani_sottili({k: 56}, {k: 69}) == []
    assert piani_sottili({k: 16}, {k: 65}) == [
        "INTUR/PIANO_FINANZIARIO: 16 righe nel file contro 65 in tabella (25%)"
    ]
    o = ("ORTI", "PIANO_FINANZIARIO")
    assert (
        len(piani_sottili({o: 23}, {o: 97})) == 1
        and len(piani_sottili({o: 18}, {o: 80})) == 1
    )
    assert piani_sottili({o: 80}, {}) == []  # tabella vuota: nessun confronto possibile
    assert (
        piani_sottili({o: 80}, {("ORTI", "SCADENZIARIO"): 500}) == []
    )  # altra fonte non conta


def test_un_file_sottile_non_viene_scritto_senza_il_flag(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "ingest.flussi.ingest_piano_finanziario_xlsx.righe_in_tabella",
        lambda client=None: {("INTUR", "PIANO_FINANZIARIO"): 80},
    )
    monkeypatch.setattr(
        "ingest.flussi.ingest_piano_finanziario_xlsx.bq_write_validated",
        lambda *a, **k: calls.append(a),
    )
    rows = assegna_occorrenze(
        [_riga(voce=f"USCITE_VOCE_{m}", mese=7) for m in range(18)]
    )  # 18 righe su 80
    with pytest.raises(SystemExit, match="piano sottile, non scrivo"):
        scrivi_su_bq(rows)
    assert calls == []
    scrivi_su_bq(rows, accetta_sottile=True)
    assert len(calls) == 1
