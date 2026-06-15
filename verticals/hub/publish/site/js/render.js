const NAVY = '#003764', AZURE = '#00a8e1', GOLD = '#ffd13f', CORAL = '#ff7f2f', SLATE = '#3a4750';
const semClass = s => s === '🟢' ? 'sem-green' : s === '🟡' ? 'sem-amber' : s === '🔴' ? 'sem-red' : '';
const charts = {};
function chart(id, cfg){ if(charts[id]) charts[id].destroy(); const el=document.getElementById(id); if(el) charts[id]=new Chart(el, cfg); }

export function renderCards(cards, onOpen){
  const root = document.getElementById('cards'); root.innerHTML = '';
  for(const c of cards){
    const el = document.createElement(c.kind === 'external' ? 'a' : 'div');
    el.className = 'card';
    if(c.kind === 'external'){ el.href = c.url; el.target = '_blank'; el.rel = 'noopener'; }
    else { el.style.cursor = 'pointer'; el.onclick = () => onOpen(c.view); }
    const sem = c.semaforo ? `<span class="sem ${semClass(c.semaforo)}"></span>` : '';
    el.innerHTML = `<h3>${c.icon || ''} ${c.title}${sem}</h3>
      <div class="metric">${c.metric}</div>
      <div class="sub">${c.subtitle || ''}</div>
      <div class="arrow">${c.kind === 'external' ? 'Apri ↗' : 'Apri →'}</div>`;
    root.appendChild(el);
  }
}

// ── Formattatori per la visualizzazione (no float grezzi) ──────────────────
const _bad = v => v == null || isNaN(v);
const eur  = v => _bad(v) ? '—' : '€ ' + Math.round(v).toLocaleString('it-IT');
const eur2 = v => _bad(v) ? '—' : '€ ' + Number(v).toFixed(2).replace('.', ',');
const pct  = v => _bad(v) ? '—' : (v * 100).toFixed(1).replace('.', ',') + '%';
const num  = v => _bad(v) ? '—' : Math.round(v).toLocaleString('it-IT');

function _yoy(cur, ap){
  if(_bad(cur) || _bad(ap) || ap === 0) return '';
  const d = (cur / ap - 1) * 100, col = d >= 0 ? '#2e9e4f' : '#dc2626';
  return ` <span style="color:${col}">(${d >= 0 ? '+' : ''}${d.toFixed(0)}%)</span>`;
}

function renderFBDetail(r){
  const rows = [
    ['RICAVI', null],
    ['Ricavi F&B totali', eur(r.ricavi_fb_totali), 1],
    ['— Breakfast', eur(r.ricavi_breakfast)],
    ['— Food', eur(r.ricavi_food)],
    ['— Beverage', eur(r.ricavi_beverage)],
    ['FOOD COST', null],
    ['Costo F&B totale', eur(r.costo_fb_totale), 1],
    ['Food cost % totale', pct(r.food_cost_pct), 1],
    ['— Breakfast', pct(r.food_cost_pct_breakfast)],
    ['— Ristorante', pct(r.food_cost_pct_ristorante)],
    ['— Bar', pct(r.food_cost_pct_bar)],
    ['OPERATIVO', null],
    ['€ / pasto', eur2(r.euro_per_pasto), 1],
    ['Coperti hotel', num(r.coperti_hotel)],
    ['Pax Breakfast / Lunch / Dinner', `${num(r.pax_breakfast)} / ${num(r.pax_lunch)} / ${num(r.pax_dinner)}`],
    ['vs ANNO PREC.', null],
    ['Ricavi F&B', eur(r.ricavi_fb_totali_ap) + _yoy(r.ricavi_fb_totali, r.ricavi_fb_totali_ap)],
    ['Costo F&B', eur(r.costo_fb_totale_ap)],
    ['Coperti hotel', num(r.coperti_hotel_ap)],
  ];
  document.querySelector('#fb-tabella tbody').innerHTML = rows.map(([label, val, bold]) => {
    if(val === null) return `<tr><th colspan="2" style="background:#f3eee6;text-transform:uppercase;`
      + `letter-spacing:.08em;font-size:.66rem;color:#00a8e1">${label}</th></tr>`;
    const w = bold ? 'font-weight:600' : '';
    return `<tr><th style="${w}">${label}</th><td style="${w}">${val}</td></tr>`;
  }).join('');
}

export function renderFB(fb){
  const serie = (fb && fb.serie) || [];
  const labels = serie.map(r => r.periodo);
  chart('chart-foodcost', {type:'line', data:{labels, datasets:[
    {label:'Ristorante', data:serie.map(r=>r.food_cost_pct_ristorante), borderColor:NAVY, tension:.3},
    {label:'Bar', data:serie.map(r=>r.food_cost_pct_bar), borderColor:AZURE, tension:.3},
    {label:'Breakfast', data:serie.map(r=>r.food_cost_pct_breakfast), borderColor:GOLD, tension:.3},
  ]}, options:{responsive:true, plugins:{legend:{position:'bottom'}}}});
  chart('chart-ricavi', {type:'bar', data:{labels, datasets:[
    {label:'Ricavi F&B', data:serie.map(r=>r.ricavi_fb_totali), backgroundColor:AZURE},
    {label:'Costo F&B', data:serie.map(r=>r.costo_fb_totale), backgroundColor:CORAL},
  ]}, options:{responsive:true, plugins:{legend:{position:'bottom'}}}});

  const sel = document.getElementById('fb-mese');
  sel.innerHTML = serie.map((r,i) => `<option value="${i}">${r.periodo || i}</option>`).join('');
  sel.value = String(serie.length - 1);
  if(serie.length) renderFBDetail(serie[serie.length - 1]);
  sel.onchange = () => renderFBDetail(serie[Number(sel.value)] || {});
}

function _opt(val){ return `<option value="${val}">${val}</option>`; }

function _renderRevList(rows){
  const tbody = document.querySelector('#rev-tabella tbody');
  const count = document.getElementById('rev-count');
  tbody.innerHTML = rows.map(r =>
    `<tr><td>${(r.data_review||'').slice(0,10)}</td><td>${r.piattaforma||''}</td>
     <td>${r.business_unit_id||''}</td><td>${r.punteggio_norm ?? ''}</td>
     <td>${r.categoria_nlp||''}</td><td>${r.sentiment_nlp||''}</td>
     <td>${r.riassunto_nlp || r.titolo || ''}</td></tr>`).join('');
  if(count) count.textContent = `${rows.length} recensioni`;
}

export function renderReviews(rev){
  const serie = (rev && rev.serie) || [];
  chart('chart-rev-trend', {type:'line', data:{labels:serie.map(r=>r.periodo), datasets:[
    {label:'Media', data:serie.map(r=>r.media), borderColor:NAVY, tension:.3, yAxisID:'y'},
    {label:'Volume', data:serie.map(r=>r.n), borderColor:AZURE, tension:.3, yAxisID:'y1'},
  ]}, options:{responsive:true, plugins:{legend:{position:'bottom'}},
    scales:{y:{position:'left',min:0,max:10}, y1:{position:'right',grid:{drawOnChartArea:false}}}}});
  const plat = (rev && rev.piattaforme) || [];
  chart('chart-rev-plat', {type:'bar', data:{labels:plat.map(p=>p.piattaforma),
    datasets:[{label:'Media', data:plat.map(p=>p.media), backgroundColor:AZURE}]},
    options:{responsive:true, indexAxis:'y', plugins:{legend:{display:false}}, scales:{x:{min:0,max:10}}}});

  // full list: prefer `tutte`, fall back to `recenti` for old snapshots
  const all = (rev && rev.tutte && rev.tutte.length) ? rev.tutte : (rev && rev.recenti) || [];

  // populate filter selects
  const selPiatt = document.getElementById('rev-piatt');
  const selSent = document.getElementById('rev-sent');
  const search = document.getElementById('rev-search');
  const piattaforme = [...new Set(all.map(r => r.piattaforma).filter(Boolean))].sort();
  const sentimenti = [...new Set(all.map(r => r.sentiment_nlp).filter(Boolean))].sort();
  selPiatt.innerHTML = '<option value="">Tutte le piattaforme</option>' + piattaforme.map(_opt).join('');
  selSent.innerHTML = '<option value="">Tutti i sentiment</option>' + sentimenti.map(_opt).join('');

  function applyFilters(){
    const p = selPiatt.value, s = selSent.value, q = (search.value || '').toLowerCase();
    _renderRevList(all.filter(r =>
      (!p || r.piattaforma === p) &&
      (!s || r.sentiment_nlp === s) &&
      (!q || (r.riassunto_nlp||'').toLowerCase().includes(q) || (r.titolo||'').toLowerCase().includes(q))
    ));
  }
  selPiatt.onchange = applyFilters;
  selSent.onchange = applyFilters;
  search.oninput = applyFilters;
  applyFilters();
}
