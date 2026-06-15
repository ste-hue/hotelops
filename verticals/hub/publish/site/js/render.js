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
  const last = serie[serie.length-1] || {};
  const rows = [['Periodo', last.periodo], ['Food cost %', last.food_cost_pct],
    ['€/pasto', last.euro_per_pasto], ['Ricavi F&B', last.ricavi_fb_totali]];
  document.querySelector('#fb-tabella tbody').innerHTML =
    rows.map(([k,v]) => `<tr><th>${k}</th><td>${v ?? '—'}</td></tr>`).join('');
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
  const rec = (rev && rev.recenti) || [];
  document.querySelector('#rev-tabella tbody').innerHTML = rec.map(r =>
    `<tr><td>${(r.data_review||'').slice(0,10)}</td><td>${r.piattaforma||''}</td>
     <td>${r.punteggio_norm ?? ''}</td><td>${r.riassunto_nlp || r.titolo || ''}</td></tr>`).join('');
}
