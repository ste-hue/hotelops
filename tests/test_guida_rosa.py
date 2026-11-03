from pathlib import Path

from verticals.condges.guida_rosa import a_html, sezione_rosa

PROCEDURA = Path("docs/procedures/cashflow_mensile.md")


def test_la_sezione_di_rosa_si_estrae_dalla_procedura_vera():
    s = sezione_rosa(PROCEDURA.read_text(encoding="utf-8"))
    assert s.startswith("## A. Rosa") and "## B." not in s and "## C." not in s
    # i gate che Rosa deve vedere, con le sue parole
    for frase in (
        "sette i conti",
        "fail (blocca)",
        "salva da Excel",
        "ERR = 0",
        "non carica niente",
    ):
        assert frase in s, frase
    # niente termini nostri nella sezione A
    for vietato in (
        "python -m",
        "SHA",
        "BigQuery",
        "f_pf_rotazioni",
        "hotelops pf-rotate",
    ):
        assert vietato not in s, vietato


def test_la_guida_html_porta_titoli_elenchi_e_grassetto():
    h = a_html(sezione_rosa(PROCEDURA.read_text(encoding="utf-8")))
    assert (
        h.startswith("<!doctype html>")
        and "<h2>A3. La rotazione nell'app Cashflow</h2>" in h
    )
    assert "<ol>" in h and "<li>" in h and "<strong>Società</strong>" in h
    assert "<code>ORTI_PF_AAAA-MM.xlsx</code>" in h
    assert "## " not in h and "**" not in h


def test_senza_sezione_a_si_ferma():
    import pytest

    with pytest.raises(ValueError):
        sezione_rosa("# niente\n\n## B. Stefano\n")
