"""Hub registry — contratto del catalogo app-store."""

import ast
import importlib
import importlib.util
import subprocess
import sys
import types
from pathlib import Path

import pytest

from verticals.hub.registry import (
    APPS,
    GROUPS,
    HubApp,
    _lazy_page_target,
    by_group,
    pages,
    validate,
)


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
    assert sens == {
        "cashflow",
        "cassa-consuntivo",
        "accodamenti",
        "revenue",
        "bilancini",
    }


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
    """Importare il registry NON deve caricare nessun modulo di pagina.

    Eseguito in un subprocess isolato per evitare contaminazione con i moduli
    già in sys.modules nella sessione pytest corrente.
    """
    script = (
        "import sys; "
        "import verticals.hub.registry; "
        "assert 'verticals.hub.pages_.cashflow' not in sys.modules, 'cashflow caricato in anticipo'; "
        "assert 'verticals.hub.pages_.revenue' not in sys.modules, 'revenue caricato in anticipo'; "
        "assert 'verticals.hub.pages_.accodamenti' not in sys.modules, 'accodamenti caricato in anticipo';"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_lazy_target_importa_solo_on_demand():
    called = {"ok": False}

    def _fake_render():
        called["ok"] = True

    sys.modules["test.lazy.module"] = types.SimpleNamespace(render=_fake_render)
    target = _lazy_page_target("test.lazy.module")
    target()
    assert called["ok"] is True
    sys.modules.pop("test.lazy.module", None)


def test_lazy_target_modulo_inesistente():
    target = _lazy_page_target("verticals.hub.pages_.nonexistent_xyz")
    with pytest.raises(ModuleNotFoundError):
        target()


def test_lazy_target_attr_mancante():
    sys.modules["test.lazy.norender"] = types.SimpleNamespace()
    target = _lazy_page_target("test.lazy.norender")
    with pytest.raises(AttributeError, match="non espone render"):
        target()
    sys.modules.pop("test.lazy.norender", None)


def test_lazy_target_attr_non_callable():
    sys.modules["test.lazy.notcallable"] = types.SimpleNamespace(
        render="non sono una funzione"
    )
    target = _lazy_page_target("test.lazy.notcallable")
    with pytest.raises(TypeError, match="non è callable"):
        target()
    sys.modules.pop("test.lazy.notcallable", None)


# ── Entrypoint di tutte le pagine registrate ─────────────────────────────────

_PAGE_APPS = [a for a in APPS if a.kind == "page"]


@pytest.mark.parametrize("app", _PAGE_APPS, ids=[a.id for a in _PAGE_APPS])
def test_pagina_registrata_ha_entrypoint(app):
    """Ogni app kind=page ha un modulo trovabile con render() definita top-level.

    Non importa il modulo (evita di richiedere streamlit/plotly nel CI) ma
    verifica che il file esista e contenga la funzione attesa tramite AST.
    """
    # Estrai module_path e attr dalla closure del proxy lazy.
    freevars = app.target.__code__.co_freevars
    closure_vals = {
        n: c.cell_contents for n, c in zip(freevars, app.target.__closure__)
    }
    module_path = closure_vals["module_path"]
    attr = closure_vals.get("attr", "render")

    spec = importlib.util.find_spec(module_path)
    assert spec is not None and spec.origin is not None, (
        f"{module_path}: modulo non trovato nel path Python"
    )

    source = Path(spec.origin).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=spec.origin)
    top_level_fn_names = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    assert attr in top_level_fn_names, (
        f"{module_path}: funzione top-level {attr!r} non trovata"
    )
