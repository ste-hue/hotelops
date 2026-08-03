import pytest

from core.lineage.source_resolver import load_registry

CASELLE = [
    ("PEC_MAILBOX_INTUR_APPEND", "in.tur@pec.it", "imaps.pec.aruba.it", "PEC_PASSWORD_INTUR"),
    ("PEC_MAILBOX_ORTI_APPEND", "orti@pec.it", "imaps.pec.aruba.it", "PEC_PASSWORD_ORTI"),
    ("PEC_MAILBOX_VIGNA_APPEND", "vineyardamalficoast@pec.it", "imaps.pec.aruba.it", "PEC_PASSWORD_VIGNA"),
]


@pytest.mark.parametrize("name,casella,host,env", CASELLE)
def test_imap_block_presente(name, casella, host, env) -> None:
    sd = load_registry().get(name)
    assert sd.imap is not None, f"{name} senza blocco imap"
    assert sd.imap.host == host
    assert sd.imap.port == 993
    assert sd.imap.password_env == env
    # la casella NON si duplica nel blocco imap: è già un campo della sorgente
    assert sd.casella == casella


@pytest.mark.parametrize("name,_c,_h,_e", CASELLE)
def test_eml_accettato(name, _c, _h, _e) -> None:
    """Il fetcher produce .eml: il promote deve accettarlo."""
    sd = load_registry().get(name)
    assert "eml" in sd.input_formats, f"{name} non accetta eml"


@pytest.mark.parametrize("name,_c,_h,_e", CASELLE)
def test_folders_include_inbox_e_inviata(name, _c, _h, _e) -> None:
    sd = load_registry().get(name)
    assert sd.imap.folders == ["INBOX", "INBOX.Inviata"]


def test_personale_resta_senza_blocco_imap() -> None:
    sd = load_registry().get("PEC_MAILBOX_PERSONALE_APPEND")
    assert sd.imap is None


def test_imap_model_non_ha_campo_password() -> None:
    from core.lineage.schemas import ImapMailbox

    assert "password" not in ImapMailbox.model_fields
    assert "user" not in ImapMailbox.model_fields


def test_nessun_smtp_nel_registry() -> None:
    text = open("core/source_registry.yaml", encoding="utf-8").read().lower()
    assert "smtp" not in text
