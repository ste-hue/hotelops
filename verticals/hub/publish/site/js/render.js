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

const _FB_LABELS = {
  anno:'Anno', mese:'Mese', periodo:'Periodo',
  ricavi_breakfast:'Ricavi Breakfast', ricavi_food:'Ricavi Food', ricavi_beverage:'Ricavi Beverage',
  ricavi_fb_totali:'Ricavi F&B totali', costo_breakfast:'Costo Breakfast',
  costo_ristorante:'Costo Ristorante', costo_bar:'Costo Bar', costo_fb_totale:'Costo F&B totale',
  pax_breakfast:'Pax Breakfast', pax_lunch:'Pax Lunch', pax_dinner:'Pax Dinner',
  coperti_hotel:'Coperti hotel',
  food_cost_pct_breakfast:'Food cost % Breakfast', food_cost_pct_ristorante:'Food cost % Ristorante',
  food_cost_pct_bar:'Food cost % Bar', food_cost_pct:'Food cost % totale',
  euro_per_pasto:'€/pasto',
  ricavi_fb_totali_ap:'Ricavi F&B (AP)', costo_fb_totale_ap:'Costo F&B (AP)',
  coperti_hotel_ap:'Coperti hotel (AP)',
};

function renderFBDetail(row){
  document.querySelector('#fb-tabella tbody').innerHTML =
    Object.entries(row).map(([k,v]) =>
      `<tr><th>${_FB_LABELS[k] || k}</th><td>${v ?? '—'}</td></tr>`
    ).join('');
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
