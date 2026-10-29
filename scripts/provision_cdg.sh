#!/usr/bin/env bash
# Provisioning Cloudflare per l'edge app CdG (cdg.panorama-host.com).
# NON lo esegue un agente: STAMPA i comandi che Stefano lancia uno alla volta con `!`.
# Il token esce da 1Password in pipe e non va mai a video. Ogni passo è una riga.
set -euo pipefail

OP_ITEM="aj7ieimu2jdwzfp6qzyw2migxq"   # Cloudflare API token (vault work)
TEAM="panoramagroup"
POLICY_NOMINATIVA="29a16983-8bb2-4104-bb0e-653dae8ef650"   # «Canone — nominativa»
DOMINIO="cdg.panorama-host.com"
WORKER_DIR="/Users/stefanodellapietra/dev/Projects/panorama_apps/cdg"

tok='op item get '"$OP_ITEM"' --vault work --fields password --reveal'

cat <<TXT
# ── CdG: provisioning, 5 passi. Ogni riga si lancia a mano con "!" dal terminale. ──
# Prerequisiti: cf CLI autenticato, op CLI sbloccato, $WORKER_DIR presente (copia da
# ~/.local/share/hotelops/cdg-cassa-handoff/panorama_apps_cdg su tong).

# 1. KV namespace del contenuto (annota l'id: va in wrangler.jsonc → <KV_ID> e in .env → CDG_KV_NAMESPACE_ID)
CLOUDFLARE_API_TOKEN=\$($tok) cf kv namespace create cdg-content

# 2. Scrivi l'id nel wrangler.jsonc del Worker (sostituisce <KV_ID>), poi deploy del Worker + custom domain
sed -i '' 's/<KV_ID>/IL_TUO_KV_ID/' $WORKER_DIR/wrangler.jsonc
(cd $WORKER_DIR && npm install && npm test && CLOUDFLARE_API_TOKEN=\$($tok) npx wrangler deploy)

# 3. App Access «CdG» sul dominio, con la policy nominativa già esistente (stessa di canone)
CLOUDFLARE_API_TOKEN=\$($tok) cf zero-trust access apps create --name "CdG" --domain "$DOMINIO" --type self_hosted --policies $POLICY_NOMINATIVA --session-duration 24h

# 4. Leggi l'AUD dell'app appena creata e scrivilo in wrangler.jsonc (<AUD>), poi ri-deploy
CLOUDFLARE_API_TOKEN=\$($tok) cf zero-trust access apps list --name "CdG" --fields id,aud,domain
sed -i '' 's/<AUD>/IL_TUO_AUD/' $WORKER_DIR/wrangler.jsonc
(cd $WORKER_DIR && CLOUDFLARE_API_TOKEN=\$($tok) npx wrangler deploy)

# 5. In hotelops: .env → CDG_KV_NAMESPACE_ID=IL_TUO_KV_ID, poi il primo push della pagina
#    (da una macchina con il .env: il Mac). Senza KV pieno il Worker risponde 503.
hotelops cdg cassa --push
# Verifica: aprire https://$DOMINIO da un browser con un'identità della policy → OTP → pagina Cassa.
TXT
