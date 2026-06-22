"""Hub roles — risoluzione identità → app concesse."""

from verticals.hub.roles import (
    ALL,
    FINANZA,
    OPERATIONS,
    _email_from_headers,
    _parse_email,
    _resolve,
)


def test_parse_email_strip_prefisso_iap():
    assert _parse_email("accounts.google.com:foo@bar.it") == "foo@bar.it"
    assert _parse_email("foo@bar.it") == "foo@bar.it"
    assert _parse_email(None) is None
    assert _parse_email("") is None


def test_email_from_headers_case_insensitive():
    h = {"x-goog-authenticated-user-email": "accounts.google.com:fom@panoramagroup.it"}
    assert _email_from_headers(h) == "fom@panoramagroup.it"
    assert _email_from_headers({}) is None
    assert _email_from_headers(None) is None


def test_costanti_gruppo_escludono_sensibili_S1():
    from verticals.hub.registry import APPS

    sens = {a.id for a in APPS if a.sensitive}
    assert sens  # esistono app sensibili
    assert not (FINANZA & sens)
    assert not (OPERATIONS & sens)
    assert "cashflow" not in FINANZA
    assert "banche" in FINANZA and "mutui" in FINANZA


def test_anna_solo_operations():
    apps = _resolve("fom@panoramagroup.it", allow_all=False)
    assert apps == frozenset({"fb", "spiaggia", "reviews"})
    assert "cashflow" not in apps and "accodamenti" not in apps


def test_rosa_finanza_con_cashflow_accodamenti_spiaggia():
    apps = _resolve("amministrazione@panoramagroup.it", allow_all=False)
    # accodamenti (sensitive) + spiaggia concessi a mano a Rosa (cassa/Gaia), non da FINANZA (S1)
    assert {"cashflow", "mutui", "banche", "cdg", "accodamenti", "spiaggia"} <= apps
    assert "fb" not in apps


def test_antonio_e_padre_tutto_tranne_scrittura_a_mano():
    for email in ("gm@panoramagroup.it", "stedepi@gmail.com"):
        apps = _resolve(email, allow_all=False)
        # accodamenti è sensitive → non ereditato, solo admin a mano
        assert "accodamenti" not in apps
        assert {"cashflow", "reviews", "fb", "spiaggia", "mutui"} <= apps


def test_mario_solo_fb_e_spiaggia():
    apps = _resolve("magazzino@panoramagroup.it", allow_all=False)
    assert apps == frozenset({"fb", "spiaggia"})


def test_admin_vede_tutto():
    apps = _resolve("stefano@panoramagroup.it", allow_all=False)
    assert apps == ALL
    assert "accodamenti" in apps and "cashflow" in apps


def test_email_ignota_deny():
    assert _resolve("chiunque@panoramagroup.it", allow_all=False) == frozenset()


def test_no_header_fail_closed_di_default():
    assert _resolve(None, allow_all=False) == frozenset()


def test_no_header_bypass_solo_esplicito():
    assert _resolve(None, allow_all=True) == ALL


def test_header_presente_vince_sul_bypass():
    apps = _resolve("fom@panoramagroup.it", allow_all=True)
    assert apps == frozenset({"fb", "spiaggia", "reviews"})


def test_assert_s1_blocca_costante_con_app_sensibile():
    import pytest

    from verticals.hub.roles import _assert_s1

    with pytest.raises(AssertionError, match="S1 violata"):
        _assert_s1("FAKE", frozenset({"cashflow"}))  # cashflow è sensibile


def test_assert_s1_passa_costante_pulita():
    from verticals.hub.roles import _assert_s1

    safe = frozenset({"fb", "spiaggia"})
    assert _assert_s1("OK", safe) == safe
