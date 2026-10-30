"""Hub — contratti di montaggio delle pagine."""


def test_reviews_render_importabile():
    from verticals.reviews.app import main, render

    assert callable(render)
    assert callable(main)


def test_reviews_render_non_chiama_set_page_config():
    # set_page_config deve stare SOLO in main() (contratto fb_dashboard):
    # render() montata dal hub non può richiamarlo (Streamlit lo vieta 2 volte).
    import inspect

    from verticals.reviews import app

    src = inspect.getsource(app.render)
    assert "set_page_config" not in src


def test_pagine_hub_importabili():
    from verticals.hub import home
    from verticals.hub.pages_ import fb, reviews

    assert callable(home.render)
    assert callable(fb.render)
    assert callable(reviews.render)


def test_fb_degrada_senza_fb_dashboard():
    # fb_dashboard non è ancora su main: l'import della PAGINA non deve esplodere
    # (il fallback vive dentro render(), non a import-time).
    import importlib

    from verticals.hub.pages_ import fb

    importlib.reload(fb)


def test_ingest_page_importabile():
    from verticals.hub.pages_ import ingest

    assert callable(ingest.render)


def test_mutui_page_importabile():
    # caso B1: embed di un artifact esterno (Worker Cloudflare) in iframe.
    from verticals.hub.pages_ import mutui

    assert callable(mutui.render)
    assert mutui.MUTUI_URL.startswith("https://")


def test_home_render_riceve_page_objs_e_allowed():
    import inspect

    from verticals.hub import home

    sig = inspect.signature(home.render)
    assert "page_objs" in sig.parameters
    assert "allowed" in sig.parameters


def test_home_usa_by_group_for_e_landing():
    from pathlib import Path

    src = Path("verticals/hub/home.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))
    assert "by_group_for" in code
    # landing quando non c'è nessuna app concessa
    assert "allowed" in code


def test_spiaggia_page_importabile():
    from verticals.hub.pages_ import spiaggia

    assert callable(spiaggia.render)


def test_spiaggia_render_non_chiama_set_page_config():
    # set_page_config deve stare SOLO in __main__ (contratto hub-bind):
    # render() montata dal hub non può richiamarlo (Streamlit lo vieta 2 volte).
    # Usiamo "st.set_page_config" per evitare falsi positivi da docstring/commenti.
    import inspect

    from verticals.spiaggia import app

    src = inspect.getsource(app.render)
    assert "st.set_page_config" not in src


def test_audience_senza_grant_non_riceve_accodamenti():
    # accodamenti (sensitive) è concesso a mano solo ad admin + Rosa (cassa/Gaia).
    # Chi non ha il grant esplicito non lo riceve, anche se è in Finanza/Operations.
    from verticals.hub.roles import _resolve

    for email in ("gm@panoramagroup.it", "fom@panoramagroup.it"):
        assert "accodamenti" not in _resolve(email, allow_all=False)


def test_spiaggia_upload_gated_per_utente():
    # la pagina spiaggia resta read-only di default: l'uploader Moolty compare
    # solo se il wrapper hub passa can_upload=True (identità edge)
    import inspect

    from verticals.spiaggia.app import render

    sig = inspect.signature(render)
    assert sig.parameters["can_upload"].default is False


# ── Home come lista (30/10/2026): HTML puro da registry + pagine, testabile senza Streamlit ──


class _PaginaFinta:
    def __init__(self, url_path):
        self.url_path = url_path


def test_home_lista_una_riga_per_app_con_un_bottone_solo():
    from verticals.hub.home import lista_html
    from verticals.hub.registry import HubApp

    groups = {
        "Finanza": [
            HubApp(
                "cashflow",
                "Cashflow",
                "💸",
                "Finanza",
                "page",
                lambda: None,
                "PF & <cassa>",
            ),
            HubApp(
                "banche",
                "Banche",
                "🏛",
                "Finanza",
                "bind",
                "https://looker.example/x?a=1&b=2",
                "Looker",
            ),
            HubApp("domani", "Domani", "🔜", "Finanza", "soon", None, ""),
        ],
        "Operations": [],
    }
    out = lista_html(groups, {"cashflow": _PaginaFinta("cashflow")})
    assert out.count('<li class="pg-riga">') == 3
    assert out.count('<section class="pg-gruppo">') == 1, (
        "un gruppo vuoto non si disegna"
    )
    assert 'href="/cashflow">Apri</a>' in out
    assert (
        'href="https://looker.example/x?a=1&amp;b=2" target="_blank" rel="noopener">Apri ↗</a>'
        in out
    )
    assert '<span class="pg-apri pg-presto">presto</span>' in out
    assert "PF &amp; &lt;cassa&gt;" in out, "il sottotitolo si scappa"
    # un bottone per riga, non uno di piu'
    assert out.count("pg-apri") == 3


def test_home_lista_pagina_non_montata_diventa_presto():
    from verticals.hub.home import lista_html
    from verticals.hub.registry import HubApp

    groups = {"Finanza": [HubApp("x", "X", "✳", "Finanza", "page", lambda: None, "")]}
    out = lista_html(groups, {})
    assert "pg-presto" in out and "href=" not in out
