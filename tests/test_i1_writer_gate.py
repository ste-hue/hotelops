"""I1 ratchet: nessuna scrittura BigQuery fuori da core/bq/write.py (issue #152).

Scansiona `ingest/` e `verticals/` con `ast` (niente falsi positivi da commenti
o docstring) e fallisce se un file chiama un writer BQ diretto. L'allowlist
qui sotto è il debito legacy censito nella #152: può solo accorciarsi. Un
file in allowlist che NON usa più la scrittura diretta fa fallire il test
finché non viene rimosso dalla lista (ratchet).
"""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("ingest", "verticals")

DIRECT_WRITE_METHODS = {
    "load_table_from_json",
    "load_table_from_dataframe",
    "insert_rows_json",
}
DIRECT_WRITE_CALLS = {"LoadJobConfig"}

# Debito legacy (#152). Rimuovere una voce = migrare quel file a bq_write_validated.
ALLOWLIST = {
    # Gli otto restanti dei nove della #152 (ingest_bilancino.py migrato)
    "ingest/flussi/ingest_fatture.py",  # #152 — load_table_from_json + WRITE_APPEND
    "ingest/flussi/ingest_movimenti_contabili.py",  # #152 — idem, DELETE a mano
    "ingest/flussi/ingest_gasparotto.py",  # #152 — idem, DELETE a mano
    "ingest/flussi/ingest_bilanci_annuali.py",  # #152 — idem, DELETE a mano
    "ingest/flussi/ingest_pms_statistiche.py",  # #152 — LoadJobConfig(WRITE_APPEND) + dataframe
    "ingest/flussi/ingest_consumi_economato.py",  # #152 — load_table_from_json
    "ingest/flussi/ingest_consumi_economato_consolidato.py",  # #152 — load_table_from_json
    "ingest/flussi/ingest_scheda_190101.py",  # #152 — load_table_from_json
    # Trovati dalla scansione, NON elencati nella #152
    "ingest/flussi/ingest_coperti.py",  # #152 (extra) — branch --replace: full wipe + load fuori gate
    "ingest/banca/ingest_accodamenti.py",  # #152 (extra) — load_table_from_dataframe
    "verticals/condges/cli_commands.py",  # #152 (extra) — insert_rows_json f_chiusura_mensile
    "verticals/reviews/ingest.py",  # #152 (extra) — insert_rows_json f_reviews
    "verticals/reviews/scrape.py",  # #152 (extra) — insert_rows_json f_apify_runs
}


def _direct_writes(path: Path) -> list[str]:
    """Return 'lineno: name' for every direct BQ write found in `path`."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in DIRECT_WRITE_METHODS:
            hits.append(f"{node.lineno}: {node.attr}")
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            if name in DIRECT_WRITE_CALLS:
                hits.append(f"{node.lineno}: {name}(")
    return hits


def _scan() -> dict[str, list[str]]:
    found = {}
    for d in SCAN_DIRS:
        for path in sorted((REPO / d).rglob("*.py")):
            hits = _direct_writes(path)
            if hits:
                found[path.relative_to(REPO).as_posix()] = hits
    return found


def test_no_direct_bq_write_outside_gate():
    offenders = {f: h for f, h in _scan().items() if f not in ALLOWLIST}
    assert not offenders, (
        "Scrittura BigQuery diretta fuori da core/bq/write.py (I1, #152). "
        "Usa bq_write_validated:\n"
        + "\n".join(f"  {f}: {h}" for f, h in offenders.items())
    )


def test_allowlist_only_contains_files_that_still_write_directly():
    found = _scan()
    stale = sorted(f for f in ALLOWLIST if f not in found)
    assert not stale, (
        "File in ALLOWLIST che non scrivono più direttamente su BQ: "
        "rimuovili dalla lista (ratchet #152):\n" + "\n".join(f"  {f}" for f in stale)
    )
