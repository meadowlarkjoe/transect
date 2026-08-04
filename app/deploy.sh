#!/bin/bash
# Deploy Transect under the /transect/ path prefix on Cloudflare Pages.
#
# Everything here is staged into <tmp>/transect/ so the site mounts at
# https://transect.joejmeadows.com/transect/ and the domain ROOT stays free for other
# content. All internal links in the HTML are RELATIVE, so the same source also works
# if you mount it elsewhere — nothing hard-codes the prefix.
#
# CACHING: Cloudflare Pages IGNORES Cache-Control in _headers for static ASSETS — it
# serves them max-age=14400 and revalidates by etag no matter what you write there.
# Only HTML honours no-cache. So freshness comes from the ?v= query on asset URLs, and
# this script stamps that automatically from a content hash: change a file, get a new
# URL. No stale JS/CSS, and no version number to remember to bump.
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
D="$(mktemp -d)/tdeploy"
mkdir -p "$D/transect"
rsync -a --exclude '_headers' --exclude '.git' --exclude 'deploy.sh' "$SRC/" "$D/transect/"

python3 - "$D" <<'PY'
import hashlib, os, re, sys
d = sys.argv[1]
stage = os.path.join(d, 'transect')

# One version stamp per deploy, derived from the content that actually ships.
h = hashlib.sha1()
for f in ('app.js', 'style.css', 'data.js', 'area_detail.js', 'public.css'):
    p = os.path.join(stage, f)
    if os.path.exists(p):
        h.update(open(p, 'rb').read())
ver = h.hexdigest()[:8]

# Rewrite every ?v=… in the STAGED html (the source tree is left untouched).
stamped = []
for f in sorted(os.listdir(stage)):
    if not f.endswith('.html'):
        continue
    p = os.path.join(stage, f)
    s = open(p).read()
    n = re.sub(r'\?v=[A-Za-z0-9]+', '?v=' + ver, s)
    if n != s:
        open(p, 'w').write(n)
        stamped.append(f)
print(f"asset version {ver} -> {', '.join(stamped) or '(no html referenced assets)'}")

# HTML is the only thing Pages lets us mark no-cache; assets rely on the stamp above.
paths = ['/transect/', '/transect/app', '/transect/app.html', '/transect/plans',
         '/transect/plans.html', '/transect/signin', '/transect/signin.html',
         '/transect/index.html']
open(os.path.join(d, '_headers'), 'w').write(
    ''.join(f"{p}\n  Cache-Control: no-cache\n" for p in paths))
PY

export CLOUDFLARE_API_TOKEN=$(cat ~/.cf_token)
export CLOUDFLARE_ACCOUNT_ID=$(curl -s -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  "https://api.cloudflare.com/client/v4/zones?name=joejmeadows.com" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"][0]["account"]["id"])')
cd "$D" && npx wrangler pages deploy . --project-name transect --commit-dirty=true
