"""Hub registry — contratto del catalogo app-store."""

import importlib
import sys

import pytest

from verticals.hub.registry import APPS, GROUPS, HubApp, by_group, pages, validate


def test_validate_ok():
    validate()  # il registry reale non solleva


def test_ids_unici():
    ids = [a.id for a in APPS]
    assert len(ids) == len(set(ids))


def test_target_coerente_col_kind():
    for a in APPS:
        if a.kind == "page":
            assert callable(a.target), a.id
        elif a.kind == "bind":
            assert isinstance(a.target, str) and a.target.startswith("https://"), a.id
        elif a.kind == "soon":
            assert a.target is None, a.id
        else:
            raise AssertionError(f"kind sconosciuto: {a.kind}")


def test_pages_solo_kind_page():
    assert all(a.kind == "page" for a in pages())
    assert {a.id for a in pages()} == {
        "cashflow",
        "cassa-consuntivo",
        "bilancini",
        "accodamenti",
        "mutui",
        "fb",
        "spiaggia",
        "reviews",
        "revenue",
    }


def test_by_group_ordine_e_contenuto():
    g = by_group()
    assert list(g.keys()) == GROUPS
    assert "cashflow" in {a.id for a in g["Finanza"]}
    assert "accodamenti" in {a.id for a in g["Finanza"]}
    assert "revenue" in {a.id for a in g["Finanza"]}
    assert "fb" in {a.id for a in g["Operations"]}
    assert g["Sistema"] == []  # ingest non è una sezione: è funzione del vertical


def test_validate_rifiuta_page_senza_callable():
    with pytest.raises(ValueError):
        validate([HubApp("x", "X", "❌", "Finanza", "page", "not-callable", None)])


def test_validate_rifiuta_group_sconosciuto():
    with pytest.raises(ValueError):
        validate([HubApp("x", "X", "❌", "Nope", "soon", None, None)])


def test_validate_rifiuta_id_duplicato():
    a = HubApp("dup", "A", "🅰", "Finanza", "soon", None, None)
    with pytest.raises(ValueError):
        validate([a, a])


def test_cashflow_accodamenti_sono_sensibili():
    # cdg non è più qui: spento (kind=soon, 2026-07-05) → niente superficie di scrittura
    from verticals.hub.registry import APPS

    sens = {a.id for a in APPS if a.sensitive}
    # revenue: sensibile dal 2026-07-13 (upload foto OTB = write-path via lineage).
    # bilancini: sensibile dal 2026-07-14 (dati riservati, come cassa-consuntivo:
    # nessun write-path, solo lettura BQ).
    # spiaggia NON è sensibile: l'uploader Moolty è gated per-utente nel wrapper
    # (pages_/spiaggia._MOOLTY_UPLOADERS) — la pagina resta lettura per Operations.
    assert sens == {"cashflow", "cassa-consuntivo", "accodamenti", "revenue", "bilancini"}


def test_pages_for_filtra_su_allowed():
    from verticals.hub.registry import pages_for

    got = {a.id for a in pages_for(frozenset({"reviews", "fb"}))}
    assert got == {"reviews", "fb"}
    assert {a.id for a in pages_for(frozenset())} == set()


def test_by_group_for_filtra_e_mantiene_ordine():
    from verticals.hub.registry import GROUPS, by_group_for

    g = by_group_for(frozenset({"reviews"}))
    assert list(g.keys()) == GROUPS  # tutti i gruppi presenti (anche vuoti)
    assert {a.id for a in g["Operations"]} == {"reviews"}
    assert g["Finanza"] == []


def test_registry_non_importa_pages_a_boot():
    sys.modules.pop("verticals.hub.registry", None)
    for m in (
        "verticals.hub.pages_.cashflow",
        "verticals.hub.pages_.revenue",
        "verticals.hub.pages_.accodamenti",
    ):
        sys.modules.pop(m, None)

    importlib.import_module("verticals.hub.registry")

    assert "verticals.hub.pages_.cashflow" not in sys.modules
    assert "verticals.hub.pages_.revenue" not in sys.modules
