from datetime import datetime

import pytest

from ingest import pec_imap
from ingest.pec_imap import ImapConfig, fetch_since

CFG = ImapConfig(host="imaps.pec.aruba.it", port=993, user="x@pec.it", password="s3cret")


class _FakeImap:
    def __init__(
        self,
        messages: dict[int, bytes],
        dates: dict[int, str] | None = None,
        uidvalidity: int | None = 1000,
    ):
        self.messages = messages
        self.dates = dates or {}
        self.uidvalidity = uidvalidity
        self.selected_readonly = None
        self.selected_mailbox = None
        self.logged_out = False
        self.fetch_specs: list[str] = []

    def login(self, user, password):
        return ("OK", [b""])

    def select(self, mailbox="INBOX", readonly=False):
        self.selected_readonly = readonly
        self.selected_mailbox = mailbox
        return ("OK", [b"1"])

    def response(self, name):
        if name == "UIDVALIDITY":
            if self.uidvalidity is None:
                return (name, [None])
            return (name, [str(self.uidvalidity).encode()])
        return (name, [None])

    def uid(self, command, *args):
        if command == "search":
            criterion = " ".join(str(a) for a in args if a is not None)
            uids = sorted(self.messages)
            if criterion.startswith("UID"):
                lo = int(criterion.split()[1].split(":")[0])
                hit = [u for u in uids if u >= lo]
                # comportamento reale: "N:*" torna sempre anche l'ultimo
                if uids and uids[-1] not in hit:
                    hit.append(uids[-1])
                uids = hit
            elif criterion.startswith("SINCE"):
                since = datetime.strptime(criterion.split(maxsplit=1)[1], "%d-%b-%Y").date()
                uids = [
                    u
                    for u in uids
                    if u in self.dates
                    and datetime.strptime(self.dates[u], "%d-%b-%Y").date() >= since
                ]
            return ("OK", [" ".join(str(u) for u in uids).encode()])
        if command == "fetch":
            self.fetch_specs.append(args[1])
            return ("OK", [(b"", self.messages[int(args[0])])])
        raise AssertionError(f"comando non previsto: {command}")

    def logout(self):
        self.logged_out = True


def _factory(fake):
    def make(cfg, folder="INBOX"):
        fake.login(cfg.user, cfg.password)
        fake.select(folder, readonly=True)
        return fake

    return make


def _messages(*args, **kwargs):
    """Appiattisce i blocchi: i test che non parlano di chunking li ignorano."""
    return [m for blk in fetch_since(*args, **kwargs) for m in blk.messages]


def test_solo_messaggi_dopo_il_watermark() -> None:
    fake = _FakeImap({10: b"dieci", 11: b"undici", 12: b"dodici"})
    got = _messages(CFG, since_uid=10, conn_factory=_factory(fake))
    assert [uid for uid, _ in got] == [11, 12]


def test_ultimo_messaggio_non_ritorna_se_sotto_watermark() -> None:
    fake = _FakeImap({10: b"dieci"})
    assert _messages(CFG, since_uid=99, conn_factory=_factory(fake)) == []


def test_casella_vuota() -> None:
    fake = _FakeImap({})
    assert _messages(CFG, since_uid=0, conn_factory=_factory(fake)) == []


def test_uid_non_contigui() -> None:
    """Buste cancellate a mano dalla webmail lasciano buchi negli UID."""
    fake = _FakeImap({3: b"tre", 17: b"diciassette", 40: b"quaranta"})
    got = _messages(CFG, since_uid=3, conn_factory=_factory(fake))
    assert [uid for uid, _ in got] == [17, 40]


def test_casella_aperta_readonly() -> None:
    fake = _FakeImap({1: b"uno"})
    _messages(CFG, since_uid=0, conn_factory=_factory(fake))
    assert fake.selected_readonly is True


def test_logout_anche_su_errore() -> None:
    fake = _FakeImap({1: b"uno"})

    def exploding(cfg, folder="INBOX"):
        fake.login(cfg.user, cfg.password)
        fake.select(folder, readonly=True)
        fake.uid = lambda *a: (_ for _ in ()).throw(RuntimeError("boom"))
        return fake

    with pytest.raises(RuntimeError):
        _messages(CFG, since_uid=0, conn_factory=exploding)
    assert fake.logged_out is True


def test_since_date_recupera_uid_sotto_il_watermark() -> None:
    """La finestra di sicurezza SINCE deve recuperare buste con UID basso
    (sotto il watermark) purché la data ricada nella finestra — è il caso
    d'uso per cui il parametro esiste. Il content-hash all'intake dedup
    contro quanto già visto via UID."""
    fake = _FakeImap(
        {5: b"cinque", 20: b"venti"},
        dates={5: "15-Jul-2026", 20: "20-Jul-2026"},
    )
    got = _messages(
        CFG, since_uid=10, since_date="01-Jul-2026", conn_factory=_factory(fake)
    )
    assert sorted(uid for uid, _ in got) == [5, 20]


def test_cartella_passata_a_select() -> None:
    fake = _FakeImap({1: b"uno"})
    _messages(CFG, since_uid=0, folder="INBOX.Inviata", conn_factory=_factory(fake))
    assert fake.selected_mailbox == "INBOX.Inviata"


def test_cartella_inviata_aperta_readonly() -> None:
    """Il vincolo di sola lettura resta assoluto anche sulla cartella Inviata."""
    fake = _FakeImap({1: b"uno"})
    _messages(CFG, since_uid=0, folder="INBOX.Inviata", conn_factory=_factory(fake))
    assert fake.selected_readonly is True


def test_default_cartella_e_inbox() -> None:
    fake = _FakeImap({1: b"uno"})
    _messages(CFG, since_uid=0, conn_factory=_factory(fake))
    assert fake.selected_mailbox == "INBOX"


def test_byte_restituiti_intatti() -> None:
    raw = b"Return-Path: <posta-certificata@pec.aruba.it>\r\nSubject: t\r\n\r\nbody"
    fake = _FakeImap({5: raw})
    got = _messages(CFG, since_uid=0, conn_factory=_factory(fake))
    assert got[0][1] == raw


# --- sola lettura sul vero _connect -----------------------------------------


class _RecordingIMAP4SSL:
    """Sostituisce imaplib.IMAP4_SSL: registra cosa riceve davvero."""

    instances: list["_RecordingIMAP4SSL"] = []

    def __init__(self, host, port):
        self.host, self.port = host, port
        self.login_args = None
        self.select_args = None
        type(self).instances.append(self)

    def login(self, user, password):
        self.login_args = (user, password)
        return ("OK", [b""])

    def select(self, mailbox="INBOX", readonly=False):
        self.select_args = (mailbox, readonly)
        return ("OK", [b"1"])


@pytest.fixture
def recording_ssl(monkeypatch):
    _RecordingIMAP4SSL.instances = []
    monkeypatch.setattr(pec_imap.imaplib, "IMAP4_SSL", _RecordingIMAP4SSL)
    return _RecordingIMAP4SSL


def test_connect_seleziona_readonly(recording_ssl) -> None:
    """Il vincolo Critical va verificato sul vero _connect, non sul fake:
    se qualcuno mettesse readonly=False qui, questo test deve diventare rosso."""
    pec_imap._connect(CFG, folder="INBOX.Inviata")
    conn = recording_ssl.instances[0]
    assert conn.select_args == ("INBOX.Inviata", True)


def test_connect_usa_le_credenziali_della_config(recording_ssl) -> None:
    pec_imap._connect(CFG)
    conn = recording_ssl.instances[0]
    assert (conn.host, conn.port) == ("imaps.pec.aruba.it", 993)
    assert conn.login_args == ("x@pec.it", "s3cret")


def test_password_non_finisce_nel_repr() -> None:
    assert "s3cret" not in repr(CFG)


def test_fetch_usa_body_peek_e_non_rfc822() -> None:
    """RFC822 setta \\Seen: oggi non succede solo perché la sessione è
    readonly. BODY.PEEK[] rende la garanzia indipendente dalla sessione."""
    fake = _FakeImap({1: b"uno", 2: b"due"})
    _messages(CFG, since_uid=0, conn_factory=_factory(fake))
    assert fake.fetch_specs == ["(BODY.PEEK[])", "(BODY.PEEK[])"]


# --- chunking ---------------------------------------------------------------


def test_blocchi_da_chunk_size() -> None:
    fake = _FakeImap({u: b"x" for u in range(1, 8)})
    blocks = list(fetch_since(CFG, since_uid=0, conn_factory=_factory(fake), chunk_size=3))
    assert [[uid for uid, _ in b.messages] for b in blocks] == [[1, 2, 3], [4, 5, 6], [7]]


def test_blocchi_in_uid_crescente() -> None:
    """Il progresso monotono del watermark dipende da questo ordine."""
    fake = _FakeImap({40: b"x", 3: b"x", 17: b"x"})
    got = _messages(CFG, since_uid=0, conn_factory=_factory(fake), chunk_size=2)
    assert [uid for uid, _ in got] == [3, 17, 40]


def test_i_blocchi_gia_scaricati_restano_se_uno_dopo_fallisce() -> None:
    """Il guasto a metà cartella non deve buttare via i blocchi buoni."""
    fake = _FakeImap({1: b"a", 2: b"b", 3: b"c", 4: b"d"})
    real_uid = fake.uid

    def flaky(command, *args):
        if command == "fetch" and int(args[0]) == 3:
            raise ConnectionError("EOF")
        return real_uid(command, *args)

    fake.uid = flaky
    got = []
    with pytest.raises(ConnectionError):
        for blk in fetch_since(CFG, since_uid=0, conn_factory=_factory(fake), chunk_size=2):
            got.extend(uid for uid, _ in blk.messages)
    assert got == [1, 2]


def test_fetch_fallita_solleva_e_non_salta_la_busta() -> None:
    """Saltare un UID farebbe scavalcare il watermark su una busta mai
    scaricata: perdita silenziosa e definitiva su un archivio probatorio."""
    fake = _FakeImap({1: b"uno", 2: b"due"})
    real_uid = fake.uid

    def broken(command, *args):
        if command == "fetch" and int(args[0]) == 1:
            return ("NO", [None])
        return real_uid(command, *args)

    fake.uid = broken
    with pytest.raises(RuntimeError, match="UID 1"):
        _messages(CFG, since_uid=0, conn_factory=_factory(fake))


# --- UIDVALIDITY ------------------------------------------------------------


def test_uidvalidity_riportata_nei_blocchi() -> None:
    fake = _FakeImap({1: b"uno"}, uidvalidity=987)
    blocks = list(fetch_since(CFG, since_uid=0, conn_factory=_factory(fake)))
    assert blocks[0].uidvalidity == 987


def test_uidvalidity_cambiata_azzera_il_watermark() -> None:
    """Cartella ricreata lato server: gli UID ripartono da 1 e un watermark
    alto sopprimerebbe tutto in silenzio."""
    fake = _FakeImap({1: b"uno", 2: b"due"}, uidvalidity=2)
    blocks = list(
        fetch_since(CFG, since_uid=500, uidvalidity=1, conn_factory=_factory(fake))
    )
    assert [uid for blk in blocks for uid, _ in blk.messages] == [1, 2]
    assert blocks[0].base_uid == 0


def test_uidvalidity_invariata_non_azzera() -> None:
    fake = _FakeImap({1: b"uno", 700: b"settecento"}, uidvalidity=1)
    blocks = list(
        fetch_since(CFG, since_uid=500, uidvalidity=1, conn_factory=_factory(fake))
    )
    assert [uid for blk in blocks for uid, _ in blk.messages] == [700]
    assert blocks[0].base_uid == 500


def test_watermark_legacy_senza_uidvalidity_non_azzera() -> None:
    """I watermark già in produzione non hanno uidvalidity: senza riferimento
    non si può dire che la cartella sia cambiata, quindi non si riscarica."""
    fake = _FakeImap({1: b"uno", 700: b"settecento"}, uidvalidity=42)
    blocks = list(
        fetch_since(CFG, since_uid=500, uidvalidity=None, conn_factory=_factory(fake))
    )
    assert [uid for blk in blocks for uid, _ in blk.messages] == [700]
    assert blocks[0].base_uid == 500


def test_server_senza_uidvalidity_non_rompe() -> None:
    """Server che non espone UIDVALIDITY: si degrada al comportamento di
    prima (nessun azzeramento), non si rompe e non si riscarica tutto."""
    fake = _FakeImap({1: b"uno", 700: b"settecento"}, uidvalidity=None)
    blocks = list(
        fetch_since(CFG, since_uid=500, uidvalidity=999, conn_factory=_factory(fake))
    )
    assert blocks[0].uidvalidity is None
    assert blocks[0].base_uid == 500
    assert [uid for blk in blocks for uid, _ in blk.messages] == [700]
