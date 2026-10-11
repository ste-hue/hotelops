"""Build del cruscotto Canone ORTI → INTUR: una pagina HTML autonoma.

Stesso schema di ``build_bilancini_artifact``: i dati entrano nel template come
JSON, il calcolo gira nel browser (porting di ``canone_sim``, verificato dai test
contro il motore Python). L'output contiene numeri del business plan → finisce in
``docs/reports/artifacts/`` (gitignored), mai in git.

    python -m verticals.condges.build_canone_artifact [--aggiorna] [--push] [--out FILE]

``--aggiorna`` interroga prima le fonti osservate (BigQuery, sola lettura) e
rinnova lo snapshot datato; senza, usa l'ultimo snapshot salvato.
``--push`` pubblica la pagina su https://canone.panorama-host.com (Worker ``canone``
in panorama_apps, dietro Cloudflare Access nominativo): niente redeploy del Worker.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from verticals.condges import canone_fonti as cf
from verticals.condges import canone_sim as cs

DEFAULT_OUT = Path("docs/reports/artifacts/canone.html")

_APERTE = [
    "Altri ricavi hotel: la quota di raccordo nella base 2026 ha composizione e crescita da verificare.",
    "Altre attività 2027: Residence, CVM e spiaggia ospiti crescono del 13% nel BP; da verificare.",
    "Fitto Angelina (2027-28): i numeri del file lo tengono in INTUR fino al 2028, un'etichetta lo dà a terzi dal 2027.",
    "Budget Rooms: capacità di ottobre 2027 più bassa del 2026 e ADR di giugno 2030 in calo.",
    "Completezza del debito: l'elenco dei debiti esistenti va confermato con l'app Mutui.",
    "IVA sull'investimento: il recupero l'anno dopo è un'ipotesi del modello.",
    "Prestiti congelati: rate e interessi sono gli importi annui del BP; cambiare tasso o durata richiede di rifare i piani.",
    "2031: oltre il Budget Rooms 2026–2030.",
    "Soglia 1,20: obiettivo del modello, non un covenant contrattuale verificato.",
    "Simulazione annuale: non dimostra la tenuta della cassa nei mesi invernali.",
]


def build_payload(inputs: dict, osservati: dict | None, generato_il: datetime | None = None) -> dict:
    """Tutto ciò che la pagina mostra o calcola. Niente ``expected`` né metadati interni."""
    years = {
        y: {"orti": v["orti"], "intur": v["intur"]}
        for y, v in inputs["years"].items()
        if 2026 <= int(y) <= 2031
    }
    base = cs.scenario_base(inputs)
    return {
        "generato_il": (generato_il or datetime.now()).isoformat(timespec="minutes"),
        "fonte": cs.fonte(inputs),
        "common": inputs["common"],
        "prior2025": inputs["prior2025"],
        "prior2026": inputs["prior2026"],
        "years": years,
        "base": {"nome": "Base", "angelina": base["angelina"],
                 "anni": {str(y): v for y, v in base["anni"].items()}},
        "fonti": cf.stato_fonti(inputs, osservati),
        "confronti": cf.base_vs_osservato(inputs, osservati),
        "osservati_del": (osservati or {}).get("acquisito_il", ""),
        "provenienza": cf.provenienza(inputs),
        "aperte": _APERTE,
        "schema": cs.SCHEMA,
    }


def render_html(payload: dict) -> str:
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return HTML_TEMPLATE.replace("__DATA__", data_json)


# ---------- push KV (Cloudflare Worker "canone", repo panorama_apps) ----------

# Id del namespace KV `canone-content`: non è un segreto (sta nel wrangler.jsonc del Worker).
KV_NAMESPACE_ID = "40c87a6c5b624fe48f6158aa01ebcaa2"
PUSH_ENV_VARS = ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID")


def load_push_env() -> dict[str, str]:
    """Credenziali push da os.environ (il chiamante carica il .env). Mancanti → RuntimeError."""
    import os

    env = {k: os.environ.get(k, "") for k in PUSH_ENV_VARS}
    missing = [k for k, v in env.items() if not v]
    if missing:
        raise RuntimeError(f"--push richiede variabili d'ambiente mancanti: {', '.join(missing)}")
    return env


def push_to_kv(html: str, env: dict[str, str]) -> None:
    """Carica la pagina nel KV del Worker canone (chiave ``html``)."""
    import requests

    url = (
        f"https://api.cloudflare.com/client/v4/accounts/{env['CLOUDFLARE_ACCOUNT_ID']}"
        f"/storage/kv/namespaces/{KV_NAMESPACE_ID}/bulk"
    )
    r = requests.put(
        url, json=[{"key": "html", "value": html}],
        headers={"Authorization": f"Bearer {env['CLOUDFLARE_API_TOKEN']}"},
        timeout=60,
    )
    if not (r.ok and r.json().get("success")):
        raise RuntimeError(f"Push KV fallito: HTTP {r.status_code} — {r.text[:500]}")


HTML_TEMPLATE = r"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Canone ORTI → INTUR</title>
<style>
:root{
  --bg:#faf9f6; --card:#ffffff; --ink:#1d1c1a; --muted:#6d6a64; --line:#e5e2db; --soft:#f1efe9;
  --accent:#1d5c87; --ok:#3f6b58; --warn:#a86400; --bad:#b3261e; --warn-bg:#fbf1dd; --bad-bg:#fbe6e3;
}
@media (prefers-color-scheme: dark){:root{
  --bg:#151513; --card:#1d1d1a; --ink:#ecebe6; --muted:#9c988f; --line:#32312d; --soft:#252521;
  --accent:#7db7e0; --ok:#86b8a0; --warn:#e2a64a; --bad:#f08a80; --warn-bg:#3a2e17; --bad-bg:#3d201d;
}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
main{max-width:860px;margin:0 auto;padding:28px 16px 56px}
h1{font-size:22px;font-weight:650;letter-spacing:-.01em;margin:0}
.sub{color:var(--muted);margin:2px 0 0}
.verdetto{margin:18px 0 6px;padding:10px 12px;border-radius:8px;background:var(--soft);font-weight:550}
.verdetto.warn{background:var(--warn-bg);color:var(--warn)} .verdetto.bad{background:var(--bad-bg);color:var(--bad)}
.verdetto small{display:block;font-weight:400;color:var(--ink);opacity:.85;margin-top:2px}
.num{font-variant-numeric:tabular-nums}
table{width:100%;border-collapse:collapse}
.scaletta{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;margin-top:10px}
.scaletta th{font-size:12px;font-weight:600;color:var(--muted);text-align:left;padding:10px 12px;border-bottom:1px solid var(--line)}
.scaletta td{padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:middle}
.scaletta tr:last-child td{border-bottom:0}
.scaletta tr.sel td:first-child{box-shadow:inset 3px 0 0 var(--accent)}
.scaletta tbody tr{cursor:pointer}
td.anno{font-weight:650;width:72px}
input.n{width:118px;max-width:100%;font:inherit;font-variant-numeric:tabular-nums;text-align:right;color:var(--ink);
  background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:5px 8px}
input.n:focus{outline:2px solid var(--accent);outline-offset:0;border-color:var(--accent)}
input.n.mod{border-color:var(--accent);box-shadow:inset 0 -2px 0 var(--accent)}
input.n.pct{width:76px}
.d{display:flex;align-items:center;gap:8px;min-width:96px}
.d b{font-weight:600;min-width:34px}
.d.warn b{color:var(--warn)} .d.bad b{color:var(--bad)}
.bar{position:relative;flex:1;height:5px;background:var(--soft);border-radius:3px;min-width:36px}
.bar i{position:absolute;left:0;top:0;bottom:0;border-radius:3px;background:var(--ok)}
.d.warn .bar i{background:var(--warn)} .d.bad .bar i{background:var(--bad)}
.bar u{position:absolute;top:-3px;bottom:-3px;width:1px;background:var(--ink);opacity:.55}
.cfr{display:block;font-size:11.5px;color:var(--muted);margin-top:1px}
.errore{color:var(--bad);margin:8px 2px 0;min-height:1.2em}
.leva{display:flex;flex-wrap:wrap;gap:6px 8px;align-items:center;margin:12px 2px 0}
.leva label{font-weight:600} .leva span{color:var(--muted);font-size:13px}
.riga-az{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;margin:8px 2px 0;color:var(--muted);font-size:13px}
button{font:inherit;font-size:13px;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:6px;padding:5px 10px;cursor:pointer}
button:hover{border-color:var(--accent)} button.link{border:0;background:none;color:var(--accent);padding:0}
details{background:var(--card);border:1px solid var(--line);border-radius:10px;margin-top:12px}
summary{cursor:pointer;padding:12px 14px;font-weight:600;list-style:none;display:flex;justify-content:space-between;gap:12px}
summary::-webkit-details-marker{display:none}
summary span{font-weight:400;color:var(--muted);font-size:13px;text-align:right}
details[open] summary{border-bottom:1px solid var(--line)}
.corpo{padding:12px 14px 14px}
.t th{font-size:12px;color:var(--muted);font-weight:600;text-align:right;padding:6px 8px;border-bottom:1px solid var(--line)}
.t th:first-child,.t td:first-child{text-align:left}
.t td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;font-variant-numeric:tabular-nums}
.t tr:last-child td{border-bottom:0}
.t tr.tot td{font-weight:650;border-top:1px solid var(--ink)}
.t.sx td,.t.sx th{text-align:left}
.nota{color:var(--muted);font-size:13px;margin:10px 0 0}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
.tabs button.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.chip{display:inline-block;font-size:11.5px;padding:1px 7px;border-radius:10px;background:var(--soft);color:var(--muted)}
.chip.osservato{color:var(--ok)} .chip.impegno{color:var(--accent)} .chip.ipotesi{color:var(--warn)}
h3{font-size:13px;margin:16px 0 6px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.04em}
h3:first-child{margin-top:0}
ul{margin:6px 0 0;padding-left:18px} li{margin:3px 0}
.scroll{overflow-x:auto}
select,input[type=text].nome{font:inherit;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:5px 8px}
footer{color:var(--muted);font-size:12.5px;margin-top:18px}
@media (max-width:560px){
  .bar{display:none} .d{min-width:0} input.n{width:104px} .scaletta td,.scaletta th{padding:8px 8px}
  summary span{display:none}
}
@media (max-width:420px){
  main{padding:20px 10px 48px} td.anno{width:44px} input.n{width:92px;padding:5px 6px} input.n.pct{width:62px}
  .scaletta td,.scaletta th{padding:8px 6px} .verdetto{font-size:14px}
}
</style>
</head>
<body>
<main>
  <h1>ORTI + INTUR · fino al 2031</h1>
  <p class="sub">La scaletta del canone regge le due gambe?</p>

  <div id="verdetto" class="verdetto"></div>

  <div class="scaletta scroll">
    <table>
      <thead><tr><th>Anno</th><th>Canone · €</th><th>ORTI</th><th>INTUR</th><th>Gruppo</th></tr></thead>
      <tbody id="righe"></tbody>
    </table>
  </div>
  <div id="errore" class="errore" role="alert"></div>
  <div class="leva">
    <label for="costi-tutti">Costi operativi ORTI su ricavi</label>
    <input class="n pct" id="costi-tutti" inputmode="decimal" aria-label="Costi operativi ORTI su ricavi, tutti gli anni"> %
    <span id="costi-nota"></span>
  </div>
  <div class="riga-az">
    <span id="stato"></span>
    <button id="ripristina" class="link" hidden>Torna alla base</button>
    <span>DSCR = cassa per le rate ÷ rate dell'anno · tacca a 1,20</span>
  </div>

  <details id="d-ipotesi">
    <summary>Ipotesi <span>ricavi, crescita e costi di ORTI · fitto Angelina</span></summary>
    <div class="corpo">
      <div class="scroll"><table class="t" id="ipotesi"></table></div>
      <p class="nota">Il 2026 è in corso: i valori di partenza sono l'atterraggio del business plan, modificabili fino a chiusura d'anno. Ricavi e crescita sono la stessa leva: cambi uno, l'altro segue, e gli anni dopo tengono la loro crescita. Il canone non si muove quando cambi queste ipotesi.</p>
      <p class="nota">Fitto Angelina 2027–28 (pagato da ORTI):
        <select id="angelina"><option value="intur">a INTUR · ipotesi del file</option><option value="terzi">a terzi · ipotesi alternativa</option></select>
      </p>
    </div>
  </details>

  <details id="d-dettaglio">
    <summary>Dettaglio dell'anno <span>dai ricavi al residuo dopo le rate</span></summary>
    <div class="corpo">
      <div class="tabs" id="tabs"></div>
      <div class="scroll"><table class="t" id="flussi"></table></div>
      <p class="nota" id="banda"></p>
      <p class="nota" id="cassa"></p>
    </div>
  </details>

  <details id="d-scenari">
    <summary>Scenari <span>salva, riapri, confronta</span></summary>
    <div class="corpo">
      <p style="margin:0 0 10px"><input type="text" class="nome" id="nome" placeholder="Nome dello scenario" maxlength="60">
        <button id="salva">Salva</button> <button id="esporta">Esporta JSON</button>
        <button id="importa">Importa JSON</button><input type="file" id="file" accept="application/json" hidden></p>
      <div class="scroll"><table class="t sx" id="salvati"></table></div>
      <p class="nota" id="msg-scenari"></p>
      <p class="nota">Gli scenari restano in questo browser; per conservarli o passarli a un altro dispositivo usa «Esporta JSON».</p>
    </div>
  </details>

  <details id="d-fonti">
    <summary>Fonti e questioni aperte <span id="fonti-sub"></span></summary>
    <div class="corpo">
      <h3>Stato delle fonti</h3>
      <div class="scroll"><table class="t sx" id="fonti"></table></div>
      <h3>Base 2026 del modello accanto ai fatti osservati</h3>
      <div class="scroll"><table class="t" id="confronti"></table></div>
      <p class="nota" id="confronti-nota"></p>
      <h3>Provenienza degli input</h3>
      <div class="scroll"><table class="t sx" id="provenienza"></table></div>
      <h3>Questioni aperte e limiti</h3>
      <ul id="aperte"></ul>
    </div>
  </details>

  <footer id="piede"></footer>
</main>

<script type="application/json" id="dati">__DATA__</script>
<script id="motore">
// Porting di verticals/condges/canone_sim.py — tenuto allineato dai test (pytest + node).
const MOTORE = (() => {
  const ANNI = [2027, 2028, 2029, 2030, 2031], TUTTI = [2026, ...ANNI];
  const excelRound = x => Math.sign(x) * Math.floor(Math.abs(x) + 0.5);
  const ratio = (a, b) => (b ? a / b : null);

  function riga(D, y, crescita, costi, canone, angelina, prevRev, prevInturRev, prevCash, w) {
    const c = D.common, t = c.taxRate, m = c.maintenanceRate, s = c.targetDSCR;
    const o = D.years[y].orti, i = D.years[y].intur;
    const ricaviO = prevRev * (1 + crescita), costiO = ricaviO * costi, ebitdaAnte = ricaviO - costiO;
    const aTerzi = (y === 2027 || y === 2028) && angelina === 'terzi';
    const angelinaAIntur = y <= 2028 && !aTerzi ? o.angelinaRent : 0;
    const altriI = i.beachRevenue + i.otherRentRevenue - (aTerzi ? o.angelinaRent : 0);
    const manO = m * ricaviO, ccnO = w * (ricaviO - prevRev), affr = i.reserveReleasePayment;

    const maxTax = ebitdaAnte - o.angelinaRent - (s * o.debtService + manO + ccnO - t * (o.depreciation + o.interest)) / (1 - t);
    const massimo = ebitdaAnte - maxTax - o.angelinaRent - o.depreciation - o.interest >= 0
      ? maxTax : ebitdaAnte - o.angelinaRent - s * o.debtService - manO - ccnO;
    const fabbisogno = s * i.debtService + m * altriI + w * (altriI - prevInturRev) + affr;
    const minTax = (fabbisogno - t * (i.depreciation + i.interest) - (altriI - i.operatingCosts) * (1 - t)) / (1 - t - m - w);
    const minimo = altriI + minTax - i.operatingCosts - i.depreciation - i.interest >= 0
      ? minTax : (fabbisogno - (altriI - i.operatingCosts)) / (1 - m - w);

    if (canone === null) {
      canone = massimo < minimo ? massimo
        : Math.min(massimo, Math.max(minimo, excelRound((minimo + c.bandPosition * (massimo - minimo)) / c.roundingEUR) * c.roundingEUR));
      canone = Math.max(0, canone);
    }
    const ebitdaO = ebitdaAnte - canone - o.angelinaRent;
    const taxO = Math.max(0, ebitdaO - o.depreciation - o.interest) * t;
    const ricaviI = altriI + canone, ebitdaI = ricaviI - i.operatingCosts;
    const taxI = Math.max(0, ebitdaI - i.depreciation - i.interest) * t;
    const manI = m * ricaviI, ccnI = w * (ricaviI - prevInturRev);
    const cfadsO = ebitdaO - taxO - manO - ccnO, cfadsI = ebitdaI - taxI - manI - ccnI - affr;
    const rateO = o.debtService, rateI = i.debtService, br = i.cashBridge;
    const cassaI = prevCash + ebitdaI - taxI - rateI - affr + br.newLoanDrawdowns - br.investmentSpend
      - br.investmentVATPaid + br.investmentVATRecovered;
    return {
      anno: y, canone, canone_min_intur: minimo, canone_max_orti: massimo,
      ricavi_o: ricaviO, ricavi_o_prec: prevRev, crescita, costi_o: costiO, incidenza_costi: costi,
      angelina_o: o.angelinaRent, angelina_a_intur: angelinaAIntur,
      tax_o: taxO, man_o: manO, ccn_o: ccnO, cfads_o: cfadsO, rate_o: rateO,
      ricavi_i: ricaviI, altri_ricavi_i: altriI, costi_i: i.operatingCosts,
      tax_i: taxI, man_i: manI, ccn_i: ccnI, affr_i: affr, cfads_i: cfadsI, rate_i: rateI, cassa_i: cassaI,
      rate_i_dettaglio: i.debtServiceBreakdown || {},
      dscr_o: ratio(cfadsO, rateO), dscr_i: ratio(cfadsI, rateI), dscr_g: ratio(cfadsO + cfadsI, rateO + rateI),
      residuo_o: cfadsO - rateO, residuo_i: cfadsI - rateI,
      manca_o: Math.max(0, s * rateO - cfadsO), manca_i: Math.max(0, s * rateI - cfadsI),
      manca_g: Math.max(0, s * (rateO + rateI) - cfadsO - cfadsI),
    };
  }

  function riga2026(D, sc) {
    const o = D.years[2026].orti, p = D.prior2025;
    const l = (sc && sc.anni[2026]) || {crescita: o.revenue / p.ortiRevenue - 1, costi: o.operatingCostRate, canone: D.prior2026.appliedRent};
    return riga(D, 2026, l.crescita, l.costi, l.canone, 'intur', p.ortiRevenue, p.inturRevenue, p.inturClosingCash, 0);
  }

  function calcola(D, sc, automatico) {
    let prec = riga2026(D, sc);
    return ANNI.map(y => {
      const p = sc.anni[y];
      prec = riga(D, y, p.crescita, p.costi, automatico ? null : p.canone, sc.angelina,
        prec.ricavi_o, prec.ricavi_i, prec.cassa_i, D.common.workingCapitalRate);
      return prec;
    });
  }

  const copia = sc => JSON.parse(JSON.stringify(sc));

  function equilibrio(D, sc, anno) {
    const prova = copia(sc);
    let lo = 0, hi = 1e7;
    for (let k = 0; k < 60; k++) {
      const medio = (lo + hi) / 2;
      prova.anni[anno].canone = medio;
      const r = righe(D, prova).find(x => x.anno === anno);
      if (r.dscr_o > r.dscr_i) lo = medio; else hi = medio;
    }
    return (lo + hi) / 2;
  }

  const righe = (D, sc) => [riga2026(D, sc), ...calcola(D, sc)];

  // Per ogni anno: [minimo, massimo] ammessi dalla scaletta non decrescente (il 2026 parte libero).
  function limiti(D, sc, anno) {
    const k = TUTTI.indexOf(anno);
    return [k === 0 ? 0 : sc.anni[TUTTI[k - 1]].canone,
            k === TUTTI.length - 1 ? 1e7 : sc.anni[TUTTI[k + 1]].canone];
  }

  function imponiRicavi(D, sc, anno, ricavi) {
    const r = righe(D, sc).find(x => x.anno === anno);
    sc.anni[anno].crescita = ricavi / r.ricavi_o_prec - 1;
  }

  return {ANNI, TUTTI, riga2026, calcola, righe, equilibrio, limiti, imponiRicavi, copia};
})();
if (typeof module !== 'undefined') module.exports = MOTORE;
</script>
<script>
(() => {
  const D = JSON.parse(document.getElementById('dati').textContent);
  const {ANNI, TUTTI, righe: calcolaTutte, equilibrio, limiti, imponiRicavi, copia} = MOTORE;
  const $ = id => document.getElementById(id);
  const S = D.common.targetDSCR;
  const nf0 = new Intl.NumberFormat('it-IT', {maximumFractionDigits: 0});
  const nf2 = new Intl.NumberFormat('it-IT', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const euro = x => nf0.format(Math.round(x)).replace('-', '−');
  const flusso = x => Math.abs(x) < 0.5 ? '—' : (x > 0 ? '+' : '−') + nf0.format(Math.abs(Math.round(x)));
  const pct = x => nf2.format(x * 100);
  const dtxt = v => v === null ? 'n.d.' : nf2.format(v);
  const classe = v => v === null ? '' : v < 1 - 1e-9 ? 'bad' : v < S - 1e-9 ? 'warn' : '';
  const leggi = testo => { const v = Number(String(testo).replace(/\./g, '').replace(/\s|€|%/g, '').replace(',', '.')); return Number.isFinite(v) ? v : NaN; };
  const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const base = () => { const b = copia(D.base); return b; };

  let sc = base(), anno = 2028, confronto = null, errore = '';
  const CHIAVE = 'canone-sim:scenari';
  const salvati = () => { try { return JSON.parse(localStorage.getItem(CHIAVE) || '[]'); } catch (e) { return []; } };
  const scrivi = lista => { try { localStorage.setItem(CHIAVE, JSON.stringify(lista)); return true; } catch (e) { return false; } };

  const diverso = (y, campo) => Math.abs(sc.anni[y][campo] - D.base.anni[y][campo]) > 1e-9;
  const modificato = () => sc.angelina !== D.base.angelina || TUTTI.some(y => ['canone', 'crescita', 'costi'].some(c => diverso(y, c)));

  function cellaDscr(v, vCfr, tetto) {
    const k = classe(v);
    const cfr = vCfr === undefined ? '' : `<span class="cfr">${esc(confronto.nome)}: ${dtxt(vCfr)}</span>`;
    return `<td><div class="d ${k}"><b class="num">${dtxt(v)}</b><span class="bar"><i style="width:${Math.max(0, Math.min(1, v / tetto)) * 100}%"></i><u style="left:${S / tetto * 100}%"></u></span></div>${cfr}</td>`;
  }

  function disegna() {
    const tutte = calcolaTutte(D, sc), righe = tutte;
    const cfr = confronto ? calcolaTutte(D, confronto) : null;
    const tetto = Math.max(2, ...tutte.flatMap(r => [r.dscr_o, r.dscr_i, r.dscr_g])) * 1.04;

    // verdetto
    const sotto1 = [], sottoS = [];
    righe.forEach(r => [['ORTI', r.dscr_o], ['INTUR', r.dscr_i]].forEach(([n, v]) => {
      if (v < 1 - 1e-9) sotto1.push(`${r.anno} ${n} ${dtxt(v)}`); else if (v < S - 1e-9) sottoS.push(`${r.anno} ${n} ${dtxt(v)}`);
    }));
    const peggio = righe.reduce((a, r) => Math.min(a, r.dscr_o, r.dscr_i), Infinity);
    const v = $('verdetto');
    if (sotto1.length) { v.className = 'verdetto bad'; v.innerHTML = `Non regge: sotto 1,00 la cassa dell'anno non copre le rate<small>${sotto1.join(' · ')}${sottoS.length ? ' — sotto 1,20: ' + sottoS.join(' · ') : ''}</small>`; }
    else if (sottoS.length) { v.className = 'verdetto warn'; v.innerHTML = `Regge, ma non arriva a ${dtxt(S)} ovunque · punto più basso ${dtxt(peggio)}<small>Sotto ${dtxt(S)}: ${sottoS.join(' · ')}</small>`; }
    else { v.className = 'verdetto'; v.innerHTML = `Regge: ORTI e INTUR sopra ${dtxt(S)} in ogni anno · punto più basso ${dtxt(peggio)}`; }

    // scaletta
    $('righe').innerHTML =
      righe.map((r, k) => `<tr data-anno="${r.anno}" class="${r.anno === anno ? 'sel' : ''}"><td class="anno">${r.anno}${r.anno === 2026 ? '<span class="cfr" style="white-space:nowrap">in corso</span>' : ''}</td>
        <td><input class="n ${diverso(r.anno, 'canone') ? 'mod' : ''}" inputmode="numeric" data-campo="canone" data-anno="${r.anno}" value="${euro(r.canone)}" aria-label="Canone ${r.anno} in euro">${cfr ? `<span class="cfr">${esc(confronto.nome)}: ${euro(cfr[k].canone)}</span>` : ''}</td>
        ${cellaDscr(r.dscr_o, cfr ? cfr[k].dscr_o : undefined, tetto)}${cellaDscr(r.dscr_i, cfr ? cfr[k].dscr_i : undefined, tetto)}${cellaDscr(r.dscr_g, cfr ? cfr[k].dscr_g : undefined, tetto)}</tr>`).join('');
    $('errore').textContent = errore;
    $('stato').textContent = (sc.nome === 'Base' ? 'Scenario base' : 'Scenario «' + sc.nome + '»') + (modificato() ? ' · modificato rispetto alla base' : '') + (confronto ? ' · confronto con «' + confronto.nome + '»' : '');
    $('ripristina').hidden = !modificato() && !confronto && sc.nome === 'Base';

    // leva costi: un valore per tutti gli anni (il dettaglio per anno sta in Ipotesi)
    const cs = TUTTI.map(y => sc.anni[y].costi), uguali = cs.every(c => Math.abs(c - cs[0]) < 1e-9);
    const cb = TUTTI.map(y => D.base.anni[y].costi), baseTxt = [...new Set(cb.map(pct))].join(' / ');
    $('costi-tutti').value = uguali ? pct(cs[0]) : '';
    $('costi-tutti').placeholder = uguali ? '' : 'vari';
    $('costi-tutti').classList.toggle('mod', TUTTI.some(y => diverso(y, 'costi')));
    $('costi-nota').textContent = (uguali ? 'tutti gli anni, 2026 incluso' : 'diversi per anno: ' + cs.map(pct).join(' / ')) + ' · nel BP ' + baseTxt;

    // ipotesi
    $('ipotesi').innerHTML = '<tr><th>Anno</th><th>Ricavi ORTI · €</th><th>Crescita · %</th><th>Costi / ricavi · %</th></tr>' +
      righe.map(r => `<tr><td>${r.anno}</td>
        <td><input class="n ${diverso(r.anno, 'crescita') ? 'mod' : ''}" inputmode="numeric" data-campo="ricavi" data-anno="${r.anno}" value="${euro(r.ricavi_o)}" aria-label="Ricavi ORTI ${r.anno}"></td>
        <td><input class="n pct ${diverso(r.anno, 'crescita') ? 'mod' : ''}" inputmode="decimal" data-campo="crescita" data-anno="${r.anno}" value="${pct(r.crescita)}" aria-label="Crescita ${r.anno}"></td>
        <td><input class="n pct ${diverso(r.anno, 'costi') ? 'mod' : ''}" inputmode="decimal" data-campo="costi" data-anno="${r.anno}" value="${pct(r.incidenza_costi)}" aria-label="Costi su ricavi ${r.anno}"></td></tr>`).join('');
    $('angelina').value = sc.angelina;

    // dettaglio
    $('tabs').innerHTML = tutte.map(r => `<button data-tab="${r.anno}" class="${r.anno === anno ? 'on' : ''}">${r.anno}</button>`).join('');
    const r = tutte.find(x => x.anno === anno), aTerzi = r.angelina_o - r.angelina_a_intur;
    const riga = (nome, a, b, g, tot) => `<tr class="${tot ? 'tot' : ''}"><td>${nome}</td><td>${a}</td><td>${b}</td><td>${g}</td></tr>`;
    $('flussi').innerHTML = '<tr><th>' + anno + ' · €</th><th>ORTI</th><th>INTUR</th><th>Gruppo</th></tr>' + [
      riga('Ricavi verso terzi (netti IVA)', flusso(r.ricavi_o), flusso(r.altri_ricavi_i - r.angelina_a_intur), flusso(r.ricavi_o + r.altri_ricavi_i - r.angelina_a_intur)),
      riga('Costi operativi', flusso(-r.costi_o), flusso(-r.costi_i), flusso(-r.costi_o - r.costi_i)),
      riga('Canone ORTI → INTUR', flusso(-r.canone), flusso(r.canone), 'si elimina'),
      riga('Fitto Angelina', flusso(-r.angelina_o), flusso(r.angelina_a_intur), aTerzi ? flusso(-aTerzi) : 'si elimina'),
      riga('Imposte (forfait del modello)', flusso(-r.tax_o), flusso(-r.tax_i), flusso(-r.tax_o - r.tax_i)),
      riga('Riserva manutenzione', flusso(-r.man_o), flusso(-r.man_i), flusso(-r.man_o - r.man_i)),
      riga('Circolante (variazione ricavi)', flusso(-r.ccn_o), flusso(-r.ccn_i), flusso(-r.ccn_o - r.ccn_i)),
      riga('Affrancamento riserve', '—', flusso(-r.affr_i), flusso(-r.affr_i)),
      riga('Cassa per le rate (CFADS)', euro(r.cfads_o), euro(r.cfads_i), euro(r.cfads_o + r.cfads_i), true),
      riga('Rate annue', euro(r.rate_o), euro(r.rate_i), euro(r.rate_o + r.rate_i)),
      riga('DSCR', dtxt(r.dscr_o), dtxt(r.dscr_i), dtxt(r.dscr_g)),
      riga('Residuo annuale dopo le rate', flusso(r.residuo_o), flusso(r.residuo_i), flusso(r.residuo_o + r.residuo_i)),
      riga('Manca per arrivare a ' + dtxt(S), r.manca_o ? euro(r.manca_o) : '—', r.manca_i ? euro(r.manca_i) : '—', r.manca_g ? euro(r.manca_g) : '—'),
    ].join('');
    {
      const lo = r.canone_min_intur, hi = r.canone_max_orti, eq = equilibrio(D, sc, anno);
      $('banda').textContent = (hi < 0 ? 'ORTI sotto la soglia anche a canone zero.'
        : lo > hi ? `Nessun canone porta entrambe a ${dtxt(S)}: a INTUR ne servono almeno ${euro(lo)}, ORTI ne regge al massimo ${euro(hi)} (divario ${euro(lo - hi)}, non è un ammanco di cassa).`
        : `Entrambe a ${dtxt(S)} con un canone tra ${euro(Math.max(0, lo))} e ${euro(hi)}.`)
        + ` Canone di equilibrio (stesso DSCR alle due): ${euro(eq)}.`;
    }
    const d = r.rate_i_dettaglio;
    $('cassa').textContent = `Rate INTUR: debiti esistenti ${euro(d.existing || 0)} + SAL ${euro(d.sal || 0)} + MCC ${euro(d.mcc || 0)}. `
      + `Cassa INTUR a fine ${anno} secondo il modello: ${euro(r.cassa_i)} € (prima delle riserve manutenzione e circolante). `
      + 'Il residuo dopo le rate è un flusso dell\'anno, non un saldo di banca.';

    // scenari
    const lista = salvati();
    $('salvati').innerHTML = lista.length ? '<tr><th>Scenario</th><th>Salvato</th><th>Scaletta</th><th></th></tr>' + lista.map((s, k) =>
      `<tr><td>${esc(s.nome)}</td><td>${esc((s.salvato_il || '').replace('T', ' ').slice(0, 16))}</td><td class="num">${TUTTI.filter(y => s.anni[y]).map(y => nf0.format(s.anni[y].canone / 1000)).join(' / ')}</td>
       <td><button data-apri="${k}">Apri</button> <button data-cfr="${k}">Confronta</button> <button data-via="${k}">Elimina</button></td></tr>`).join('')
      : '<tr><td style="color:var(--muted)">Nessuno scenario salvato: la base è l\'unico.</td></tr>';
  }

  function fisse() {
    const stato = s => /^BLOCCATA/.test(s) ? 'bad' : '';
    $('fonti').innerHTML = '<tr><th>Fonte</th><th>Tipo</th><th>Stato</th><th>Acquisito</th></tr>' + D.fonti.map(f =>
      `<tr><td>${esc(f.fonte)}<br><span class="cfr">${esc(f.riferimento)} · ${esc(f.dimensione)}</span></td><td><span class="chip ${esc(f.tipo)}">${esc(f.tipo)}</span></td><td style="color:var(--${stato(f.stato) ? 'bad' : 'ink'})">${esc(f.stato)}</td><td class="num">${esc(f.acquisito_il)}</td></tr>`).join('');
    $('confronti').innerHTML = D.confronti.length ? '<tr><th>Voce</th><th>Modello 2026 · anno intero</th><th>Osservato</th><th>Quando</th></tr>' + D.confronti.map(c =>
      `<tr><td>${esc(c.voce)}</td><td>${c.modello_2026 === null ? '—' : euro(c.modello_2026)}</td><td>${euro(c.osservato)}</td><td>${esc(c.quando)}</td></tr>`).join('')
      : '<tr><td style="color:var(--muted)">Nessuno snapshot degli osservati.</td></tr>';
    $('confronti-nota').textContent = D.confronti.length ? 'Gli osservati sono parziali d\'anno e non entrano nel calcolo: servono a giudicare la base 2026, che resta quella del business plan. Snapshot del ' + D.osservati_del.replace('T', ' ') + '.' : '';
    $('provenienza').innerHTML = '<tr><th>Voce</th><th>Società</th><th>Tipo</th><th>Unità</th><th>Celle</th></tr>' + D.provenienza.map(p =>
      `<tr><td>${esc(p.voce)}</td><td>${esc(p['società'])}</td><td><span class="chip ${esc(p.tipo)}">${esc(p.tipo)}</span></td><td>${esc(p['unità'])}</td><td>${esc(p.celle)}</td></tr>`).join('');
    $('aperte').innerHTML = D.aperte.map(a => `<li>${esc(a)}</li>`).join('');
    const collegate = D.fonti.filter(f => f.stato === 'collegata').length;
    $('fonti-sub').textContent = `${collegate} fonti collegate · ${D.fonti.length - collegate} da snapshot o non collegate`;
    $('piede').textContent = `Fonte: ${D.fonte.file} · impronta ${D.fonte.sha256_fonte.slice(0, 8) || 'n.d.'} · ricavi netti IVA · rate = debiti esistenti + nuovi SAL e MCC del terzo piano · simulazione annuale, non verifica la liquidità mese per mese · pagina generata il ${D.generato_il.replace('T', ' ')}.`;
  }

  function modifica(input) {
    const y = Number(input.dataset.anno), campo = input.dataset.campo, v = leggi(input.value);
    errore = '';
    if (!Number.isFinite(v)) { errore = 'Inserisci un numero.'; return disegna(); }
    if (campo === 'canone') {
      const [lo, hi] = limiti(D, sc, y);
      if (v < lo || v > hi) { errore = `La scaletta non può scendere: per il ${y} scegli tra ${euro(lo)} e ${euro(hi)}. Per uscire da questo intervallo, cambia prima l'anno accanto.`; return disegna(); }
      sc.anni[y].canone = v;
    } else if (campo === 'ricavi') {
      if (v <= 0) { errore = 'I ricavi devono essere positivi.'; return disegna(); }
      imponiRicavi(D, sc, y, v);
    } else if (campo === 'crescita') {
      if (v <= -100) { errore = 'Crescita non valida.'; return disegna(); }
      sc.anni[y].crescita = v / 100;
    } else if (campo === 'costi') {
      if (v < 0 || v > 100) { errore = 'L\'incidenza dei costi deve stare tra 0 e 100%.'; return disegna(); }
      sc.anni[y].costi = v / 100;
    }
    disegna();
  }

  const documento = () => ({schema: D.schema, nome: sc.nome, salvato_il: new Date().toISOString().slice(0, 19), fonte: D.fonte, angelina: sc.angelina, anni: sc.anni});
  function valida(doc) {
    if (!doc || doc.schema !== D.schema) throw new Error('non è uno scenario del simulatore canone');
    if (!['intur', 'terzi'].includes(doc.angelina)) throw new Error('fitto Angelina non valido');
    let prec = 0;
    if (doc.anni && !doc.anni[2026]) doc.anni[2026] = D.base.anni[2026];  // scenari salvati prima del 2026 modificabile
    for (const y of TUTTI) {
      const a = doc.anni && doc.anni[y];
      if (!a || ![a.canone, a.crescita, a.costi].every(Number.isFinite)) throw new Error('anno ' + y + ' mancante o non numerico');
      if (a.canone < prec) throw new Error('scaletta in discesa nel ' + y);
      prec = a.canone;
    }
    return {nome: String(doc.nome || 'Scenario'), salvato_il: doc.salvato_il || '', angelina: doc.angelina,
      anni: Object.fromEntries(TUTTI.map(y => [y, {crescita: doc.anni[y].crescita, costi: doc.anni[y].costi, canone: doc.anni[y].canone}])),
      altraFonte: !doc.fonte || doc.fonte.sha256_inputs !== D.fonte.sha256_inputs};
  }
  const msg = t => { $('msg-scenari').textContent = t; };

  document.addEventListener('change', e => {
    if (e.target.id === 'costi-tutti') {
      const v = leggi(e.target.value);
      if (!Number.isFinite(v) || v < 0 || v > 100) errore = 'L\'incidenza dei costi deve stare tra 0 e 100%.';
      else { errore = ''; TUTTI.forEach(y => { sc.anni[y].costi = v / 100; }); }
      disegna();
    }
    else if (e.target.matches('input.n')) modifica(e.target);
    else if (e.target.id === 'angelina') { sc.angelina = e.target.value; disegna(); }
    else if (e.target.id === 'file' && e.target.files[0]) {
      e.target.files[0].text().then(t => {
        const s = valida(JSON.parse(t));
        sc = {nome: s.nome, angelina: s.angelina, anni: s.anni}; confronto = null; errore = '';
        msg('Scenario «' + s.nome + '» importato.' + (s.altraFonte ? ' Era stato salvato su una versione diversa dei dati di base: le leve sono le stesse, i risultati possono differire.' : ''));
        disegna();
      }).catch(err => msg('Scenario non importato: ' + err.message));
      e.target.value = '';
    }
  });
  document.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.matches('input.n')) e.target.blur(); });
  document.addEventListener('click', e => {
    const t = e.target;
    if (t.dataset.tab) { anno = Number(t.dataset.tab); return disegna(); }
    if (t.id === 'ripristina') { sc = base(); confronto = null; errore = ''; msg(''); return disegna(); }
    if (t.id === 'salva') {
      const nome = $('nome').value.trim();
      if (!nome || nome === 'Base') return msg('Dai allo scenario un nome diverso da «Base».');
      sc.nome = nome;
      const lista = salvati().filter(s => s.nome !== nome); lista.push(documento());
      msg(scrivi(lista) ? 'Salvato «' + nome + '».' : 'Il browser non permette il salvataggio: usa «Esporta JSON».');
      return disegna();
    }
    if (t.id === 'esporta') {
      const nome = $('nome').value.trim(); if (nome) sc.nome = nome;
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([JSON.stringify(documento(), null, 2)], {type: 'application/json'}));
      a.download = 'canone_' + sc.nome.toLowerCase().replace(/[^a-z0-9]+/g, '-') + '.json'; a.click(); URL.revokeObjectURL(a.href);
      return;
    }
    if (t.id === 'importa') return $('file').click();
    if (t.dataset.apri !== undefined || t.dataset.cfr !== undefined) {
      try {
        const s = valida(salvati()[Number(t.dataset.apri ?? t.dataset.cfr)]), pulito = {nome: s.nome, angelina: s.angelina, anni: s.anni};
        if (t.dataset.apri !== undefined) { sc = pulito; confronto = null; $('nome').value = s.nome; } else confronto = pulito;
        errore = ''; msg(s.altraFonte ? 'Scenario salvato su una versione diversa dei dati di base: i risultati possono differire.' : '');
      } catch (err) { msg('Scenario non valido: ' + err.message); }
      return disegna();
    }
    if (t.dataset.via !== undefined) { const l = salvati(); l.splice(Number(t.dataset.via), 1); scrivi(l); return disegna(); }
    const tr = t.closest && t.closest('tr[data-anno]');
    if (tr && !t.matches('input')) { anno = Number(tr.dataset.anno); disegna(); }
  });

  fisse(); disegna();
})();
</script>
</body>
</html>
"""


def run(out: Path = DEFAULT_OUT, aggiorna: bool = False, push: bool = False) -> None:
    push_env = None
    if push:
        from core.env import load_dotenv_file

        load_dotenv_file()
        push_env = load_push_env()  # fail-fast: env incompleta → errore prima del build

    path = cs.inputs_path()
    if not path.exists():
        raise SystemExit(f"Dati di base non trovati: {path} (numeri del BP, fuori da git).")
    inputs = cs.load_inputs(path.read_bytes())
    osservati = cf.salva_osservati(cf.aggiorna()) if aggiorna else cf.carica_osservati()

    html = render_html(build_payload(inputs, osservati))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Scritto {out}")
    for f in cf.stato_fonti(inputs, osservati):
        print(f"  {f['fonte']}: {f['stato']} ({f['acquisito_il'] or 'mai'})")
    if push_env is not None:
        push_to_kv(html, push_env)
        print("Push KV OK → https://canone.panorama-host.com")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build cruscotto Canone ORTI → INTUR")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--aggiorna", action="store_true",
                    help="interroga le fonti osservate (BigQuery, sola lettura) prima del build")
    ap.add_argument("--push", action="store_true",
                    help="dopo il build, pubblica la pagina nel KV del Worker canone (dietro Access)")
    args = ap.parse_args()
    run(args.out, args.aggiorna, args.push)


if __name__ == "__main__":
    main()
