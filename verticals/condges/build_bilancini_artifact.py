#!/usr/bin/env python3
"""Builder dell'artifact "Bilancini · Gruppo Panorama".

Legge f_bilancino da BQ (2026, ORTI+INTUR) + Budget_ORTI_2026.xlsx (via
parse_budget_orti_workbook) + Incidenza_costi_personale.xlsx e scrive un HTML
self-contained (dati embedded, nessuna richiesta esterna).

Uso:
    python -m verticals.condges.build_bilancini_artifact \
        [--budget-xlsx PATH] [--incidenza-xlsx PATH] [--out PATH]
"""

import argparse
import json
import logging
from datetime import date
from pathlib import Path

import openpyxl

from core.bq.client import get_client
from core.config import PROJECT

DEFAULT_BUDGET = Path("~/Desktop/WORK/artifacts/budget/Budget_ORTI_2026.xlsx").expanduser()
DEFAULT_INCIDENZA = Path("~/Desktop/WORK/artifacts/budget/Incidenza_costi_personale.xlsx").expanduser()
DEFAULT_OUT = Path("docs/reports/artifacts/bilancini.html")

ANNO = 2026


def fetch_bilancino(client) -> list[dict]:
    sql = f"""
        SELECT societa_id, mese, codice_conto, descrizione, tipo_conto, sezione, saldo
        FROM `{PROJECT}.hotelops.f_bilancino`
        WHERE mese LIKE '{ANNO}-%'
    """
    return [dict(r) for r in client.query(sql).result()]


def compute_delta(ytd: dict[str, float]) -> dict[str, float]:
    """delta[m] = ytd[m] − ytd[mese precedente presente]; primo mese = ytd."""
    delta = {}
    prev = 0.0
    for m in sorted(ytd):
        delta[m] = round(ytd[m] - prev, 2)
        prev = ytd[m]
    return delta


def budget_per_conto(rows: list[dict]) -> dict[str, dict[int, float]]:
    out: dict[str, dict[int, float]] = {}
    for r in rows:
        conto = out.setdefault(r["codice_conto"], {})
        conto[r["mese"]] = round(conto.get(r["mese"], 0.0) + r["importo"], 2)
    return out


def budget_per_categoria(rows: list[dict]) -> dict[str, dict[int, float]]:
    out: dict[str, dict[int, float]] = {}
    for r in rows:
        cat = out.setdefault(r["categoria_ce"], {})
        cat[r["mese"]] = round(cat.get(r["mese"], 0.0) + r["importo"], 2)
    return out


def categoria_per_conto(rows: list[dict]) -> dict[str, str]:
    """Codice conto → categoria_ce (dal budget), per raggruppare gli Scostamenti."""
    out: dict[str, str] = {}
    for r in rows:
        out.setdefault(r["codice_conto"], r["categoria_ce"])
    return out


def read_incidenza(path: Path) -> dict[str, list[float]]:
    """Foglio 'Costi Mensili': header riga 4, Division fino a '  TOTALE' (esclusa), '—'→0."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["Costi Mensili"]
    out: dict[str, list[float]] = {}
    for row in ws.iter_rows(min_row=5, values_only=True):
        div = str(row[0] or "").strip()
        if not div or div.upper() == "TOTALE":
            break
        vals = [float(v) if isinstance(v, (int, float)) else 0.0 for v in row[1:13]]
        out[div] = vals
    wb.close()
    return out


def build_payload(bilancino_rows: list[dict], budget_rows: list[dict], incidenza: dict) -> dict:
    mesi = sorted({r["mese"] for r in bilancino_rows})
    societa: dict[str, dict] = {}
    per_conto: dict[tuple, dict] = {}
    for r in bilancino_rows:
        key = (r["societa_id"], r["codice_conto"])
        c = per_conto.setdefault(key, {
            "codice": r["codice_conto"], "descrizione": r["descrizione"],
            "tipo": r["tipo_conto"], "sezione": r["sezione"], "ytd": {},
        })
        c["ytd"][r["mese"]] = round(float(r["saldo"]), 2)
    for (soc, _), c in per_conto.items():
        c["delta"] = compute_delta(c["ytd"])
        societa.setdefault(soc, {"conti": []})["conti"].append(c)
    for soc in societa:
        societa[soc]["conti"].sort(key=lambda c: c["codice"])
    return {
        "generated_at": date.today().isoformat(),
        "mesi": mesi,
        "societa": societa,
        "budget": {
            "per_conto": budget_per_conto(budget_rows),
            "per_categoria": budget_per_categoria(budget_rows),
            "categoria_per_conto": categoria_per_conto(budget_rows),
            "personale_reparti": incidenza,
        },
    }


def render_html(payload: dict) -> str:
    data_json = json.dumps(payload, ensure_ascii=False)
    return HTML_TEMPLATE.replace("__DATA__", data_json)


HTML_TEMPLATE = """<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bilancini · Gruppo Panorama</title>
<style>
  :root {
    --page: #f9f9f7;
    --surface: #fcfcfb;
    --ink: #0b0b0b;
    --ink-2: #52514e;
    --ink-muted: #898781;
    --grid: #e1e0d9;
    --axis: #c3c2b7;
    --border: rgba(11,11,11,0.10);
    --overlay: rgba(11,11,11,0.04);
    --good: #0ca30c;
    --warning: #fab219;
    --critical: #d03b3b;
    --cat-ricavi: #2a78d6;
    --cat-fissi: #1baf7a;
    --cat-personale: #eda100;
    --cat-finanziari: #4a3aa7;
    --cat-fuori: #898781;
    --soc-orti: #2a78d6;
    --soc-intur: #1baf7a;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --page: #0d0d0d;
      --surface: #1a1a19;
      --ink: #ffffff;
      --ink-2: #c3c2b7;
      --ink-muted: #898781;
      --grid: #2c2c2a;
      --axis: #383835;
      --border: rgba(255,255,255,0.10);
      --overlay: rgba(255,255,255,0.06);
      --good: #0ca30c;
      --warning: #fab219;
      --critical: #e66767;
      --cat-ricavi: #3987e5;
      --cat-fissi: #199e70;
      --cat-personale: #c98500;
      --cat-finanziari: #9085e9;
      --cat-fuori: #898781;
      --soc-orti: #3987e5;
      --soc-intur: #199e70;
    }
  }
  :root[data-theme="dark"] {
    --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7; --ink-muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10); --overlay: rgba(255,255,255,0.06);
    --good: #0ca30c; --warning: #fab219; --critical: #e66767;
    --cat-ricavi: #3987e5; --cat-fissi: #199e70; --cat-personale: #c98500; --cat-finanziari: #9085e9; --cat-fuori: #898781;
    --soc-orti: #3987e5; --soc-intur: #199e70;
  }
  :root[data-theme="light"] {
    --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --ink-muted: #898781;
    --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10); --overlay: rgba(11,11,11,0.04);
    --good: #0ca30c; --warning: #fab219; --critical: #d03b3b;
    --cat-ricavi: #2a78d6; --cat-fissi: #1baf7a; --cat-personale: #eda100; --cat-finanziari: #4a3aa7; --cat-fuori: #898781;
    --soc-orti: #2a78d6; --soc-intur: #1baf7a;
  }
  * { box-sizing: border-box; }
  @media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }
  html, body { margin: 0; padding: 0; }
  body {
    background: var(--page);
    color: var(--ink);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    font-size: 14px;
    line-height: 1.5;
  }
  h1, h2, h3 { text-wrap: balance; margin: 0; }
  a { color: var(--cat-ricavi); }
  :focus-visible { outline: 2px solid var(--cat-ricavi); outline-offset: 2px; }
  .wrap { max-width: 1180px; margin: 0 auto; padding: 20px 24px 64px; }
  header.top { padding-bottom: 14px; border-bottom: 1px solid var(--border); margin-bottom: 20px; }
  header.top h1 { font-size: 22px; font-weight: 700; letter-spacing: -0.01em; }
  .freshness { color: var(--ink-muted); font-size: 12.5px; margin-top: 4px; }
  nav.tabnav { display: flex; gap: 4px; margin-top: 16px; flex-wrap: wrap; }
  nav.tabnav button {
    appearance: none; border: 1px solid transparent; background: transparent; color: var(--ink-2);
    font: inherit; font-weight: 600; font-size: 13px; padding: 8px 14px; border-radius: 7px 7px 0 0;
    cursor: pointer; border-bottom: 2px solid transparent;
  }
  nav.tabnav button:hover { background: var(--overlay); }
  nav.tabnav button[aria-selected="true"] { color: var(--ink); border-bottom-color: var(--cat-ricavi); }
  section.panel { display: none; }
  section.panel.active { display: block; }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 18px 20px; }
  .card + .card { margin-top: 16px; }
  h2.section-title { font-size: 16px; font-weight: 700; margin-bottom: 4px; }
  p.section-sub { color: var(--ink-muted); font-size: 12.5px; margin: 0 0 16px; }
  .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 14px; }
  .kpi-tile { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px 18px; }
  .kpi-label { font-size: 11.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: var(--ink-muted); }
  .kpi-value { font-size: 28px; font-weight: 700; margin-top: 6px; font-variant-numeric: tabular-nums; }
  .kpi-budget { font-size: 12px; color: var(--ink-muted); margin-top: 2px; font-variant-numeric: tabular-nums; }
  .kpi-bar { position: relative; height: 8px; background: var(--grid); border-radius: 4px; margin-top: 12px; overflow: visible; }
  .kpi-bar-fill { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 4px; }
  .kpi-bar-tick { position: absolute; top: -3px; bottom: -3px; width: 2px; background: var(--ink); opacity: 0.55; }
  .kpi-bar-zero { position: absolute; top: -3px; bottom: -3px; width: 1px; background: var(--axis); }
  .pill { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 700; padding: 3px 9px; border-radius: 100px; margin-top: 10px; }
  .pill.good { color: var(--good); background: color-mix(in srgb, var(--good) 14%, transparent); }
  .pill.critical { color: var(--critical); background: color-mix(in srgb, var(--critical) 14%, transparent); }
  .legend { display: flex; flex-wrap: wrap; gap: 14px; margin: 10px 0 4px; font-size: 12px; color: var(--ink-2); }
  .legend-item { display: flex; align-items: center; gap: 6px; }
  .legend-swatch { width: 11px; height: 11px; border-radius: 3px; flex: none; }
  .legend-swatch.fuori { background-image: repeating-linear-gradient(45deg, var(--cat-fuori) 0 2px, transparent 2px 5px); }
  .chart-row { display: grid; grid-template-columns: 1fr; gap: 18px; }
  @media (min-width: 900px) { .chart-row { grid-template-columns: 1fr 1fr; } }
  svg.chart { width: 100%; height: auto; display: block; overflow: visible; }
  svg.chart text { fill: var(--ink-2); font-size: 10.5px; font-family: inherit; }
  svg.chart .axis-line { stroke: var(--axis); stroke-width: 1; }
  svg.chart .gridline { stroke: var(--grid); stroke-width: 1; }
  details.data-fallback { margin-top: 10px; }
  details.data-fallback summary { cursor: pointer; font-size: 12px; color: var(--ink-muted); }
  .table-scroll { overflow-x: auto; }
  table.data { border-collapse: collapse; width: 100%; min-width: 640px; font-size: 13px; }
  table.data th, table.data td { padding: 7px 10px; text-align: right; border-bottom: 1px solid var(--border); white-space: nowrap; }
  table.data th:first-child, table.data td:first-child { text-align: left; white-space: normal; }
  table.data th { color: var(--ink-muted); font-weight: 600; font-size: 11.5px; text-transform: uppercase; letter-spacing: 0.03em; position: sticky; top: 0; background: var(--surface); }
  table.data td { font-variant-numeric: tabular-nums; }
  table.data tbody tr:hover { background: var(--overlay); }
  .num.good { color: var(--good); }
  .num.critical { color: var(--critical); }
  .badge-fb { display: inline-block; font-size: 10.5px; font-weight: 700; color: var(--ink-muted); border: 1px solid var(--border); border-radius: 4px; padding: 1px 5px; margin-left: 6px; vertical-align: middle; }
  details.group { border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; overflow: hidden; }
  details.group summary { list-style: none; cursor: pointer; padding: 10px 14px; display: flex; align-items: center; gap: 10px; background: var(--surface); font-weight: 700; font-size: 13px; }
  details.group summary::-webkit-details-marker { display: none; }
  details.group summary::before { content: "▸"; color: var(--ink-muted); transition: none; }
  details.group[open] summary::before { content: "▾"; }
  details.group summary .cat-dot { width: 10px; height: 10px; border-radius: 3px; flex: none; }
  details.group summary .sum-line { margin-left: auto; display: flex; gap: 16px; font-weight: 400; color: var(--ink-2); font-size: 12px; font-variant-numeric: tabular-nums; }
  .reparto-table td.heat { text-align: right; font-variant-numeric: tabular-nums; }
  .navigator-controls { display: flex; flex-wrap: wrap; gap: 16px; align-items: center; margin-bottom: 14px; }
  .soc-pills { display: flex; gap: 6px; }
  .soc-pills button { appearance: none; border: 1px solid var(--border); background: var(--surface); color: var(--ink-2); font: inherit; font-weight: 700; font-size: 12.5px; padding: 6px 14px; border-radius: 100px; cursor: pointer; }
  .soc-pills button[aria-pressed="true"][data-soc="ORTI"] { background: var(--soc-orti); border-color: var(--soc-orti); color: #fff; }
  .soc-pills button[aria-pressed="true"][data-soc="INTUR"] { background: var(--soc-intur); border-color: var(--soc-intur); color: #fff; }
  select { font: inherit; padding: 6px 10px; border-radius: 7px; border: 1px solid var(--border); background: var(--surface); color: var(--ink); }
  .sign-note { color: var(--ink-muted); font-size: 11.5px; margin-bottom: 10px; }
  .tree-root { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
  .tree-node > summary { list-style: none; cursor: pointer; display: flex; align-items: center; gap: 8px; padding: 7px 12px; border-bottom: 1px solid var(--border); background: var(--surface); }
  .tree-node > summary::-webkit-details-marker { display: none; }
  .tree-node > summary::before { content: "▸"; color: var(--ink-muted); font-size: 11px; width: 10px; }
  .tree-node[open] > summary::before { content: "▾"; }
  .tree-node .node-code { font-variant-numeric: tabular-nums; color: var(--ink-muted); font-size: 11.5px; width: 84px; flex: none; }
  .tree-node .node-label { flex: 1; font-size: 12.5px; }
  .tree-node .node-vals { display: flex; gap: 18px; font-size: 12.5px; font-variant-numeric: tabular-nums; }
  .tree-node .node-vals .lbl { color: var(--ink-muted); font-size: 10.5px; display: block; text-transform: uppercase; letter-spacing: .03em; }
  .tree-children { padding-left: 20px; border-bottom: 1px solid var(--border); }
  .tree-children:last-child { border-bottom: none; }
  .tree-node:last-child > summary { border-bottom: none; }
  .leaf-row { display: flex; align-items: center; gap: 8px; padding: 6px 12px 6px 30px; border-bottom: 1px solid var(--border); }
  .leaf-row:last-child { border-bottom: none; }
  .leaf-row .node-desc { flex: 1; font-size: 12px; color: var(--ink-2); }
  footer.note { margin-top: 22px; color: var(--ink-muted); font-size: 11.5px; }
</style>
</head>
<body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
  <defs>
    <pattern id="hatch-fb" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)">
      <rect width="6" height="6" fill="transparent"></rect>
      <line x1="0" y1="0" x2="0" y2="6" stroke="var(--cat-fuori)" stroke-width="2.4"></line>
    </pattern>
  </defs>
</svg>
<div class="wrap">
  <header class="top">
    <h1>Bilancini · Gruppo Panorama</h1>
    <div class="freshness" id="freshness"></div>
    <nav class="tabnav" id="tabnav">
      <button data-tab="oggi" aria-selected="true">A oggi</button>
      <button data-tab="progressione" aria-selected="false">Progressione</button>
      <button data-tab="scostamenti" aria-selected="false">Scostamenti</button>
      <button data-tab="navigatore" aria-selected="false">Navigatore</button>
    </nav>
  </header>

  <section class="panel active" id="panel-oggi">
    <h2 class="section-title">A oggi — ORTI vs budget</h2>
    <p class="section-sub">Come sta andando il bilancio ORTI rispetto al budget, dall'inizio dell'anno al mese chiuso più recente.</p>
    <div class="kpi-grid" id="kpi-grid"></div>
  </section>

  <section class="panel" id="panel-progressione">
    <h2 class="section-title">Progressione — ORTI, mese per mese</h2>
    <p class="section-sub">Come ci siamo arrivati: il peso di ogni mese sul consuntivo YTD, per categoria, confrontato col budget.</p>
    <div class="card">
      <div class="legend" id="cat-legend"></div>
      <div class="chart-row">
        <div>
          <h3 style="font-size:12.5px;color:var(--ink-muted);font-weight:700;text-transform:uppercase;letter-spacing:.03em;margin-bottom:8px;">Delta mensile per categoria</h3>
          <svg class="chart" id="chart-monthly" viewBox="0 0 640 260" preserveAspectRatio="xMinYMin meet"></svg>
          <details class="data-fallback"><summary>Vedi tabella dati</summary><div class="table-scroll" id="table-monthly"></div></details>
        </div>
        <div>
          <h3 style="font-size:12.5px;color:var(--ink-muted);font-weight:700;text-transform:uppercase;letter-spacing:.03em;margin-bottom:8px;">Margine cumulato YTD — actual vs budget</h3>
          <svg class="chart" id="chart-cumulata" viewBox="0 0 640 260" preserveAspectRatio="xMinYMin meet"></svg>
          <details class="data-fallback"><summary>Vedi tabella dati</summary><div class="table-scroll" id="table-cumulata"></div></details>
        </div>
      </div>
    </div>
  </section>

  <section class="panel" id="panel-scostamenti">
    <h2 class="section-title">Scostamenti — ORTI, categoria → conto</h2>
    <p class="section-sub">Dove il consuntivo si discosta dal budget, ordinato per scostamento assoluto. I conti senza budget non sono mai nascosti.</p>
    <div id="scostamenti-groups"></div>
    <div class="card" style="margin-top:16px;">
      <h3 style="font-size:13px;font-weight:700;margin-bottom:4px;">Personale per reparto (budget mensile)</h3>
      <p class="section-sub" style="margin-bottom:12px;">Distribuzione del costo del personale a budget, per reparto e mese (Incidenza costi personale).</p>
      <div class="table-scroll" id="reparto-table"></div>
    </div>
  </section>

  <section class="panel" id="panel-navigatore">
    <h2 class="section-title">Navigatore — piano dei conti</h2>
    <p class="section-sub">ORTI e INTUR, albero dai prefissi di conto. Saldo YTD e delta del mese selezionato, i gruppi sommano le foglie.</p>
    <div class="navigator-controls">
      <div class="soc-pills" id="soc-pills">
        <button data-soc="ORTI" aria-pressed="true">ORTI</button>
        <button data-soc="INTUR" aria-pressed="false">INTUR</button>
      </div>
      <label for="mese-select" style="font-size:12.5px;color:var(--ink-muted);">Mese</label>
      <select id="mese-select"></select>
    </div>
    <p class="sign-note">Segni: ricavi CE mostrati positivi (saldo invertito); costi CE e voci patrimoniali mostrati come da saldo contabile.</p>
    <div class="table-scroll">
      <div class="tree-root" id="tree-root"></div>
    </div>
  </section>

  <footer class="note">Bilancini · Gruppo Panorama — dati BigQuery (f_bilancino) + budget ORTI. Artifact rigenerabile, non è una fonte.</footer>
</div>

<script>
const DATA = __DATA__;
const MONTH_LABELS = ["Gen","Feb","Mar","Apr","Mag","Giu","Lug","Ago","Set","Ott","Nov","Dic"];
const CATS = ["Ricavi","Costi Produttivi","Costo del Personale","Oneri Finanziari"];
const CAT_COLOR_VAR = {
  "Ricavi": "--cat-ricavi",
  "Costi Produttivi": "--cat-fissi",
  "Costo del Personale": "--cat-personale",
  "Oneri Finanziari": "--cat-finanziari",
  "Fuori budget": "--cat-fuori",
};

function fmt(n) { return new Intl.NumberFormat("it-IT", { maximumFractionDigits: 0 }).format(Math.round(n || 0)); }
function fmtEuro(n) { return "€ " + fmt(n); }
function fmtPct(n) { return (n >= 0 ? "+" : "") + n.toFixed(1) + "%"; }
function monthNum(mese) { return parseInt(mese.slice(5, 7), 10); }
function monthLabel(mese) { return MONTH_LABELS[monthNum(mese) - 1] + " " + mese.slice(0, 4); }

// -- sign convention: ricavi CE mostrati positivi (saldo bilancino è negativo per i ricavi) --
function ceConti(soc) {
  const list = (DATA.societa[soc] && DATA.societa[soc].conti) || [];
  return list.filter(c => c.tipo === "CE");
}
function dispYtd(c, mese) { const v = c.ytd[mese] || 0; return c.sezione === "Ricavi" ? -v : v; }
function dispDelta(c, mese) { const v = c.delta[mese] || 0; return c.sezione === "Ricavi" ? -v : v; }

function budgetPerContoAt(codice, m) {
  const b = DATA.budget.per_conto[codice];
  return (b && b[String(m)]) || 0;
}
function budgetPerContoYtd(codice, uptoM) {
  let tot = 0;
  for (let m = 1; m <= uptoM; m++) tot += budgetPerContoAt(codice, m);
  return tot;
}
function budgetPerCategoriaAt(cat, m) {
  const b = DATA.budget.per_categoria[cat];
  return (b && b[String(m)]) || 0;
}
function budgetPerCategoriaYtd(cat, uptoM) {
  let tot = 0;
  for (let m = 1; m <= uptoM; m++) tot += budgetPerCategoriaAt(cat, m);
  return tot;
}
function categoriaOf(codice, sezione) {
  const cat = DATA.budget.categoria_per_conto[codice];
  if (cat) return cat;
  return sezione === "Ricavi" ? "Ricavi" : "Fuori budget";
}

const MESI = DATA.mesi;
const LAST_MESE = MESI[MESI.length - 1];
const LAST_M = monthNum(LAST_MESE);

// ---------- Tabs ----------
document.getElementById("tabnav").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-tab]");
  if (!btn) return;
  document.querySelectorAll("#tabnav button").forEach(b => b.setAttribute("aria-selected", String(b === btn)));
  document.querySelectorAll("section.panel").forEach(p => p.classList.toggle("active", p.id === "panel-" + btn.dataset.tab));
});

// ---------- Freshness ----------
document.getElementById("freshness").textContent = `dati al ${LAST_MESE} · generato il ${DATA.generated_at}`;

// ---------- A oggi (KPI) ----------
function kpiTotals() {
  const conti = ceConti("ORTI");
  let ricaviActual = 0, costiActual = 0;
  for (const c of conti) {
    if (c.sezione === "Ricavi") ricaviActual += dispYtd(c, LAST_MESE);
    else costiActual += dispYtd(c, LAST_MESE);
  }
  const ricaviBudget = budgetPerCategoriaYtd("Ricavi", LAST_M);
  const costiBudget = ["Costi Produttivi", "Costo del Personale", "Oneri Finanziari"]
    .reduce((s, cat) => s + budgetPerCategoriaYtd(cat, LAST_M), 0);
  return {
    ricavi: { actual: ricaviActual, budget: ricaviBudget },
    costi: { actual: costiActual, budget: costiBudget },
    margine: { actual: ricaviActual - costiActual, budget: ricaviBudget - costiBudget },
  };
}

function kpiBarHtml(actual, budget) {
  // Ricavi/Costi sono per costruzione >=0 (segno già raddrizzato): barra semplice
  // ancorata a sinistra. Margine può essere negativo (perdita): barra divergente
  // centrata sullo zero, altrimenti max(actual,budget,1) esploderebbe con valori
  // entrambi negativi (percentuali di larghezza a 6 cifre).
  const maxAbs = Math.max(Math.abs(actual), Math.abs(budget), 1);
  if (actual >= 0 && budget >= 0) {
    const fillPct = Math.min(100, (actual / maxAbs) * 100);
    const tickPct = Math.min(100, (budget / maxAbs) * 100);
    return `<div class="kpi-bar">
        <div class="kpi-bar-fill" style="left:0;width:${fillPct}%;background:var(--cat-ricavi);"></div>
        <div class="kpi-bar-tick" style="left:${tickPct}%;" title="budget"></div>
      </div>`;
  }
  const half = 50;
  const actualPct = (Math.abs(actual) / maxAbs) * half;
  const budgetPct = (Math.abs(budget) / maxAbs) * half;
  const actualLeft = actual >= 0 ? half : half - actualPct;
  const budgetLeft = budget >= 0 ? half + budgetPct : half - budgetPct;
  return `<div class="kpi-bar">
      <div class="kpi-bar-zero" style="left:${half}%;"></div>
      <div class="kpi-bar-fill" style="left:${actualLeft}%;width:${actualPct}%;background:var(--cat-ricavi);"></div>
      <div class="kpi-bar-tick" style="left:${budgetLeft}%;" title="budget"></div>
    </div>`;
}

function kpiTile(label, actual, budget, kind) {
  const scost = actual - budget;
  const pct = budget !== 0 ? (scost / Math.abs(budget)) * 100 : (actual !== 0 ? 100 : 0);
  let favorable;
  if (kind === "ricavi") favorable = scost >= 0;
  else if (kind === "costi") favorable = scost <= 0;
  else favorable = scost >= 0;
  const dir = scost >= 0 ? "sopra" : "sotto";
  const cls = favorable ? "good" : "critical";
  const check = favorable ? " ✓" : "";
  // Margine può essere negativo (perdita reale, non un artefatto di segno bilancino):
  // lo si etichetta esplicitamente invece di lasciare solo il "-" a parlare.
  const tag = kind === "margine" && actual < 0 ? '<span class="badge-fb">perdita</span>' : "";
  return `
    <div class="kpi-tile">
      <div class="kpi-label">${label}</div>
      <div class="kpi-value">${fmtEuro(actual)} ${tag}</div>
      <div class="kpi-budget">budget YTD: ${fmtEuro(budget)}</div>
      ${kpiBarHtml(actual, budget)}
      <div class="pill ${cls}">${fmtPct(pct)} ${dir} budget${check}</div>
    </div>`;
}

function renderKpi() {
  const t = kpiTotals();
  document.getElementById("kpi-grid").innerHTML =
    kpiTile("Ricavi YTD", t.ricavi.actual, t.ricavi.budget, "ricavi") +
    kpiTile("Costi YTD", t.costi.actual, t.costi.budget, "costi") +
    kpiTile("Margine YTD", t.margine.actual, t.margine.budget, "margine");
}

// ---------- Progressione ----------
function monthlyByCategoria() {
  const conti = ceConti("ORTI");
  const byCat = {};
  for (const m of MESI) byCat[m] = {};
  for (const c of conti) {
    const cat = categoriaOf(c.codice, c.sezione);
    for (const m of MESI) {
      byCat[m][cat] = (byCat[m][cat] || 0) + dispDelta(c, m);
    }
  }
  return byCat;
}

function svgEl(tag, attrs) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}

function renderMonthlyChart() {
  const byCat = monthlyByCategoria();
  const allCats = CATS.concat(["Fuori budget"]);
  const svg = document.getElementById("chart-monthly");
  svg.innerHTML = "";
  const W = 640, H = 260, padL = 54, padR = 10, padT = 10, padB = 26;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const n = MESI.length;
  const slot = plotW / n;
  const barW = slot * 0.56;

  let maxVal = 1;
  const budgetTotals = [];
  MESI.forEach((m, i) => {
    let tot = 0;
    for (const cat of allCats) tot += Math.max(0, byCat[m][cat] || 0);
    const bt = ["Ricavi", "Costi Produttivi", "Costo del Personale", "Oneri Finanziari"]
      .reduce((s, cat) => s + budgetPerCategoriaAt(cat, monthNum(m)), 0);
    budgetTotals.push(bt);
    maxVal = Math.max(maxVal, tot, bt);
  });
  const scale = (v) => (v / maxVal) * plotH;

  // gridlines
  for (let g = 0; g <= 4; g++) {
    const y = padT + plotH - (g / 4) * plotH;
    svg.appendChild(svgEl("line", { class: "gridline", x1: padL, x2: W - padR, y1: y, y2: y }));
    const label = svgEl("text", { x: padL - 8, y: y + 3, "text-anchor": "end" });
    label.textContent = fmt((g / 4) * maxVal);
    svg.appendChild(label);
  }
  svg.appendChild(svgEl("line", { class: "axis-line", x1: padL, x2: padL, y1: padT, y2: padT + plotH }));

  const rows = [["Mese"].concat(allCats, ["Budget tot."])];
  MESI.forEach((m, i) => {
    const x0 = padL + i * slot + (slot - barW) / 2;
    let yCursor = padT + plotH;
    const rowVals = [monthLabel(m)];
    for (const cat of allCats) {
      const v = Math.max(0, byCat[m][cat] || 0);
      rowVals.push(fmt(byCat[m][cat] || 0));
      const h = scale(v);
      if (h > 0.2) {
        const fill = cat === "Fuori budget" ? "url(#hatch-fb)" : `var(${CAT_COLOR_VAR[cat]})`;
        svg.appendChild(svgEl("rect", {
          x: x0, y: yCursor - h, width: barW, height: Math.max(0, h - 1.5),
          fill: fill, rx: 1.5,
        }));
      }
      yCursor -= h;
    }
    rowVals.push(fmt(budgetTotals[i]));
    rows.push(rowVals);
    // budget tick
    const by = padT + plotH - scale(budgetTotals[i]);
    svg.appendChild(svgEl("line", {
      x1: x0 - 3, x2: x0 + barW + 3, y1: by, y2: by,
      stroke: "var(--ink)", "stroke-width": 2, opacity: 0.55,
    }));
    const lab = svgEl("text", { x: x0 + barW / 2, y: H - 6, "text-anchor": "middle" });
    lab.textContent = MONTH_LABELS[monthNum(m) - 1];
    svg.appendChild(lab);
  });

  document.getElementById("table-monthly").innerHTML = tableFromRows(rows);
}

function renderCumulataChart() {
  const conti = ceConti("ORTI");
  const svg = document.getElementById("chart-cumulata");
  svg.innerHTML = "";
  const W = 640, H = 260, padL = 54, padR = 14, padT = 10, padB = 26;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const n = MESI.length;

  const actualCum = [];
  const budgetCum = [];
  let rA = 0, cA = 0, rB = 0, cB = 0;
  const rows = [["Mese", "Margine actual", "Margine budget"]];
  MESI.forEach((m) => {
    for (const c of conti) {
      if (c.sezione === "Ricavi") rA += dispDelta(c, m); else cA += dispDelta(c, m);
    }
    const mnum = monthNum(m);
    rB += budgetPerCategoriaAt("Ricavi", mnum);
    cB += ["Costi Produttivi", "Costo del Personale", "Oneri Finanziari"].reduce((s, cat) => s + budgetPerCategoriaAt(cat, mnum), 0);
    actualCum.push(rA - cA);
    budgetCum.push(rB - cB);
    rows.push([monthLabel(m), fmt(rA - cA), fmt(rB - cB)]);
  });

  const allVals = actualCum.concat(budgetCum);
  const minV = Math.min(0, ...allVals);
  const maxV = Math.max(1, ...allVals);
  const range = maxV - minV || 1;
  const x = (i) => padL + (i / Math.max(1, n - 1)) * plotW;
  const y = (v) => padT + plotH - ((v - minV) / range) * plotH;

  for (let g = 0; g <= 4; g++) {
    const v = minV + (g / 4) * range;
    const yy = y(v);
    svg.appendChild(svgEl("line", { class: "gridline", x1: padL, x2: W - padR, y1: yy, y2: yy }));
    const label = svgEl("text", { x: padL - 8, y: yy + 3, "text-anchor": "end" });
    label.textContent = fmt(v);
    svg.appendChild(label);
  }
  svg.appendChild(svgEl("line", { class: "axis-line", x1: padL, x2: padL, y1: padT, y2: padT + plotH }));

  function polyline(vals, stroke, dash) {
    const pts = vals.map((v, i) => `${x(i)},${y(v)}`).join(" ");
    const attrs = { points: pts, fill: "none", stroke: stroke, "stroke-width": 2.4, "stroke-linejoin": "round", "stroke-linecap": "round" };
    if (dash) attrs["stroke-dasharray"] = "5,4";
    svg.appendChild(svgEl("polyline", attrs));
    vals.forEach((v, i) => {
      svg.appendChild(svgEl("circle", { cx: x(i), cy: y(v), r: 3, fill: stroke }));
    });
  }
  polyline(budgetCum, "var(--ink-muted)", true);
  polyline(actualCum, "var(--cat-ricavi)", false);

  MESI.forEach((m, i) => {
    const lab = svgEl("text", { x: x(i), y: H - 6, "text-anchor": "middle" });
    lab.textContent = MONTH_LABELS[monthNum(m) - 1];
    svg.appendChild(lab);
  });

  document.getElementById("table-cumulata").innerHTML = tableFromRows(rows);
}

function tableFromRows(rows) {
  const [head, ...body] = rows;
  let html = '<table class="data"><thead><tr>' + head.map(h => `<th>${h}</th>`).join("") + "</tr></thead><tbody>";
  for (const r of body) html += "<tr>" + r.map(c => `<td>${c}</td>`).join("") + "</tr>";
  html += "</tbody></table>";
  return html;
}

function renderCatLegend() {
  const allCats = CATS.concat(["Fuori budget"]);
  document.getElementById("cat-legend").innerHTML = allCats.map(cat => {
    const swatchCls = cat === "Fuori budget" ? "legend-swatch fuori" : "legend-swatch";
    const style = cat === "Fuori budget" ? "" : `style="background:var(${CAT_COLOR_VAR[cat]})"`;
    return `<span class="legend-item"><span class="${swatchCls}" ${style}></span>${cat}</span>`;
  }).join("");
}

// ---------- Scostamenti ----------
function scostamentiRows() {
  const conti = ceConti("ORTI");
  const rows = conti.map(c => {
    const cat = categoriaOf(c.codice, c.sezione);
    const ytd = dispYtd(c, LAST_MESE);
    const delta = dispDelta(c, LAST_MESE);
    const hasBudget = !!DATA.budget.per_conto[c.codice];
    const budgetYtd = budgetPerContoYtd(c.codice, LAST_M);
    const scost = ytd - budgetYtd;
    const favorable = c.sezione === "Ricavi" ? scost >= 0 : scost <= 0;
    return { c, cat, ytd, delta, hasBudget, budgetYtd, scost, favorable };
  });
  const byCat = {};
  for (const r of rows) (byCat[r.cat] = byCat[r.cat] || []).push(r);
  for (const cat in byCat) byCat[cat].sort((a, b) => Math.abs(b.scost) - Math.abs(a.scost));
  return byCat;
}

function renderScostamenti() {
  const byCat = scostamentiRows();
  const order = CATS.concat(["Fuori budget"]).filter(cat => byCat[cat] && byCat[cat].length);
  let html = "";
  for (const cat of order) {
    const rows = byCat[cat];
    const sumYtd = rows.reduce((s, r) => s + r.ytd, 0);
    const sumBudget = rows.reduce((s, r) => s + r.budgetYtd, 0);
    const sumScost = sumYtd - sumBudget;
    const colorVar = CAT_COLOR_VAR[cat];
    const dotStyle = cat === "Fuori budget" ? "background-image:repeating-linear-gradient(45deg, var(--cat-fuori) 0 2px, transparent 2px 5px);" : `background:var(${colorVar});`;
    const pctHtml = sumBudget !== 0
      ? `<span class="${sumScost === 0 ? '' : (sumScost > 0 === (cat === 'Ricavi') ? 'num good' : 'num critical')}">${fmtPct((sumScost / Math.abs(sumBudget)) * 100)}</span>`
      : `<span class="badge-fb">nessun budget</span>`;
    html += `<details class="group" ${cat === order[0] ? "open" : ""}>
      <summary><span class="cat-dot" style="${dotStyle}"></span>${cat}
        <span class="sum-line"><span>consuntivo ${fmtEuro(sumYtd)}</span><span>budget ${fmtEuro(sumBudget)}</span>${pctHtml}</span>
      </summary>
      <div class="table-scroll"><table class="data">
        <thead><tr><th>Conto</th><th>Delta mese</th><th>YTD</th><th>Budget YTD</th><th>Scostamento</th></tr></thead>
        <tbody>`;
    for (const r of rows) {
      const cls = r.hasBudget ? (r.favorable ? "num good" : "num critical") : "num";
      const badge = r.hasBudget ? "" : '<span class="badge-fb">Fuori budget</span>';
      html += `<tr><td>${r.c.codice} — ${r.c.descrizione}${badge}</td><td>${fmtEuro(r.delta)}</td><td>${fmtEuro(r.ytd)}</td><td>${fmtEuro(r.budgetYtd)}</td><td class="${cls}">${fmtEuro(r.scost)}</td></tr>`;
    }
    html += "</tbody></table></div></details>";
  }
  document.getElementById("scostamenti-groups").innerHTML = html;

  // Personale per reparto
  const reparti = DATA.budget.personale_reparti || {};
  const maxV = Math.max(1, ...Object.values(reparti).flat());
  let rhtml = '<table class="data"><thead><tr><th>Reparto</th>' + MONTH_LABELS.map(m => `<th>${m}</th>`).join("") + "<th>Totale</th></tr></thead><tbody>";
  for (const rep in reparti) {
    const vals = reparti[rep];
    const tot = vals.reduce((s, v) => s + v, 0);
    rhtml += `<tr><td>${rep}</td>` + vals.map(v => {
      const alpha = Math.min(0.9, (v / maxV) * 0.55);
      return `<td class="heat" style="background:rgba(42,120,214,${alpha})">${fmt(v)}</td>`;
    }).join("") + `<td>${fmt(tot)}</td></tr>`;
  }
  rhtml += "</tbody></table>";
  document.getElementById("reparto-table").innerHTML = rhtml;
}

// ---------- Navigatore ----------
let currentSoc = "ORTI";
let currentMese = LAST_MESE;

function buildTree(conti) {
  const root = { children: {}, code: "" };
  for (const c of conti) {
    const dYtd = {}, dDelta = {};
    for (const m of MESI) { dYtd[m] = dispYtd(c, m); dDelta[m] = dispDelta(c, m); }
    const parts = c.codice.split(".");
    let node = root, path = "";
    for (const p of parts) {
      path = path ? path + "." + p : p;
      if (!node.children[p]) node.children[p] = { children: {}, code: path };
      node = node.children[p];
    }
    node.leaf = { codice: c.codice, descrizione: c.descrizione, ytd: dYtd, delta: dDelta };
  }
  return root;
}

function aggregate(node) {
  if (node.leaf) { node.ytd = node.leaf.ytd; node.delta = node.leaf.delta; return; }
  const ytd = {}, delta = {};
  for (const m of MESI) { ytd[m] = 0; delta[m] = 0; }
  for (const key of Object.keys(node.children).sort()) {
    aggregate(node.children[key]);
    const ch = node.children[key];
    for (const m of MESI) { ytd[m] += ch.ytd[m] || 0; delta[m] += ch.delta[m] || 0; }
  }
  node.ytd = ytd; node.delta = delta;
}

function renderTreeNode(node) {
  const ytd = node.ytd[currentMese] || 0;
  const delta = node.delta[currentMese] || 0;
  if (node.leaf) {
    return `<div class="leaf-row">
      <span class="node-code">${node.code}</span>
      <span class="node-desc">${node.leaf.descrizione}</span>
      <span class="node-vals"><span><span class="lbl">YTD</span>${fmtEuro(ytd)}</span><span><span class="lbl">Delta</span>${fmtEuro(delta)}</span></span>
    </div>`;
  }
  const keys = Object.keys(node.children).sort();
  const depth = node.code ? node.code.split(".").length : 0;
  const childrenHtml = keys.map(k => renderTreeNode(node.children[k])).join("");
  const label = keys.length === 1 ? "" : `${keys.length} voci`;
  return `<details class="tree-node" ${depth <= 1 ? "open" : ""}>
    <summary>
      <span class="node-code">${node.code}</span>
      <span class="node-label">${label}</span>
      <span class="node-vals"><span><span class="lbl">YTD</span>${fmtEuro(ytd)}</span><span><span class="lbl">Delta</span>${fmtEuro(delta)}</span></span>
    </summary>
    <div class="tree-children">${childrenHtml}</div>
  </details>`;
}

function renderNavigator() {
  const conti = (DATA.societa[currentSoc] && DATA.societa[currentSoc].conti) || [];
  const tree = buildTree(conti);
  aggregate(tree);
  const keys = Object.keys(tree.children).sort();
  document.getElementById("tree-root").innerHTML = keys.map(k => renderTreeNode(tree.children[k])).join("");
}

document.getElementById("soc-pills").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-soc]");
  if (!btn) return;
  currentSoc = btn.dataset.soc;
  document.querySelectorAll("#soc-pills button").forEach(b => b.setAttribute("aria-pressed", String(b === btn)));
  renderNavigator();
});

const meseSelect = document.getElementById("mese-select");
meseSelect.innerHTML = MESI.map(m => `<option value="${m}" ${m === currentMese ? "selected" : ""}>${monthLabel(m)}</option>`).join("");
meseSelect.addEventListener("change", () => { currentMese = meseSelect.value; renderNavigator(); });

// ---------- Init ----------
renderKpi();
renderCatLegend();
renderMonthlyChart();
renderCumulataChart();
renderScostamenti();
renderNavigator();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description="Build artifact Bilancini")
    ap.add_argument("--budget-xlsx", type=Path, default=DEFAULT_BUDGET)
    ap.add_argument("--incidenza-xlsx", type=Path, default=DEFAULT_INCIDENZA)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log = logging.getLogger("bilancini_artifact")

    from ingest.flussi.budget_orti_xlsx import parse_budget_orti_workbook

    bilancino = fetch_bilancino(get_client())
    budget = parse_budget_orti_workbook(args.budget_xlsx, "ORTI", ANNO, log)
    incidenza = read_incidenza(args.incidenza_xlsx)
    payload = build_payload(bilancino, budget, incidenza)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_html(payload), encoding="utf-8")
    log.info(f"OK → {args.out} ({len(bilancino)} righe bilancino, {len(budget)} righe budget)")


if __name__ == "__main__":
    main()
