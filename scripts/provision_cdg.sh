#!/usr/bin/env bash
# Provisioning Cloudflare per l'edge app CdG (cdg.panorama-host.com).
# NON lo esegue un agente: STAMPA i comandi che Stefano lancia uno alla volta nel suo terminale.
# Eseguito con successo il 30/10/2026 (KV e692128a…, app Access «CdG», Worker deployato).
# cf e wrangler usano il login OAuth del Mac (`cf auth whoami`, `npx wrangler whoami`): il token di
# 1Password serve SOLO al push della pagina da hotelops (CLOUDFLARE_API_TOKEN nel .env).
set -euo pipefail

POLICY_NOMINATIVA="29a16983-8bb2-4104-bb0e-653dae8ef650"   # «Canone — nominativa» (riusabile)
DOMINIO="cdg.panorama-host.com"
WORKER_DIR="${WORKER_DIR:-$HOME/dev/Projects/panorama_apps/cdg}"   # sovrascrivibile: WORKER_DIR=… bash scripts/provision_cdg.sh

cat <<TXT
# ── CdG: provisioning, 5 passi. Righe corte, una alla volta, nel terminale (non via "!"). ──
# Prerequisiti: cf e wrangler autenticati (cf auth whoami), $WORKER_DIR presente,
# $WORKER_DIR/access-app.json = corpo dell'app Access (name CdG, domain $DOMINIO, type self_hosted,
# session_duration 24h, app_launcher_visible false, policies [$POLICY_NOMINATIVA]).

# 1. KV namespace del contenuto: annota l'id (va in wrangler.jsonc → <KV_ID> e nel .env → CDG_KV_NAMESPACE_ID)
cf kv namespaces create --title cdg-content

# 2. App Access «CdG» con la policy nominativa: annota il campo "aud"
cd $WORKER_DIR
cf zero-trust access applications create --body "\$(cat access-app.json)"
#    (per rileggere l'aud in seguito: cf zero-trust access applications list --name CdG --exact)

# 3. Scrivi KV id e aud nel wrangler.jsonc (segnaposto <KV_ID> e <AUD>), poi test e deploy
sed -i '' 's/<KV_ID>/IL_TUO_KV_ID/; s/<AUD>/IL_TUO_AUD/' wrangler.jsonc
npm install && npm test
npx wrangler deploy

# 4. In hotelops: .env → CDG_KV_NAMESPACE_ID=IL_TUO_KV_ID, poi il primo push della pagina
#    (dal clone che ha il .env). Senza KV pieno il Worker risponde 503.
hotelops cdg cassa --push

# 5. Verifica: curl -sI https://$DOMINIO/ → 302 verso panoramagroup.cloudflareaccess.com;
#    da un browser con un'identità della policy → OTP → pagina Cassa.
TXT
