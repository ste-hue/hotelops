const semClass = s => s === '🟢' ? 'sem-green' : s === '🟡' ? 'sem-amber' : s === '🔴' ? 'sem-red' : '';

export function renderCards(cards){
  const root = document.getElementById('cards'); root.innerHTML = '';
  for(const c of cards){
    const el = document.createElement('a');
    el.className = 'card';
    el.href = c.url; el.target = '_blank'; el.rel = 'noopener';
    const sem = c.semaforo ? `<span class="sem ${semClass(c.semaforo)}"></span>` : '';
    const metricHtml = c.metric ? `<div class="metric">${c.metric}</div>` : '';
    el.innerHTML = `<h3>${c.icon || ''} ${c.title}${sem}</h3>
      ${metricHtml}
      <div class="sub">${c.subtitle || ''}</div>
      <div class="arrow">Apri ↗</div>`;
    root.appendChild(el);
  }
}
