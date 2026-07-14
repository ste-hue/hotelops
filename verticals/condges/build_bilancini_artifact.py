#!/usr/bin/env python3
"""Builder dell'artifact "Bilancini · Gruppo Panorama".

V1 = solo numeri veri (amendment 2026-07-14): legge SOLO f_bilancino da BQ
(2026, ORTI+INTUR) e scrive un HTML self-contained (dati embedded, nessuna
richiesta esterna). Nessun confronto budget/stime.

Uso:
    python -m verticals.condges.build_bilancini_artifact [--out PATH]
"""

import argparse
import json
import logging
from datetime import date
from pathlib import Path

from core.bq.client import get_client
from core.config import PROJECT

DEFAULT_OUT = Path("docs/reports/artifacts/bilancini.html")

ANNO = 2026


def fetch_bilancino(client) -> list[dict]:
    sql = f"""
        SELECT societa_id, mese, codice_conto, descrizione, tipo_conto, sezione, saldo
        FROM `{PROJECT}.hotelops.f_bilancino`
        WHERE mese LIKE '{ANNO}-%'
    """
    return [dict(r) for r in client.query(sql).result()]


def fetch_gruppi(client) -> dict[str, str]:
    sql = f"SELECT codice_conto, descrizione FROM `{PROJECT}.hotelops.d_conti_gruppi`"
    return {r["codice_conto"]: r["descrizione"] for r in client.query(sql).result()}


def compute_delta(ytd: dict[str, float]) -> dict[str, float]:
    """delta[m] = ytd[m] − ytd[mese precedente presente]; primo mese = ytd."""
    delta = {}
    prev = 0.0
    for m in sorted(ytd):
        delta[m] = round(ytd[m] - prev, 2)
        prev = ytd[m]
    return delta


def build_payload(bilancino_rows: list[dict], gruppi: dict[str, str] | None = None) -> dict:
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
        "gruppi": gruppi or {},
    }


def render_html(payload: dict) -> str:
    data_json = json.dumps(payload, ensure_ascii=False)
    # Hardening: un `</script>` dentro una descrizione/stringa embedded
    # chiuderebbe il tag prematuramente — evaso qui, prima dell'inject.
    data_json = data_json.replace("</", "<\\/")
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
    --critical: #d03b3b;
    --cat-ricavi: #2a78d6;
    --cat-fissi: #1baf7a;
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
      --critical: #e66767;
      --cat-ricavi: #3987e5;
      --cat-fissi: #199e70;
      --soc-orti: #3987e5;
      --soc-intur: #199e70;
    }
  }
  :root[data-theme="dark"] {
    --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7; --ink-muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10); --overlay: rgba(255,255,255,0.06);
    --good: #0ca30c; --critical: #e66767;
    --cat-ricavi: #3987e5; --cat-fissi: #199e70;
    --soc-orti: #3987e5; --soc-intur: #199e70;
  }
  :root[data-theme="light"] {
    --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --ink-muted: #898781;
    --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10); --overlay: rgba(11,11,11,0.04);
    --good: #0ca30c; --critical: #d03b3b;
    --cat-ricavi: #2a78d6; --cat-fissi: #1baf7a;
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
  .kpi-sub { font-size: 12px; color: var(--ink-muted); margin-top: 2px; font-variant-numeric: tabular-nums; }
  .pill { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 700; padding: 3px 9px; border-radius: 100px; margin-top: 10px; }
  .pill.good { color: var(--good); background: color-mix(in srgb, var(--good) 14%, transparent); }
  .pill.critical { color: var(--critical); background: color-mix(in srgb, var(--critical) 14%, transparent); }
  .legend { display: flex; flex-wrap: wrap; gap: 14px; margin: 10px 0 4px; font-size: 12px; color: var(--ink-2); }
  .legend-item { display: flex; align-items: center; gap: 6px; }
  .legend-swatch { width: 11px; height: 11px; border-radius: 3px; flex: none; }
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
  .badge-fb { display: inline-block; font-size: 10.5px; font-weight: 700; color: var(--ink-muted); border: 1px solid var(--border); border-radius: 4px; padding: 1px 5px; margin-left: 6px; vertical-align: middle; }
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
<div class="wrap">
  <header class="top">
    <h1>Bilancini · Gruppo Panorama
      <span style="float:right;display:flex;gap:8px;">
        <button id="csv-btn" title="Scarica i dati in CSV (una riga per società × conto × mese)" style="appearance:none;font:inherit;font-size:12.5px;font-weight:600;color:var(--ink-2);background:var(--surface);border:1px solid var(--border);border-radius:7px;padding:6px 12px;cursor:pointer;">⬇ CSV</button>
        <button id="fs-btn" title="Schermo intero" style="appearance:none;font:inherit;font-size:12.5px;font-weight:600;color:var(--ink-2);background:var(--surface);border:1px solid var(--border);border-radius:7px;padding:6px 12px;cursor:pointer;">⛶ Schermo intero</button>
      </span>
    </h1>
    <div class="freshness" id="freshness"></div>
    <div class="navigator-controls" style="margin-top:12px;margin-bottom:0;">
      <div class="soc-pills" id="soc-pills-global">
        <button data-soc="ORTI" aria-pressed="true">ORTI</button>
        <button data-soc="INTUR" aria-pressed="false">INTUR</button>
      </div>
    </div>
    <nav class="tabnav" id="tabnav">
      <button data-tab="oggi" aria-selected="true">A oggi</button>
      <button data-tab="progressione" aria-selected="false">Progressione</button>
      <button data-tab="navigatore" aria-selected="false">Navigatore</button>
    </nav>
  </header>

  <section class="panel active" id="panel-oggi">
    <h2 class="section-title" id="title-oggi">A oggi — ORTI</h2>
    <p class="section-sub">Il conto economico dall'inizio dell'anno al mese chiuso più recente. Solo numeri veri dal bilancino, nessuna stima.</p>
    <div class="kpi-grid" id="kpi-grid"></div>
  </section>

  <section class="panel" id="panel-progressione">
    <h2 class="section-title" id="title-progressione">Progressione — ORTI, mese per mese</h2>
    <p class="section-sub">Come ci siamo arrivati: il delta di ogni mese, per macro-gruppo del conto economico reale.</p>
    <div class="card">
      <div class="chart-row">
        <div>
          <h3 style="font-size:12.5px;color:var(--ink-muted);font-weight:700;text-transform:uppercase;letter-spacing:.03em;margin-bottom:8px;">Entrate vs uscite del mese</h3>
          <div class="legend" id="cat-legend"></div>
          <svg class="chart" id="chart-monthly" viewBox="0 0 640 260" preserveAspectRatio="xMinYMin meet"></svg>
          <details class="data-fallback"><summary>Vedi tabella dati</summary><div class="table-scroll" id="table-monthly"></div></details>
        </div>
        <div>
          <h3 style="font-size:12.5px;color:var(--ink-muted);font-weight:700;text-transform:uppercase;letter-spacing:.03em;margin-bottom:8px;">Margine cumulato YTD</h3>
          <svg class="chart" id="chart-cumulata" viewBox="0 0 640 260" preserveAspectRatio="xMinYMin meet"></svg>
          <details class="data-fallback"><summary>Vedi tabella dati</summary><div class="table-scroll" id="table-cumulata"></div></details>
        </div>
      </div>
    </div>
    <div class="card" style="margin-top:16px;">
      <h3 style="font-size:13px;font-weight:700;margin-bottom:4px;">Delta mensile per macro-gruppo</h3>
      <p class="section-sub" style="margin-bottom:12px;">Gruppi top-level del piano dei conti (CE). Entrate e uscite mostrate positive, direzione dichiarata per riga.</p>
      <div class="table-scroll" id="gruppi-table"></div>
    </div>
  </section>

  <section class="panel" id="panel-navigatore">
    <h2 class="section-title">Navigatore — piano dei conti</h2>
    <p class="section-sub">Albero dai prefissi di conto per la società selezionata in testa. Saldo YTD e delta del mese selezionato, i gruppi sommano le foglie.</p>
    <div class="navigator-controls">
      <label for="mese-select" style="font-size:12.5px;color:var(--ink-muted);">Mese</label>
      <select id="mese-select"></select>
    </div>
    <p class="sign-note">Segni: ricavi CE mostrati positivi (saldo invertito); costi CE e voci patrimoniali mostrati come da saldo contabile.</p>
    <div class="table-scroll">
      <div class="tree-root" id="tree-root"></div>
    </div>
  </section>

  <footer class="note">Bilancini · Gruppo Panorama — dati BigQuery (f_bilancino), solo numeri veri. Artifact rigenerabile, non è una fonte.</footer>
</div>

<script>
const DATA = __DATA__;
const MONTH_LABELS = ["Gen","Feb","Mar","Apr","Mag","Giu","Lug","Ago","Set","Ott","Nov","Dic"];

function fmt(n) { return new Intl.NumberFormat("it-IT", { maximumFractionDigits: 0 }).format(Math.round(n || 0) || 0); }
function fmtEuro(n) { return "€ " + fmt(n); }
function monthNum(mese) { return parseInt(mese.slice(5, 7), 10); }
function monthLabel(mese) { return MONTH_LABELS[monthNum(mese) - 1] + " " + mese.slice(0, 4); }
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// -- sign convention: ricavi CE mostrati positivi (saldo bilancino è negativo per i ricavi) --
// Entrata se sezione="Ricavi" (dato già corretto) OPPURE prefisso top-level 53
// ("Altri ricavi e proventi" — nei dati storici in BQ arriva ancora con
// sezione="Costi" fino al prossimo promote, quindi il prefisso è il fallback).
function isEntrata(c) { return c.sezione === "Ricavi" || c.codice.split(".")[0] === "53"; }
function ceConti(soc) {
  const list = (DATA.societa[soc] && DATA.societa[soc].conti) || [];
  return list.filter(c => c.tipo === "CE");
}
function dispYtd(c, mese) { const v = c.ytd[mese] || 0; return isEntrata(c) ? -v : v; }
function dispDelta(c, mese) { const v = c.delta[mese] || 0; return isEntrata(c) ? -v : v; }

const MESI = DATA.mesi;
function lastMeseFor(soc) {
  let max = null;
  for (const c of (DATA.societa[soc] && DATA.societa[soc].conti) || []) {
    for (const m of Object.keys(c.ytd)) {
      if (max === null || m > max) max = m;
    }
  }
  return max || MESI[MESI.length - 1];
}

// ---------- Export CSV (client-side, formato tidy: una riga per società × conto × mese) ----------
document.getElementById("csv-btn").addEventListener("click", () => {
  const q = (s) => '"' + String(s).replace(/"/g, '""') + '"';
  const lines = ["societa,mese,codice_conto,descrizione,tipo_conto,sezione,saldo_ytd,delta_mese"];
  for (const soc of Object.keys(DATA.societa)) {
    for (const c of DATA.societa[soc].conti) {
      for (const mese of Object.keys(c.ytd).sort()) {
        lines.push([soc, mese, c.codice, q(c.descrizione), c.tipo, c.sezione,
          c.ytd[mese], c.delta[mese] ?? ""].join(","));
      }
    }
  }
  const blob = new Blob(["\\ufeff" + lines.join("\\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `bilancini_2026_al_${DATA.generated_at}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
});

// ---------- Schermo intero (si nasconde se il contesto non lo permette, es. iframe senza allowfullscreen) ----------
const fsBtn = document.getElementById("fs-btn");
if (!document.fullscreenEnabled) {
  fsBtn.style.display = "none";
} else {
  fsBtn.addEventListener("click", () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else document.documentElement.requestFullscreen();
  });
  document.addEventListener("fullscreenchange", () => {
    fsBtn.textContent = document.fullscreenElement ? "✕ Esci" : "⛶ Schermo intero";
  });
}

// ---------- Tabs ----------
document.getElementById("tabnav").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-tab]");
  if (!btn) return;
  document.querySelectorAll("#tabnav button").forEach(b => b.setAttribute("aria-selected", String(b === btn)));
  document.querySelectorAll("section.panel").forEach(p => p.classList.toggle("active", p.id === "panel-" + btn.dataset.tab));
});

// ---------- Freshness ----------
function updateFreshness() {
  const lastOrti = lastMeseFor("ORTI");
  const lastIntur = lastMeseFor("INTUR");
  const el = document.getElementById("freshness");
  if (lastOrti === lastIntur) {
    el.textContent = `dati al ${lastOrti} · generato il ${DATA.generated_at}`;
  } else {
    el.textContent = `dati al ${lastMeseFor(currentSoc)} (${currentSoc}) — ORTI ${lastOrti} · INTUR ${lastIntur} · generato il ${DATA.generated_at}`;
  }
}

// ---------- Società (selettore globale) ----------
let currentSoc = "ORTI";

// ---------- A oggi (KPI) ----------
function kpiTotals() {
  const lastMese = lastMeseFor(currentSoc);
  const conti = ceConti(currentSoc);
  let ricaviYtd = 0, costiYtd = 0, ricaviMese = 0, costiMese = 0;
  for (const c of conti) {
    if (isEntrata(c)) {
      ricaviYtd += dispYtd(c, lastMese);
      ricaviMese += dispDelta(c, lastMese);
    } else {
      costiYtd += dispYtd(c, lastMese);
      costiMese += dispDelta(c, lastMese);
    }
  }
  return {
    ricavi: { ytd: ricaviYtd, mese: ricaviMese },
    costi: { ytd: costiYtd, mese: costiMese },
    margine: { ytd: ricaviYtd - costiYtd, mese: ricaviMese - costiMese },
    lastMese,
  };
}

function kpiTile(label, ytd, mese, kind, lastMese) {
  const meseLabel = MONTH_LABELS[monthNum(lastMese) - 1];
  // Margine può essere negativo (perdita reale, non un artefatto di segno
  // bilancino): lo si etichetta esplicitamente invece di lasciare solo il "-".
  const tag = kind === "margine" && ytd < 0 ? ' <span class="badge-fb">perdita</span>' : "";
  const pill = kind === "margine"
    ? `<div class="pill ${ytd >= 0 ? "good" : "critical"}">${ytd >= 0 ? "utile" : "perdita"} YTD</div>`
    : "";
  const meseVal = kind === "margine" && mese < 0 ? `−${fmtEuro(-mese)}` : fmtEuro(mese);
  return `
    <div class="kpi-tile">
      <div class="kpi-label">${label}</div>
      <div class="kpi-value">${fmtEuro(ytd)}${tag}</div>
      <div class="kpi-sub">di cui ${meseLabel}: ${meseVal}</div>
      ${pill}
    </div>`;
}

function renderKpi() {
  const t = kpiTotals();
  document.getElementById("kpi-grid").innerHTML =
    kpiTile("Ricavi YTD", t.ricavi.ytd, t.ricavi.mese, "ricavi", t.lastMese) +
    kpiTile("Costi YTD", t.costi.ytd, t.costi.mese, "costi", t.lastMese) +
    kpiTile("Margine YTD", t.margine.ytd, t.margine.mese, "margine", t.lastMese);
}

// ---------- Progressione ----------
function monthlyTotals() {
  const conti = ceConti(currentSoc);
  const out = MESI.map((m) => {
    let entrate = 0, uscite = 0;
    for (const c of conti) {
      if (isEntrata(c)) entrate += dispDelta(c, m);
      else uscite += dispDelta(c, m);
    }
    return { mese: m, entrate, uscite };
  });
  return out;
}

function svgEl(tag, attrs) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}

function renderMonthlyChart() {
  const tot = monthlyTotals();
  const svg = document.getElementById("chart-monthly");
  svg.innerHTML = "";
  const W = 640, H = 260, padL = 54, padR = 10, padT = 10, padB = 26;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const n = MESI.length;
  const slot = plotW / n;
  const barW = slot * 0.30;

  const maxVal = Math.max(1, ...tot.flatMap(t => [t.entrate, t.uscite]));
  const scale = (v) => (Math.max(0, v) / maxVal) * plotH;

  for (let g = 0; g <= 4; g++) {
    const y = padT + plotH - (g / 4) * plotH;
    svg.appendChild(svgEl("line", { class: "gridline", x1: padL, x2: W - padR, y1: y, y2: y }));
    const label = svgEl("text", { x: padL - 8, y: y + 3, "text-anchor": "end" });
    label.textContent = fmt((g / 4) * maxVal);
    svg.appendChild(label);
  }
  svg.appendChild(svgEl("line", { class: "axis-line", x1: padL, x2: padL, y1: padT, y2: padT + plotH }));

  const rows = [["Mese", "Entrate (ricavi)", "Uscite (costi)"]];
  tot.forEach((t, i) => {
    const xc = padL + i * slot + slot / 2;
    const he = scale(t.entrate), hu = scale(t.uscite);
    svg.appendChild(svgEl("rect", {
      x: xc - barW - 1, y: padT + plotH - he, width: barW, height: he,
      fill: "var(--cat-ricavi)", rx: 1.5,
    }));
    svg.appendChild(svgEl("rect", {
      x: xc + 1, y: padT + plotH - hu, width: barW, height: hu,
      fill: "var(--cat-fissi)", rx: 1.5,
    }));
    const lab = svgEl("text", { x: xc, y: H - 6, "text-anchor": "middle" });
    lab.textContent = MONTH_LABELS[monthNum(t.mese) - 1];
    svg.appendChild(lab);
    rows.push([monthLabel(t.mese), fmt(t.entrate), fmt(t.uscite)]);
  });

  document.getElementById("table-monthly").innerHTML = tableFromRows(rows);
}

function renderCumulataChart() {
  const svg = document.getElementById("chart-cumulata");
  svg.innerHTML = "";
  const W = 640, H = 260, padL = 54, padR = 14, padT = 10, padB = 26;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const n = MESI.length;

  const tot = monthlyTotals();
  const cum = [];
  let acc = 0;
  const rows = [["Mese", "Margine cumulato"]];
  tot.forEach((t) => {
    acc += t.entrate - t.uscite;
    cum.push(acc);
    rows.push([monthLabel(t.mese), fmt(acc)]);
  });

  const minV = Math.min(0, ...cum);
  const maxV = Math.max(1, ...cum);
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
  if (minV < 0) {
    svg.appendChild(svgEl("line", { class: "axis-line", x1: padL, x2: W - padR, y1: y(0), y2: y(0) }));
  }

  const pts = cum.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  svg.appendChild(svgEl("polyline", {
    points: pts, fill: "none", stroke: "var(--cat-ricavi)",
    "stroke-width": 2.4, "stroke-linejoin": "round", "stroke-linecap": "round",
  }));
  cum.forEach((v, i) => {
    svg.appendChild(svgEl("circle", { cx: x(i), cy: y(v), r: 3, fill: "var(--cat-ricavi)" }));
  });

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
  document.getElementById("cat-legend").innerHTML =
    '<span class="legend-item"><span class="legend-swatch" style="background:var(--cat-ricavi)"></span>Entrate (ricavi)</span>' +
    '<span class="legend-item"><span class="legend-swatch" style="background:var(--cat-fissi)"></span>Uscite (costi)</span>';
}

// ---------- Delta mensile per macro-gruppo (top-level CE) ----------
function renderGruppiTable() {
  // Gruppi dai prefissi top-level del codice conto (47, 55, 57, …). Etichetta
  // da DATA.gruppi (d_conti_gruppi); fallback sul codice se mancante.
  const lastMese = lastMeseFor(currentSoc);
  const conti = ceConti(currentSoc);
  const gruppi = {};
  for (const c of conti) {
    const pref = c.codice.split(".")[0];
    const g = gruppi[pref] || (gruppi[pref] = { pref, entrata: isEntrata(c), delta: {}, ytd: 0 });
    for (const m of MESI) g.delta[m] = (g.delta[m] || 0) + dispDelta(c, m);
    g.ytd += dispYtd(c, lastMese);
  }
  const order = Object.values(gruppi).sort((a, b) =>
    a.entrata === b.entrata ? a.pref.localeCompare(b.pref) : (a.entrata ? -1 : 1));
  let html = '<table class="data"><thead><tr><th>Gruppo</th><th>Direzione</th>' +
    MESI.map(m => `<th>${MONTH_LABELS[monthNum(m) - 1]}</th>`).join("") +
    "<th>YTD</th></tr></thead><tbody>";
  for (const g of order) {
    const dir = g.entrata ? "Entrate" : "Uscite";
    const label = escapeHtml(DATA.gruppi[g.pref] || g.pref);
    html += `<tr><td>${label}</td><td>${dir}</td>` +
      MESI.map(m => `<td>${fmt(g.delta[m] || 0)}</td>`).join("") +
      `<td>${fmt(g.ytd)}</td></tr>`;
  }
  html += "</tbody></table>";
  document.getElementById("gruppi-table").innerHTML = html;
}

// ---------- Navigatore ----------
let currentMese = lastMeseFor(currentSoc);

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
      <span class="node-desc">${escapeHtml(node.leaf.descrizione)}</span>
      <span class="node-vals"><span><span class="lbl">YTD</span>${fmtEuro(ytd)}</span><span><span class="lbl">Delta</span>${fmtEuro(delta)}</span></span>
    </div>`;
  }
  const keys = Object.keys(node.children).sort();
  const depth = node.code ? node.code.split(".").length : 0;
  const childrenHtml = keys.map(k => renderTreeNode(node.children[k])).join("");
  const label = escapeHtml(DATA.gruppi[node.code] || node.code);
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

function updateSocTitles() {
  document.getElementById("title-oggi").textContent = `A oggi — ${currentSoc}`;
  document.getElementById("title-progressione").textContent = `Progressione — ${currentSoc}, mese per mese`;
}

document.getElementById("soc-pills-global").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-soc]");
  if (!btn) return;
  currentSoc = btn.dataset.soc;
  document.querySelectorAll("#soc-pills-global button").forEach(b => b.setAttribute("aria-pressed", String(b === btn)));
  updateSocTitles();
  updateFreshness();
  renderKpi();
  renderMonthlyChart();
  renderCumulataChart();
  renderGruppiTable();
  renderNavigator();
});

const meseSelect = document.getElementById("mese-select");
meseSelect.innerHTML = MESI.map(m => `<option value="${m}" ${m === currentMese ? "selected" : ""}>${monthLabel(m)}</option>`).join("");
meseSelect.addEventListener("change", () => { currentMese = meseSelect.value; renderNavigator(); });

// ---------- Init ----------
updateFreshness();
renderKpi();
renderCatLegend();
renderMonthlyChart();
renderCumulataChart();
renderGruppiTable();
renderNavigator();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description="Build artifact Bilancini")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log = logging.getLogger("bilancini_artifact")

    client = get_client()
    bilancino = fetch_bilancino(client)
    gruppi = fetch_gruppi(client)
    payload = build_payload(bilancino, gruppi)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_html(payload), encoding="utf-8")
    log.info(f"OK → {args.out} ({len(bilancino)} righe bilancino)")


if __name__ == "__main__":
    main()
