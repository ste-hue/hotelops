"""Hub registry — contratto del catalogo app-store."""

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
        "cashflow", "mutui", "fb", "spiaggia", "reviews", "ingest",
    }


def test_by_group_ordine_e_contenuto():
    g = by_group()
    assert list(g.keys()) == GROUPS
    assert "cashflow" in {a.id for a in g["Finanza"]}
    assert "fb" in {a.id for a in g["Operations"]}
    assert "ingest" in {a.id for a in g["Sistema"]}


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
