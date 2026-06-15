// Carica apps.json (le card) + _meta.json (freshness) e li fonde.
const J = (p) => fetch(p, {cache: 'no-store'}).then(r => { if(!r.ok) throw new Error(p); return r.json(); });

export async function loadManifest() {
  const manifest = await J('apps.json');
  let meta = null;
  try { meta = await J('data/_meta.json'); } catch { /* snapshot non ancora generato → card senza KPI */ }
  const surfaces = (meta && meta.surfaces) || {};
  const cards = manifest.apps.map(a => {
    const s = a.kpi_from ? surfaces[a.kpi_from] : null;
    return { ...a, semaforo: s ? s.semaforo : null, metric: cardMetric(a, s) };
  });
  return { cards, generated_at: meta ? meta.generated_at : null };
}

function cardMetric(app, surface) {
  if (app.kind === 'external') return app.icon ? 'Apri' : 'Apri';
  if (!surface) return '—';
  if (app.kpi_from === 'reviews') return surface.media_mese != null ? `${surface.media_mese}/10` : '—';
  if (app.kpi_from === 'fb') return surface.giorni != null ? `${surface.giorni} gg fa` : '—';
  return '—';
}
