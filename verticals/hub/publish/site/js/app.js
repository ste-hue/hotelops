import { loadManifest } from './manifest.js';
import { renderCards, renderFB, renderReviews } from './render.js';

const J = (p) => fetch(p, {cache:'no-store'}).then(r => { if(!r.ok) throw new Error(p); return r.json(); });
const dataCache = {};
async function data(name){ if(!dataCache[name]) dataCache[name] = await J(`data/${name}.json`); return dataCache[name]; }

function show(view){
  document.querySelectorAll('[data-view]').forEach(s => s.classList.toggle('active', s.dataset.view === view));
  window.scrollTo(0,0);
  if(view === 'fb') data('fb').then(renderFB).catch(()=>err('fb-error'));
  if(view === 'reviews') data('reviews').then(renderReviews).catch(()=>err('rev-error'));
}
function err(id){ const e=document.getElementById(id); if(e) e.textContent='Dati non disponibili.'; }
function go(view){ location.hash = view === 'home' ? '' : `#${view}`; }
function currentView(){ return (location.hash || '#home').slice(1) || 'home'; }

async function boot(){
  try{
    const { cards, generated_at } = await loadManifest();
    renderCards(cards, go);
    document.getElementById('stato-dati').textContent =
      generated_at ? `Aggiornato: ${generated_at.slice(0,16).replace('T',' ')}` : 'Snapshot';
    const g = document.getElementById('gen-at'); if(g && generated_at) g.textContent = generated_at.slice(0,16).replace('T',' ');
  }catch(e){
    document.getElementById('stato-dati').textContent = 'Dati non disponibili (snapshot mancante).';
  }
  document.querySelectorAll('[data-back]').forEach(b => b.onclick = () => go('home'));
  window.addEventListener('hashchange', () => show(currentView()));
  show(currentView());
}
boot();
