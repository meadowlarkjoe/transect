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

# NOTHING GOES LIVE THAT IS NOT IN THE REPO.
#
# This script used to be run from a working copy that was not under version control
# at all, so the live site ran ahead of git for a full day — 52 KB of app.js that
# existed nowhere but one directory and Cloudflare. If the box had died, so had the
# work. Deploy is now only legal from inside the repo, with a clean tree.
#
# ALLOW_DIRTY=1 escapes the check for a genuine emergency; it prints what it is
# shipping that git has never seen, so the escape is never silent.
if ! git -C "$SRC" rev-parse --git-dir >/dev/null 2>&1; then
  echo "REFUSING: $SRC is not inside a git repository." >&2
  echo "Deploy from the repo (moose-scout/app), not from a loose copy." >&2
  exit 1
fi
DIRTY="$(git -C "$SRC" status --porcelain -- "$SRC")"
if [ -n "$DIRTY" ]; then
  echo "REFUSING: uncommitted changes would go live without existing in git:" >&2
  echo "$DIRTY" >&2
  if [ "${ALLOW_DIRTY:-0}" != "1" ]; then
    echo "Commit them, or re-run with ALLOW_DIRTY=1 if this is an emergency." >&2
    exit 1
  fi
  echo "ALLOW_DIRTY=1 set — shipping anyway." >&2
fi
echo "deploying $(git -C "$SRC" rev-parse --short HEAD) from $(git -C "$SRC" rev-parse --abbrev-ref HEAD)"
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
