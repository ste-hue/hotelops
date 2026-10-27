"""CE contract tests: synthetic ledger only, no live services."""

import pytest

from verticals.condges.ce_famiglie import build_ce_report, render_ce_report


def snapshot(month, code, amount, soc="ORTI"):
    return dict(societa_id=soc, mese=f"2026-{month:02}", codice_conto=code,
                descrizione=f"Conto {code}", tipo_conto="CE", saldo=amount)


def movement(month, code, amount, family, soc="ORTI", intercompany=False):
    return dict(societa_id=soc, anno=2026, mese=month, codice_conto=code,
                descrizione=f"Conto {code}", categoria_gestionale=family,
                is_intercompany=intercompany, saldo_mese=amount,
                importo_gestionale=-amount if family == "Ricavi" else amount)


def report(rows, raw, through=2):
    return build_ce_report(rows, raw, year=2026, through_month=through,
                           observed_at="2026-10-27T12:00:00+00:00")


def family(data, name, soc="ORTI"):
    return next(f for f in data["societa"][soc]["famiglie"] if f["famiglia"] == name)


def sample():
    rows = [movement(1, "47.01", -1000, "Ricavi"),
            movement(2, "47.01", -2000, "Ricavi"),
            movement(1, "67.01", 400, "Personale"),
            movement(2, "67.01", 500, "Personale")]
    raw = [snapshot(1, "47.01", -1000), snapshot(2, "47.01", -3000),
           snapshot(1, "67.01", 400), snapshot(2, "67.01", 900)]
    return rows, raw


def test_monthly_progressive_and_rates_share_reconciled_account_detail():
    data = report(*sample())
    costs = family(data, "Personale")
    assert costs["mensile"] == {"01": 400, "02": 500}
    assert costs["progressivo"] == {"01": 400, "02": 900}
    assert costs["incidenza_mensile"] == {"01": 40, "02": 25}
    assert costs["incidenza_progressivo"]["02"] == 30
    assert costs["conti"][0]["progressivo"] == costs["progressivo"]
    assert data["dimensione"] == "COMPETENZA"
    assert data["natura"] == "osservato"
    assert data["societa"]["ORTI"]["copertura"]["mesi_presenti"] == [1, 2]
    assert data["societa"]["INTUR"]["copertura"]["mesi_mancanti"] == [1, 2]


def test_gap_does_not_turn_two_month_change_into_one_month_cost():
    rows = [movement(1, "67.01", 40, "Personale"), movement(3, "67.01", 90, "Personale")]
    data = report(rows, [snapshot(1, "67.01", 40), snapshot(3, "67.01", 130)], through=3)
    costs = family(data, "Personale")
    assert costs["mensile"] == {"01": 40, "02": None, "03": None}
    assert costs["progressivo"] == {"01": 40, "02": None, "03": 130}


def test_zero_suppressed_account_reversal_and_negative_incidence_survive():
    rows, raw = sample()
    rows += [movement(1, "65.01", 100, "Affitti e canoni", intercompany=True),
             movement(2, "65.01", -100, "Affitti e canoni", intercompany=True)]
    raw += [snapshot(1, "65.01", 100)]
    rents = family(report(rows, raw), "Affitti e canoni")
    assert rents["mensile"]["02"] == -100
    assert rents["progressivo"]["02"] == 0
    assert rents["incidenza_mensile"]["02"] == -5
    assert rents["conti"][0]["is_intercompany"] is True


def test_unknown_accounts_remain_signed_and_visible():
    data = report([movement(1, "99", -20, None)], [snapshot(1, "99", -20)])
    unknown = family(data, "Non classificati")
    assert unknown["progressivo"]["01"] == -20
    assert unknown["incidenza_mensile"]["01"] is None
    assert data["societa"]["ORTI"]["conti_non_classificati"] == ["99"]


def test_no_cross_company_consolidation():
    rows, raw = sample()
    rows += [movement(1, "47.01", -50, "Ricavi", soc="INTUR", intercompany=True)]
    raw += [snapshot(1, "47.01", -50, soc="INTUR")]
    data = report(rows, raw)
    assert family(data, "Ricavi")["progressivo"]["01"] == 1000
    assert family(data, "Ricavi", "INTUR")["progressivo"]["01"] == 50


@pytest.mark.parametrize("which", ["raw", "view"])
def test_duplicate_accounts_fail_instead_of_deduplicating(which):
    rows, raw = sample()
    (raw if which == "raw" else rows).append((raw if which == "raw" else rows)[0].copy())
    with pytest.raises(ValueError, match="duplicat"):
        report(rows, raw)


def test_offsetting_errors_do_not_pass_net_reconciliation():
    rows, raw = sample()
    rows[2]["saldo_mese"] += 10
    rows[2]["importo_gestionale"] += 10
    rows[0]["saldo_mese"] -= 10
    rows[0]["importo_gestionale"] += 10
    with pytest.raises(ValueError, match="quadratura"):
        report(rows, raw)


def test_missing_snapshot_with_view_data_fails():
    rows, raw = sample()
    with pytest.raises(ValueError, match="snapshot"):
        report(rows, [r for r in raw if r["mese"] != "2026-02"])


@pytest.mark.parametrize("amount", [float("nan"), float("inf"), None])
def test_invalid_numbers_fail(amount):
    rows, raw = sample()
    rows[0]["saldo_mese"] = amount
    with pytest.raises(ValueError, match="importo"):
        report(rows, raw)


def test_snapshot_identity_does_not_depend_on_fetch_order_or_read_time():
    rows, raw = sample()
    first = report(rows, raw)
    second = build_ce_report(list(reversed(rows)), list(reversed(raw)), year=2026,
                             through_month=2, observed_at="2026-10-28T12:00:00+00:00")
    assert first["snapshot_id"] == second["snapshot_id"]


def test_html_contains_all_periods_detail_limits_and_escaped_labels():
    rows, raw = sample()
    rows[0]["descrizione"] = rows[1]["descrizione"] = "<script>bad()</script>"
    html = render_ce_report(report(rows, raw))
    assert "&lt;script&gt;bad()&lt;/script&gt;" in html
    assert "<script>bad()" not in html
    assert "COMPETENZA" in html and "67.01" in html
    assert "Non disponibile" in html and "IVA" in html
    assert 'data-ce-soc="ORTI"' in html and 'data-ce-soc="INTUR"' in html
    assert "2026-02" in html and "Incidenza" in html


def test_ce_mode_uses_only_reconciled_data_for_html_and_csv():
    from verticals.condges.build_bilancini_artifact import build_payload, render_html, payload_to_csv

    rows, raw = sample()
    payload = build_payload([{**r, "sezione": "Costi"} for r in raw])
    payload["ce_famiglie"] = report(rows, raw)
    html = render_html(payload)
    assert '<section class="panel active" id="panel-ce-famiglie">' in html
    assert 'id="panel-oggi"' not in html
    assert 'data-tab="navigatore"' not in html
    assert "data-ce-soc" in html
    assert "__CE_" not in html
    assert "compute_delta" not in html
    csv = payload_to_csv(payload)
    assert "famiglia" in csv and "Personale" in csv
    assert "incidenza_progressivo" in csv


def test_cli_builds_html_and_same_ce_snapshot_json_without_push(tmp_path, monkeypatch):
    import json
    import sys
    from verticals.condges import build_bilancini_artifact as builder
    from verticals.condges import ce_famiglie

    rows, raw = sample()
    monkeypatch.setattr(sys, "argv", ["build", "--out", str(tmp_path / "report.html"), "--ce-mese", "2"])
    monkeypatch.setattr(builder, "get_client", lambda: object())
    monkeypatch.setattr(builder, "fetch_bilancino", lambda _: [{**r, "sezione": "Costi"} for r in raw])
    monkeypatch.setattr(builder, "fetch_gruppi", lambda _: {})
    monkeypatch.setattr(ce_famiglie, "fetch_ce_rows", lambda *a, **kw: rows)
    monkeypatch.setattr(builder, "push_to_kv", lambda *a, **kw: pytest.fail("unexpected publication"))
    builder.main()
    data = json.loads((tmp_path / "report.ce.json").read_text())
    assert data["snapshot_id"] in (tmp_path / "report.html").read_text()
    assert family(data, "Personale")["progressivo"]["02"] == 900


def test_csv_preserves_missing_months_and_matches_account_values():
    import csv
    import io
    from verticals.condges.ce_famiglie import ce_to_csv

    rows = [movement(1, "67.01", 40, "Personale"), movement(3, "67.01", 90, "Personale")]
    data = report(rows, [snapshot(1, "67.01", 40), snapshot(3, "67.01", 130)], through=3)
    exported = list(csv.DictReader(io.StringIO(ce_to_csv(data))))
    assert exported[1]["mensile"] == exported[1]["progressivo"] == ""
    assert exported[2]["mensile"] == ""
    assert float(exported[2]["progressivo"]) == 130
    assert {r["snapshot_id"] for r in exported} == {data["snapshot_id"]}


def test_loader_is_parameterized_bounded_and_reads_only_canonical_view():
    from verticals.condges.ce_famiglie import fetch_ce_rows

    class Client:
        def query(self, sql, *, job_config, timeout):
            assert sql.lstrip().startswith("SELECT")
            assert "v_ce_mensile_bilancino" in sql and "@year" in sql and "@month" in sql
            assert job_config.maximum_bytes_billed == 100_000_000
            assert {p.name: p.value for p in job_config.query_parameters} == {"year": 2026, "month": 9}
            return self

        def result(self, *, timeout):
            return [{"societa_id": "ORTI"}]

    assert fetch_ce_rows(Client(), year=2026, through_month=9) == [{"societa_id": "ORTI"}]
