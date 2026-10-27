"""Read-only CE reporting from the canonical monthly view; no account mapping here.

The raw ledger is a reconciliation control, never a substitute data source.
Missing accounts in an observed snapshot mean zero under the canonical view's
zero-suppression rule. Missing snapshots never mean zero.
"""

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from html import escape
import json

SCHEMA = "hotelops.ce-famiglie.v1"
SOCIETA = ("ORTI", "INTUR")


def _amount(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("importo non valido") from exc
    if not result.is_finite():
        raise ValueError("importo non finito")
    return result


def _money(value):
    return float(round(value, 2)) if value is not None else None


def build_ce_report(rows, snapshots, *, year, through_month, observed_at):
    """Build family/account monthly and YTD values, checked against each snapshot.

    Caller supplies Jan..cutoff, not merely the final month. A skipped snapshot
    prevents displaying the following canonical LAG delta as a monthly amount.
    The cumulative delta can still be verified against the later YTD snapshot.
    """
    if not isinstance(year, int) or not 1900 <= year <= 9999:
        raise ValueError("anno non valido")
    if not isinstance(through_month, int) or not 1 <= through_month <= 12:
        raise ValueError("mese non valido")
    months = range(1, through_month + 1)
    raw, view, accounts = {}, {}, {}
    available = {soc: set() for soc in SOCIETA}
    for r in snapshots:
        soc = r["societa_id"]
        if soc not in SOCIETA or r["tipo_conto"] != "CE":
            continue
        if r["mese"][:4] != str(year):
            continue
        month = int(r["mese"][5:])
        if month not in months:
            continue
        key = (soc, month, r["codice_conto"])
        if key in raw:
            raise ValueError(f"conto duplicato nello snapshot: {key}")
        raw[key] = _amount(r["saldo"])
        available[soc].add(month)

    for r in rows:
        soc, month = r["societa_id"], r["mese"]
        if soc not in SOCIETA or r["anno"] != year or month not in months:
            continue
        key = (soc, month, r["codice_conto"])
        if key in view:
            raise ValueError(f"conto duplicato nella vista: {key}")
        if month not in available[soc]:
            raise ValueError(f"vista senza snapshot: {soc}/{month}")
        signed = _amount(r["saldo_mese"])
        amount = _amount(r["importo_gestionale"])
        family = r["categoria_gestionale"] or "Non classificati"
        if abs(amount - (-signed if family == "Ricavi" else signed)) > Decimal("0.01"):
            raise ValueError(f"segno gestionale incoerente: {key}")
        account_key = (soc, r["codice_conto"])
        info = {"codice": r["codice_conto"], "descrizione": r["descrizione"],
                "famiglia": family, "is_intercompany": r["is_intercompany"]}
        if account_key in accounts and accounts[account_key] != info:
            raise ValueError(f"metadati conto incoerenti: {account_key}")
        accounts[account_key] = info
        view[key] = (signed, amount)

    # Reconcile every account, including raw-only accounts and zero reversals.
    keys = set(accounts) | {(soc, code) for soc, _, code in raw}
    checks = {soc: 0 for soc in SOCIETA}
    for soc, code in sorted(keys):
        cumulative = Decimal(0)
        for month in months:
            cumulative += view.get((soc, month, code), (Decimal(0), Decimal(0)))[0]
            if month in available[soc]:
                expected = raw.get((soc, month, code), Decimal(0))
                if abs(cumulative - expected) > Decimal("0.01"):
                    raise ValueError(f"quadratura fallita: {soc}/{month}/{code}")
                checks[soc] += 1

    result = {"schema": SCHEMA, "anno": year, "mese_fino": through_month,
              "dimensione": "COMPETENZA", "natura": "osservato", "unita": "EUR",
              "observed_at": observed_at,
              "fonti": ["v_ce_mensile_bilancino", "f_bilancino (controllo)"],
              "societa": {}}
    for soc in SOCIETA:
        grouped = defaultdict(list)
        for (company, code), info in sorted(accounts.items()):
            if company != soc:
                continue
            account = dict(info, mensile={}, progressivo={})
            cumulative = Decimal(0)
            for month in months:
                delta = view.get((soc, month, code), (Decimal(0), Decimal(0)))[1]
                cumulative += delta
                tag = f"{month:02}"
                valid_month = month in available[soc] and (month == 1 or month - 1 in available[soc])
                account["mensile"][tag] = delta if valid_month else None
                account["progressivo"][tag] = cumulative if month in available[soc] else None
            grouped[info["famiglia"]].append(account)

        families = []
        for name, details in sorted(grouped.items(), key=lambda pair: (pair[0] != "Ricavi", pair[0])):
            family = {"famiglia": name, "conti": details}
            for kind in ("mensile", "progressivo"):
                family[kind] = {}
                for month in months:
                    tag = f"{month:02}"
                    values = [account[kind][tag] for account in details]
                    family[kind][tag] = sum(values, Decimal(0)) if all(v is not None for v in values) else None
            families.append(family)

        revenue = next((f for f in families if f["famiglia"] == "Ricavi"), None)
        for family in families:
            for item in [family, *family["conti"]]:
                for kind in ("mensile", "progressivo"):
                    rates = {}
                    for tag, value in item[kind].items():
                        base = revenue[kind][tag] if revenue else None
                        rates[tag] = (float(value / base * 100)
                                      if value is not None and base is not None and base > 0 else None)
                    item[f"incidenza_{kind}"] = rates
        # Conversion only after all financial arithmetic and ratios use decimals.
        for family in families:
            for item in [family, *family["conti"]]:
                for kind in ("mensile", "progressivo"):
                    item[kind] = {tag: _money(value) for tag, value in item[kind].items()}
        result["societa"][soc] = {
            "famiglie": families,
            "copertura": {"mesi_presenti": sorted(available[soc]),
                          "mesi_mancanti": sorted(set(months) - available[soc]),
                          "quadrature_conto_mese": checks[soc]},
            "conti_non_classificati": [a["codice"] for a in grouped["Non classificati"]],
        }

    # Identity names this exported content, not an immutable upstream revision.
    identity = {k: v for k, v in result.items() if k != "observed_at"}
    result["snapshot_id"] = sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False,
                                            allow_nan=False).encode()).hexdigest()
    return result


def fetch_ce_rows(client, *, year, through_month):
    """Read canonical data with bounded cost and typed parameters; never deploy."""
    from google.cloud import bigquery
    from core.config import PROJECT

    config = bigquery.QueryJobConfig(
        maximum_bytes_billed=100_000_000,
        query_parameters=[bigquery.ScalarQueryParameter("year", "INT64", year),
                          bigquery.ScalarQueryParameter("month", "INT64", through_month)],
    )
    sql = f"""SELECT societa_id, anno, mese, codice_conto, descrizione,
                     categoria_gestionale, is_intercompany, saldo_mese, importo_gestionale
              FROM `{PROJECT}.hotelops.v_ce_mensile_bilancino`
              WHERE anno = @year AND mese BETWEEN 1 AND @month
                AND societa_id IN ('ORTI', 'INTUR')"""
    job = client.query(sql, job_config=config, timeout=30)
    return [dict(row) for row in job.result(timeout=60)]


def render_ce_report(report):
    """HTML fragment for the existing Bilancini artifact; no JS financial logic."""
    def fmt(value, rate=False):
        if value is None:
            return "Non disponibile"
        text = f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
        return text + ("%" if rate else " €")

    def table(items, label, kind):
        html = '<div class="table-scroll"><table class="data"><thead><tr><th>Voce</th>'
        for month in range(1, report["mese_fino"] + 1):
            html += f'<th>{report["anno"]}-{month:02}<br>Importo · Incidenza</th>'
        html += "</tr></thead><tbody>"
        for item in items:
            html += f"<tr><td>{escape(label(item))}</td>"
            for tag, value in item[kind].items():
                html += f'<td>{fmt(value)}<br><small>{fmt(item[f"incidenza_{kind}"][tag], True)}</small></td>'
            html += "</tr>"
        return html + "</tbody></table></div>"

    html = '<h2>Conto economico per famiglie</h2><p>COMPETENZA · Consuntivo osservato · EUR</p>'
    html += ("<p>Ricavi e costi dal bilancino; incidenza sui ricavi classificati, "
             "non disponibile con ricavi nulli o negativi. Importi negativi conservati. "
             "I mensili sono differenze tra bilancini cumulativi: le rettifiche di competenza "
             "non registrate non sono ricostruite. La famiglia Investimenti contiene conti CE, non misura il CAPEX. "
             "Intercompany distinto nel dettaglio; società non consolidate. "
             "Attribuzione per struttura e verifica IVA dei ricavi non disponibili in questa fonte. "
             "I flussi IVA di cassa, gli impegni, il margine operativo e il confronto 65% "
             "richiedono verifiche e fonti ulteriori.</p>")
    for soc, data in report["societa"].items():
        hidden = "" if soc == "ORTI" else " hidden"
        coverage = data["copertura"]
        html += f'<div data-ce-soc="{escape(soc)}"{hidden}><h3>{escape(soc)}</h3>'
        html += (f'<p>Snapshot presenti: {len(coverage["mesi_presenti"])}/{report["mese_fino"]}. '
                 f'Quadrature conto/mese: {coverage["quadrature_conto_mese"]} (tolleranza 0,01 €).</p>')
        if coverage["mesi_mancanti"]:
            html += f'<p>Mesi mancanti: {escape(str(coverage["mesi_mancanti"]))}. Il delta successivo non è mensile.</p>'
        if data["conti_non_classificati"]:
            html += "<p>Conti non classificati: esposti a segno contabile, da verificare.</p>"
        if not data["famiglie"]:
            html += "<p>Non disponibile: nessun conto CE nel periodo.</p>"
        for kind, title in (("mensile", "Mensili"), ("progressivo", "Progressivi da gennaio")):
            html += f"<h3>{title}</h3>" + table(data["famiglie"], lambda f: f["famiglia"], kind)
        html += "<h3>Dettaglio Esolver</h3>"
        for family in data["famiglie"]:
            html += f'<details><summary>{escape(family["famiglia"])}</summary>'
            for kind, title in (("mensile", "Mensili"), ("progressivo", "Progressivi")):
                html += f"<h4>{title}</h4>" + table(
                    family["conti"], lambda a: a["codice"] + " — " + a["descrizione"]
                    + (" · Intercompany" if a["is_intercompany"] else ""), kind)
            html += "</details>"
        html += "</div>"
    html += (f'<p>Lettura: {escape(report["observed_at"])}. '
             f'Fonti: {escape(", ".join(report["fonti"]))}. '
             f'Contratto: {escape(report["schema"])}. Snapshot contenuto: {report["snapshot_id"]}.</p>')
    return html


def ce_to_csv(report):
    """Account-month export from the same snapshot as HTML, including nulls."""
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["societa", "mese", "famiglia", "codice_conto", "descrizione",
                     "is_intercompany", "mensile", "progressivo", "incidenza_mensile",
                     "incidenza_progressivo", "dimensione", "snapshot_id"])
    for soc, data in report["societa"].items():
        for family in data["famiglie"]:
            for account in family["conti"]:
                for tag in account["mensile"]:
                    writer.writerow([soc, f'{report["anno"]}-{tag}', family["famiglia"],
                                     account["codice"], account["descrizione"], account["is_intercompany"],
                                     account["mensile"][tag], account["progressivo"][tag],
                                     account["incidenza_mensile"][tag], account["incidenza_progressivo"][tag],
                                     "COMPETENZA", report["snapshot_id"]])
    return buffer.getvalue()


def render_ce_document(report, style):
    """CE mode of the Bilancini builder: shared styling, only verified CE data."""
    from base64 import b64encode

    csv_data = b64encode(ce_to_csv(report).encode()).decode()
    controls = ''.join(f'<button data-soc="{soc}" aria-pressed="{str(soc == "ORTI").lower()}">{soc}</button>'
                       for soc in SOCIETA)
    return ('<!doctype html><html lang="it"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>CE per famiglie · Bilancini</title><style>' + style + '</style></head>'
            '<body><main class="wrap"><header class="top"><h1>Bilancini · CE per famiglie</h1>'
            f'<p>Gennaio–{report["mese_fino"]:02}/{report["anno"]}</p>'
            f'<a download="ce-famiglie.csv" href="data:text/csv;base64,{csv_data}">Scarica CSV del CE</a>'
            '<div class="soc-pills" id="ce-soc-selector">' + controls + '</div></header>'
            '<section class="panel active" id="panel-ce-famiglie">' + render_ce_report(report)
            + '</section></main><script>' + '''
document.getElementById("ce-soc-selector").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-soc]");
  if (!button) return;
  document.querySelectorAll("[data-ce-soc]").forEach(el => {
    el.hidden = el.dataset.ceSoc !== button.dataset.soc;
  });
  document.querySelectorAll("button[data-soc]").forEach(el => {
    el.setAttribute("aria-pressed", String(el === button));
  });
});
''' + '</script></body></html>')
