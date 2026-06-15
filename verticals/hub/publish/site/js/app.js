import { loadManifest } from './manifest.js';
import { renderCards } from './render.js';

async function boot(){
  try{
    const { cards, generated_at } = await loadManifest();
    renderCards(cards);
    document.getElementById('stato-dati').textContent =
      generated_at ? `Aggiornato: ${generated_at.slice(0,16).replace('T',' ')}` : 'Snapshot';
    const g = document.getElementById('gen-at'); if(g && generated_at) g.textContent = generated_at.slice(0,16).replace('T',' ');
  }catch(e){
    document.getElementById('stato-dati').textContent = 'Dati non disponibili (snapshot mancante).';
  }
}
boot();
