#!/bin/bash
# Deploy Transect at the ROOT of transect.joejmeadows.com on Cloudflare Pages.
#
# It briefly lived under /transect/ to leave the domain root free — but the whole
# subdomain is Transect's, so the prefix was a level of nesting that bought nothing.
# All internal links in the HTML are RELATIVE, so the same source works mounted
# anywhere; only this staging step and the _headers paths know where it lands.
# /transect/* is 301'd to the root below so existing links and bookmarks survive.
#
# CACHING: Cloudflare Pages IGNORES Cache-Control in _headers for static ASSETS — it
# serves them max-age=14400 and revalidates by etag no matter what you write there.
# Only HTML honours no-cache. So freshness comes from the ?v= query on asset URLs, and
# this script stamps that automatically from a content hash: change a file, get a new
# URL. No stale JS/CSS, and no version number to remember to bump.
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
D="$(mktemp -d)/tdeploy"
mkdir -p "$D"
rsync -a --exclude '_headers' --exclude '_redirects' --exclude '.git' --exclude 'deploy.sh' "$SRC/" "$D/"

python3 - "$D" <<'PY'
import hashlib, os, re, sys
d = sys.argv[1]
stage = d

# One version stamp per deploy, derived from the content that actually ships.
h = hashlib.sha1()
for f in ('app.js', 'style.css', 'data.js', 'area_detail.js', 'public.css', 'i18n.js', 'icons.js'):
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
paths = ['/', '/app', '/app.html', '/plans', '/plans.html',
         '/signin', '/signin.html', '/index.html']
open(os.path.join(d, '_headers'), 'w').write(
    ''.join(f"{p}\n  Cache-Control: no-cache\n" for p in paths))

# Old /transect/* links keep working. Pages evaluates _redirects before serving
# assets, so this costs nothing on the normal path.
# The bare /transect/ needs its own rule: a splat rule with an empty splat does
# not reliably win against a same-path asset lookup, so name it explicitly.
open(os.path.join(d, '_redirects'), 'w').write(
    "/transect / 301\n"
    "/transect/ / 301\n"
    "/transect/index.html / 301\n"
    "/transect/* /:splat 301\n")
PY

export CLOUDFLARE_API_TOKEN=$(cat ~/.cf_token)
export CLOUDFLARE_ACCOUNT_ID=$(curl -s -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  "https://api.cloudflare.com/client/v4/zones?name=joejmeadows.com" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"][0]["account"]["id"])')
cd "$D" && npx wrangler pages deploy . --project-name transect --commit-dirty=true
