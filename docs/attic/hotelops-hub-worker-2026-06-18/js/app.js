"use strict";

// Superfici esterne legate nella forma in cui già esistono.
const BANCHE_URL =
  "https://lookerstudio.google.com/reporting/2a7a4c25-56f2-44d4-986f-9a9cc27a03cd/page/TlJ0C";

const NAVY = "#003764", AZURE = "#00a8e1", TEAL = "#00bfd6", CORAL = "#ff7f2f", GOLD = "#ffd13f", SAND = "#f3eee6";
const PLAT_COLORS = [NAVY, AZURE, TEAL, GOLD, CORAL];

const eur = new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const pct = (v) => (v == null ? "—" : (v * 100).toFixed(1).replace(".", ",") + "%");
const MESI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"];
const meseLabel = (periodo) => {
  const [y, m] = periodo.split("-");
  return `${MESI[parseInt(m, 10) - 1]} ${y.slice(2)}`;
};

function fail(msg) {
  document.getElementById("stato-dati").innerHTML =
    `<span class="err">Dati non disponibili: ${msg}</span>`;
}

async function load(name) {
  const r = await fetch(`data/${name}.json`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${name}.json (${r.status})`);
  return r.json();
}

function renderMeta(meta) {
  document.getElementById("card-banche").href = BANCHE_URL;
  document.getElementById("gen-at").textContent =
    new Date(meta.generated_at).toLocaleString("it-IT");
  const sems = Object.values(meta.surfaces).map((s) => s.semaforo);
  const worst = sems.includes("🔴") ? "🔴" : sems.includes("🟡") ? "🟡" : "🟢";
  const fb = meta.surfaces.fb, rev = meta.surfaces.reviews;
  document.getElementById("card-rev-metric").textContent = rev.media_mese ?? "n/d";
  document.getElementById("stato-dati").textContent =
    `Stato dati: ${worst} · F&B ${fb.semaforo} (${fb.giorni} gg fa) · Reviews ${rev.semaforo} (media ${rev.media_mese ?? "n/d"})`;
}

function renderFb(fb) {
  const serie = fb.serie;
  const labels = serie.map((r) => meseLabel(r.periodo));

  // Ultimo mese consuntivato = ultimo con ricavi > 0 (il mese in corso è a zero).
  const cons = [...serie].reverse().find((r) => (r.ricavi_fb_totali || 0) > 0);
  if (cons) {
    document.getElementById("card-fb-metric").textContent = pct(cons.food_cost_pct_ristorante);
    document.getElementById("card-fb-sub").textContent =
      `food cost ristorante · ${meseLabel(cons.periodo)}`;
    const rows = [
      ["Ricavi F&B", eur.format(cons.ricavi_fb_totali)],
      ["Costo F&B", eur.format(cons.costo_fb_totale)],
      ["Food cost % ristorante", pct(cons.food_cost_pct_ristorante)],
      ["Food cost % bar", pct(cons.food_cost_pct_bar)],
      ["Food cost % breakfast", pct(cons.food_cost_pct_breakfast)],
      ["€/pasto", eur.format(cons.euro_per_pasto)],
      ["Coperti hotel", new Intl.NumberFormat("it-IT").format(cons.coperti_hotel)],
    ];
    document.querySelector("#fb-tabella tbody").innerHTML =
      rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("");
  }

  const line = (label, key, color) => ({
    label, borderColor: color, backgroundColor: color, tension: 0.3, spanGaps: true,
    data: serie.map((r) => (r[key] == null ? null : r[key] * 100)),
  });
  new Chart(document.getElementById("chart-foodcost"), {
    type: "line",
    data: { labels, datasets: [
      line("Ristorante", "food_cost_pct_ristorante", NAVY),
      line("Bar", "food_cost_pct_bar", AZURE),
      line("Breakfast", "food_cost_pct_breakfast", CORAL),
    ] },
    options: { responsive: true, plugins: { legend: { position: "bottom" } },
      scales: { y: { ticks: { callback: (v) => v + "%" } } } },
  });

  new Chart(document.getElementById("chart-ricavi"), {
    type: "bar",
    data: { labels, datasets: [
      { label: "Ricavi F&B", backgroundColor: GOLD, data: serie.map((r) => r.ricavi_fb_totali) },
      { label: "Costo F&B", backgroundColor: CORAL, data: serie.map((r) => r.costo_fb_totale) },
    ] },
    options: { responsive: true, plugins: { legend: { position: "bottom" } },
      scales: { y: { ticks: { callback: (v) => eur.format(v) } } } },
  });
}

function renderReviews(rev) {
  const serie = rev.serie || [];
  const labels = serie.map((r) => meseLabel(r.periodo));
  new Chart(document.getElementById("chart-rev-trend"), {
    type: "bar",
    data: { labels, datasets: [
      { type: "line", label: "Media", yAxisID: "y", borderColor: NAVY, tension: 0.3,
        data: serie.map((r) => r.media) },
      { label: "N. recensioni", yAxisID: "y1", backgroundColor: SAND,
        data: serie.map((r) => r.n) },
    ] },
    options: { responsive: true, plugins: { legend: { position: "bottom" } },
      scales: {
        y: { position: "left", min: 0, max: 10, title: { display: true, text: "media" } },
        y1: { position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "n." } },
      } },
  });

  const plat = rev.piattaforme || [];
  new Chart(document.getElementById("chart-rev-plat"), {
    type: "bar",
    data: { labels: plat.map((p) => p.piattaforma), datasets: [
      { label: "N. recensioni", data: plat.map((p) => p.n),
        backgroundColor: plat.map((_, i) => PLAT_COLORS[i % PLAT_COLORS.length]) },
    ] },
    options: { responsive: true, plugins: { legend: { display: false },
      tooltip: { callbacks: { afterLabel: (c) => `media ${plat[c.dataIndex].media}` } } } },
  });

  document.querySelector("#rev-tabella tbody").innerHTML = (rev.recenti || [])
    .map((r) => {
      const v = r.punteggio_norm;
      const col = v != null && v < 7 ? ` style="color:${CORAL}"` : "";
      const txt = (r.riassunto_nlp || r.titolo || "").slice(0, 90);
      return `<tr><td>${r.data_review || ""}</td><td>${r.piattaforma || ""}</td>` +
        `<td${col}>${v ?? "—"}</td><td style="text-align:left">${txt}</td></tr>`;
    }).join("");
}

function renderSpiaggia(sp) {
  const serie = sp.serie || [];
  const labels = serie.map((r) => meseLabel(r.periodo));

  // Card: last month with stabilimento > 0.
  const last = [...serie].reverse().find((r) => (r.stabilimento || 0) > 0);
  if (last) {
    document.getElementById("card-sp-metric").textContent = eur.format(last.stabilimento);
    document.getElementById("card-sp-sub").textContent =
      `stabilimento · ${meseLabel(last.periodo)}`;
    const rows = [
      ["Banco (diretto)", eur.format(last.banco)],
      ["Alloggiati (hotel)", eur.format(last.alloggiati)],
      ["Stabilimento totale", eur.format(last.stabilimento)],
      ["Moolty (POS)", eur.format(last.moolty)],
      ["Scost. cassa", eur.format(last.scost_cassa)],
    ];
    document.querySelector("#sp-tabella tbody").innerHTML =
      rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("");
  }

  // Stacked bar: banco + alloggiati per mese.
  new Chart(document.getElementById("chart-sp-ricavi"), {
    type: "bar",
    data: { labels, datasets: [
      { label: "Banco (diretto)", backgroundColor: NAVY, data: serie.map((r) => r.banco), stack: "s" },
      { label: "Alloggiati (hotel)", backgroundColor: GOLD, data: serie.map((r) => r.alloggiati), stack: "s" },
    ] },
    options: { responsive: true, plugins: { legend: { position: "bottom" } },
      scales: { y: { ticks: { callback: (v) => eur.format(v) } } } },
  });

  // Grouped bar: registro fiscale vs Moolty.
  new Chart(document.getElementById("chart-sp-quadratura"), {
    type: "bar",
    data: { labels, datasets: [
      { label: "Registro fiscale", backgroundColor: AZURE, data: serie.map((r) => r.banco) },
      { label: "Moolty (POS)", backgroundColor: TEAL, data: serie.map((r) => r.moolty) },
    ] },
    options: { responsive: true, plugins: { legend: { position: "bottom" } },
      scales: { y: { ticks: { callback: (v) => eur.format(v) } } } },
  });
}

(async () => {
  try {
    renderMeta(await load("_meta"));
  } catch (e) { fail(e.message); }
  try {
    renderFb(await load("fb"));
  } catch (e) {
    document.getElementById("fb-error").innerHTML = `<div class="err">F&B: ${e.message}</div>`;
  }
  try {
    renderReviews(await load("reviews"));
  } catch (e) {
    document.getElementById("rev-error").innerHTML = `<div class="err">Reviews: ${e.message}</div>`;
  }
  try {
    renderSpiaggia(await load("spiaggia"));
  } catch (e) {
    document.getElementById("sp-error").innerHTML = `<div class="err">Spiaggia: ${e.message}</div>`;
  }
})();
