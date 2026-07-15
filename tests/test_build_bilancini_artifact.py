"""Tests per le funzioni pure del builder artifact bilancini (v1: solo numeri veri)."""

from verticals.condges.build_bilancini_artifact import build_payload, compute_delta


def test_compute_delta_first_month_is_ytd():
    ytd = {"2026-01": 100.0, "2026-02": 250.0, "2026-04": 400.0}
    delta = compute_delta(ytd)
    assert delta["2026-01"] == 100.0
    assert delta["2026-02"] == 150.0
    # mese mancante (2026-03): delta di 2026-04 = 400 − 250 (dall'ultimo mese presente)
    assert delta["2026-04"] == 150.0


def test_build_payload_signs_and_presence():
    bilancino = [
        {"societa_id": "ORTI", "mese": "2026-05", "codice_conto": "47.91.01",
         "descrizione": "Ricavi alloggi", "tipo_conto": "CE", "sezione": "Ricavi", "saldo": -1000.0},
        {"societa_id": "ORTI", "mese": "2026-05", "codice_conto": "67.03.94",
         "descrizione": "Vestiario dipendenti", "tipo_conto": "CE", "sezione": "Costi", "saldo": 80.0},
    ]
    payload = build_payload(bilancino)
    orti = {c["codice"]: c for c in payload["societa"]["ORTI"]["conti"]}
    # saldo bilancino a segno grezzo nel payload (ricavi negativi): il raddrizzamento è del renderer
    assert orti["47.91.01"]["ytd"]["2026-05"] == -1000.0
    assert orti["47.91.01"]["delta"]["2026-05"] == -1000.0
    assert orti["67.03.94"]["ytd"]["2026-05"] == 80.0
    assert "budget" not in payload  # v1: solo numeri veri, nessuna stima
    assert payload["gruppi"] == {}  # nessun gruppi passato → default vuoto


def test_build_payload_includes_gruppi_descriptions():
    bilancino = [
        {"societa_id": "ORTI", "mese": "2026-05", "codice_conto": "47.91.01",
         "descrizione": "Ricavi alloggi", "tipo_conto": "CE", "sezione": "Ricavi", "saldo": -1000.0},
    ]
    gruppi = {"47.91": "Ricavi Hotel", "47": "RICAVI DELLE VENDITE E DELLE PRESTAZIONI"}
    payload = build_payload(bilancino, gruppi)
    assert payload["gruppi"] == gruppi
    # label fallback: un codice gruppo assente in DATA.gruppi resta il codice stesso
    # (comportamento lato JS: DATA.gruppi[codice] || codice) — qui verifichiamo solo
    # che il payload trasporti il dict così com'è, senza mutazioni.
    assert payload["gruppi"].get("99.99") is None


# ---------- push KV (flag --push) ----------

import pytest

from verticals.condges.build_bilancini_artifact import (
    PUSH_ENV_VARS,
    load_push_env,
    push_to_kv,
    payload_to_csv,
    render_html,
)

PUSH_ENV = {
    "CLOUDFLARE_API_TOKEN": "tok-test",
    "CLOUDFLARE_ACCOUNT_ID": "acc-123",
    "BILANCINI_KV_NAMESPACE_ID": "ns-456",
}


def _payload():
    return {
        "generated_at": "2026-07-15", "mesi": ["2026-05"],
        "societa": {"ORTI": {"conti": [{
            "codice": "47.91.01", "descrizione": "Ricavi alloggi", "tipo": "CE",
            "sezione": "Ricavi", "ytd": {"2026-05": -1000.0}, "delta": {"2026-05": -1000.0},
        }]}},
        "gruppi": {},
    }


def test_load_push_env_missing_raises(monkeypatch):
    for k in PUSH_ENV_VARS:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(RuntimeError, match="CLOUDFLARE_API_TOKEN"):
        load_push_env()


def test_load_push_env_complete(monkeypatch):
    for k, v in PUSH_ENV.items():
        monkeypatch.setenv(k, v)
    assert load_push_env() == PUSH_ENV


class _FakeResp:
    def __init__(self, ok=True, success=True, status_code=200, text=""):
        self.ok = ok
        self.status_code = status_code
        self.text = text
        self._success = success

    def json(self):
        return {"success": self._success}


def test_push_to_kv_bulk_payload(monkeypatch):
    import requests

    calls = {}

    def fake_put(url, json=None, headers=None, timeout=None):
        calls.update(url=url, body=json, headers=headers, timeout=timeout)
        return _FakeResp()

    monkeypatch.setattr(requests, "put", fake_put)
    payload = _payload()
    html = render_html(payload)
    push_to_kv(html, payload, PUSH_ENV)

    assert calls["url"] == (
        "https://api.cloudflare.com/client/v4/accounts/acc-123"
        "/storage/kv/namespaces/ns-456/bulk"
    )
    assert calls["headers"]["Authorization"] == "Bearer tok-test"
    by_key = {e["key"]: e["value"] for e in calls["body"]}
    assert set(by_key) == {"html", "data.json", "data.csv"}
    assert by_key["html"] == html
    assert '"generated_at": "2026-07-15"' in by_key["data.json"] or '"generated_at":"2026-07-15"' in by_key["data.json"]
    assert by_key["data.csv"] == payload_to_csv(payload)


def test_push_to_kv_api_error_raises(monkeypatch):
    import requests

    monkeypatch.setattr(
        requests, "put",
        lambda *a, **kw: _FakeResp(ok=False, success=False, status_code=403, text="forbidden"),
    )
    with pytest.raises(RuntimeError, match="403"):
        push_to_kv("<html>", _payload(), PUSH_ENV)


def test_render_html_no_fullscreen_button():
    # Bottone rimosso 2026-07-15: l'API Fullscreen JS è rotta su Arc (schermo
    # vuoto, non rilevabile). Il fullscreen è quello nativo del browser.
    html = render_html(_payload())
    assert "fs-btn" not in html
    assert "Schermo intero" not in html
    assert "csv-btn" in html  # il CSV resta
