"""Test del valutatore di firme dichiarative (ingest.signatures).

Le fixture sono xlsx sintetici: nome foglio + sola riga d'header, che è
esattamente ciò che una firma legge. Nessun file di produzione nel repo.
"""

from pathlib import Path

import pytest

from ingest.signatures import (
    AmbiguousSignature,
    _entry_is_supported,
    identify,
    matches,  # noqa: F401 (public API, used in test_registry_signatures)
)


def _xlsx(path: Path, sheet: str, header: list[str]) -> Path:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(header)
    wb.save(path)
    return path


FT = {
    "numero_camera_clienti": {
        "formats": [".xlsx"],
        "signatures": [
            {"type": "sheets", "required": ["Export"]},
            {
                "type": "structure",
                "header_prefix": ["Camera", "Volte", "ARB", "Infant"],
            },
        ],
    },
    "occupazione_pms": {
        "formats": [".xlsx"],
        "signatures": [
            {"type": "sheets", "required": ["Export"]},
            {
                "type": "structure",
                "header_prefix": ["Data", "Cam. Totali", "OOO", "Cam. Vendibili"],
            },
        ],
    },
    "legacy_da_saltare": {
        "formats": [".xlsx"],
        "signatures": [
            {"type": "sheets", "required": ["Export"]},
            {"type": "structure", "header_0_2": ["Camera", "Volte", "ARB"]},
        ],
    },
}


def test_identifica_dal_prefisso_header(tmp_path):
    f = _xlsx(
        tmp_path / "data.xlsx",
        "Export",
        ["Camera", "Volte", "ARB", "Infant", "ADR"],
    )
    assert identify(f, FT) == "numero_camera_clienti"


def test_foglio_sbagliato_non_matcha(tmp_path):
    f = _xlsx(
        tmp_path / "data.xlsx",
        "Foglio1",
        ["Camera", "Volte", "ARB", "Infant"],
    )
    assert identify(f, FT) is None


def test_header_diverso_non_matcha(tmp_path):
    f = _xlsx(tmp_path / "data.xlsx", "Export", ["Giorno", "Camere", "ARB"])
    assert identify(f, FT) is None


def test_entry_con_grammatica_legacy_viene_saltata():
    assert _entry_is_supported(FT["numero_camera_clienti"]) is True
    assert _entry_is_supported(FT["legacy_da_saltare"]) is False


def test_grammatica_legacy_non_matcha_mai(tmp_path):
    """Un file che soddisfa header_0_2 non viene identificato: resta ai detector."""
    f = _xlsx(tmp_path / "data.xlsx", "Export", ["Camera", "Volte", "ARB"])
    assert identify(f, {"legacy_da_saltare": FT["legacy_da_saltare"]}) is None


def test_estensione_non_ammessa_non_matcha(tmp_path):
    f = tmp_path / "data.csv"
    f.write_text("Camera,Volte,ARB,Infant\n")
    assert identify(f, FT) is None


def test_due_entry_che_matchano_sollevano(tmp_path):
    doppione = {
        "a": FT["numero_camera_clienti"],
        "b": FT["numero_camera_clienti"],
    }
    f = _xlsx(tmp_path / "data.xlsx", "Export", ["Camera", "Volte", "ARB", "Infant"])
    with pytest.raises(AmbiguousSignature):
        identify(f, doppione)
