"""Test di CONFIGURAZIONE su core/registry.yaml — non del codice.

Verificano proprietà del registry reale: che nessuna firma sia ambigua, e che
ogni categoria firmata risolva a una source in core/source_registry.yaml.
Il secondo, se fosse esistito, avrebbe mostrato i 4 source_name orfani a maggio.
"""

from pathlib import Path

from core.lineage.source_resolver import load_registry
from ingest.signatures import _entry_is_supported, identify, load_file_types

# Le categorie Power BI che questo giro porta sotto firma dichiarativa.
ATTESE = {
    "andamento_prenotazioni",
    "bookings_tipologia",
    "consprev_mensile",
    "consprev_pax",
    "dettaglio_prenotazioni",
    "menu_engineering",
    "numero_camera_clienti",
    "occupazione_pms",
    "produzione_pms",
    "vendite_fb",
}


def _signed() -> dict:
    return {k: v for k, v in load_file_types().items() if _entry_is_supported(v)}


def _fixture_from_entry(path: Path, entry: dict) -> Path:
    """Costruisce l'xlsx minimo che la entry dichiara di riconoscere."""
    from openpyxl import Workbook

    sheet = "Sheet1"
    header: list[str] = []
    for sig in entry["signatures"]:
        if sig["type"] == "sheets":
            sheet = sig["required"][0]
        elif sig["type"] == "structure":
            header = list(sig["header_prefix"])
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(header)
    wb.save(path)
    return path


def test_le_dieci_categorie_powerbi_hanno_una_firma():
    # Uguaglianza, non sottoinsieme: se una categoria legacy diventasse
    # valutabile si unirebbe silenziosamente al set supportato e potrebbe
    # dirottare il proprio detector — con `==` "nessuna categoria legacy
    # è migrata" è imposto, non solo vero per il momento.
    assert set(_signed()) == ATTESE


def test_nessuna_firma_e_ambigua(tmp_path):
    """Ogni entry riconosce la propria fixture e nessun'altra.

    identify() solleva AmbiguousSignature se due entry matchano: il test
    fallisce da solo, senza bisogno di asserirlo.
    """
    signed = _signed()
    assert signed, "nessuna entry valutabile — il valutatore non è collegato"
    for cat, entry in signed.items():
        f = _fixture_from_entry(tmp_path / f"{cat}.xlsx", entry)
        assert identify(f, signed) == cat


def test_ogni_categoria_firmata_risolve_a_una_source():
    # Esattamente una, non almeno una: _classify_by_signature deriva
    # lifecycle/societa/parser_module con un helper (_unico) che è
    # significativo solo quando la categoria risolve a una source sola.
    reg = load_registry()
    for cat in _signed():
        assert len(reg.find_all_by_detector_category(cat)) == 1, (
            f"{cat}: firma in core/registry.yaml non risolve a esattamente "
            f"una source in core/source_registry.yaml"
        )
