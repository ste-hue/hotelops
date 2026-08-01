from datetime import datetime

import pytest

from ingest.pec_imap import ImapConfig, fetch_since

CFG = ImapConfig(host="imaps.pec.aruba.it", port=993, user="x@pec.it", password="s3cret")


class _FakeImap:
    def __init__(self, messages: dict[int, bytes], dates: dict[int, str] | None = None):
        self.messages = messages
        self.dates = dates or {}
        self.selected_readonly = None
        self.logged_out = False

    def login(self, user, password):
        return ("OK", [b""])

    def select(self, mailbox="INBOX", readonly=False):
        self.selected_readonly = readonly
        return ("OK", [b"1"])

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
            return ("OK", [(b"", self.messages[int(args[0])])])
        raise AssertionError(f"comando non previsto: {command}")

    def logout(self):
        self.logged_out = True


def _factory(fake):
    def make(cfg):
        fake.login(cfg.user, cfg.password)
        fake.select("INBOX", readonly=True)
        return fake

    return make


def test_solo_messaggi_dopo_il_watermark() -> None:
    fake = _FakeImap({10: b"dieci", 11: b"undici", 12: b"dodici"})
    got = fetch_since(CFG, since_uid=10, conn_factory=_factory(fake))
    assert [uid for uid, _ in got] == [11, 12]


def test_ultimo_messaggio_non_ritorna_se_sotto_watermark() -> None:
    fake = _FakeImap({10: b"dieci"})
    assert fetch_since(CFG, since_uid=99, conn_factory=_factory(fake)) == []


def test_casella_vuota() -> None:
    fake = _FakeImap({})
    assert fetch_since(CFG, since_uid=0, conn_factory=_factory(fake)) == []


def test_uid_non_contigui() -> None:
    """Buste cancellate a mano dalla webmail lasciano buchi negli UID."""
    fake = _FakeImap({3: b"tre", 17: b"diciassette", 40: b"quaranta"})
    got = fetch_since(CFG, since_uid=3, conn_factory=_factory(fake))
    assert [uid for uid, _ in got] == [17, 40]


def test_casella_aperta_readonly() -> None:
    fake = _FakeImap({1: b"uno"})
    fetch_since(CFG, since_uid=0, conn_factory=_factory(fake))
    assert fake.selected_readonly is True


def test_logout_anche_su_errore() -> None:
    fake = _FakeImap({1: b"uno"})

    def exploding(cfg):
        fake.login(cfg.user, cfg.password)
        fake.select("INBOX", readonly=True)
        fake.uid = lambda *a: (_ for _ in ()).throw(RuntimeError("boom"))
        return fake

    with pytest.raises(RuntimeError):
        fetch_since(CFG, since_uid=0, conn_factory=exploding)
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
    got = fetch_since(
        CFG, since_uid=10, since_date="01-Jul-2026", conn_factory=_factory(fake)
    )
    assert sorted(uid for uid, _ in got) == [5, 20]


def test_byte_restituiti_intatti() -> None:
    raw = b"Return-Path: <posta-certificata@pec.aruba.it>\r\nSubject: t\r\n\r\nbody"
    fake = _FakeImap({5: raw})
    got = fetch_since(CFG, since_uid=0, conn_factory=_factory(fake))
    assert got[0][1] == raw
