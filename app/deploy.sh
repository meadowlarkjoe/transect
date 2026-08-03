#!/bin/bash
# Deploy Transect under the /transect/ path prefix on Cloudflare Pages.
# Everything in this directory is staged into <tmp>/transect/ so the site mounts at
# https://transect.joejmeadows.com/transect/ and the domain ROOT stays free for other
# content. All internal links in the HTML are RELATIVE, so the same source also works
# if you ever mount it somewhere else — nothing hard-codes the prefix.
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
D="$(mktemp -d)/tdeploy"
mkdir -p "$D/transect"
rsync -a --exclude '_headers' --exclude '.git' --exclude 'deploy.sh' "$SRC/" "$D/transect/"
python3 - "$D" <<'PY'
import sys, os
d = sys.argv[1]
paths = ['/transect/', '/transect/app', '/transect/app.html', '/transect/plans',
         '/transect/plans.html', '/transect/signin', '/transect/signin.html',
         '/transect/index.html', '/transect/app.js', '/transect/data.js',
         '/transect/area_detail.js', '/transect/style.css', '/transect/public.css',
         '/transect/config.js', '/transect/preview.jpg']
open(os.path.join(d, '_headers'), 'w').write(
    ''.join(f"{p}\n  Cache-Control: no-cache\n" for p in paths))
PY
export CLOUDFLARE_API_TOKEN=$(cat ~/.cf_token)
export CLOUDFLARE_ACCOUNT_ID=$(curl -s -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  "https://api.cloudflare.com/client/v4/zones?name=joejmeadows.com" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"][0]["account"]["id"])')
cd "$D" && npx wrangler pages deploy . --project-name transect --commit-dirty=true
