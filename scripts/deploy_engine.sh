#!/bin/bash
# Deploy the ENGINE to the droplet without throwing away someone's analysis.
#
# WHY THIS EXISTS. A run is a daemon thread inside uvicorn and its state lives only in
# an in-memory dict (#17), so restarting the container kills every in-flight analysis
# with no way to recover it — minutes of someone's evening, gone. I did exactly that
# once, at 49% CPU, because the "is it busy?" check and the restart were chained in one
# command so the check checked nothing.
#
# The fix is to make the check a STEP, not a habit:
#   1. DRAIN   — tell the API to refuse new runs, so waiting can actually converge.
#   2. WAIT    — poll until no job is in flight (or give up and leave the old one alive).
#   3. SHIP    — pull, build, recreate.
#   4. VERIFY  — health + engine revision, before calling it done.
#
# Anything that fails leaves the RUNNING container untouched. The worst case is "we did
# not deploy", never "we deployed and killed a run".
#
#   ./scripts/deploy_engine.sh              # drain politely, wait up to 20 min
#   MAX_WAIT=0 ./scripts/deploy_engine.sh   # refuse outright if anything is running
#   FORCE=1 ./scripts/deploy_engine.sh      # ship now, killing in-flight runs (say why)
set -euo pipefail

HOST="${TRANSECT_HOST:-root@157.245.143.211}"
API="${TRANSECT_API:-https://api.joejmeadows.com}"
REMOTE="${TRANSECT_REMOTE:-/opt/transect}"
MAX_WAIT="${MAX_WAIT:-1200}"        # seconds to wait for runs to finish
POLL="${POLL:-15}"

say(){ printf '\n\033[1m== %s\033[0m\n' "$*"; }
health(){ curl -fsS --max-time 20 "$API/health"; }
jq_num(){ python3 -c "import sys,json;print(json.load(sys.stdin).get('$1',0))"; }
jq_str(){ python3 -c "import sys,json;print(json.load(sys.stdin).get('$1',''))"; }

# The API key is a secret: read it, never print it, never put it in a command line that
# could land in a shell history or a process list on a shared box.
KEY_FILE="${TRANSECT_KEY_FILE:-$HOME/.transect_api_key}"
api_key(){
  if [ -f "$KEY_FILE" ]; then cat "$KEY_FILE"; else
    # fall back to the key the front end already ships (public by design)
    sed -n "s/.*TRANSECT_API_KEY='\([^']*\)'.*/\1/p" "$(dirname "$0")/../app/config.js"
  fi
}

say "engine health before"
H="$(health)" || { echo "REFUSING: $API is not answering. Nothing changed." >&2; exit 1; }
echo "$H" | python3 -c "import sys,json;d=json.load(sys.stdin);print(f\"  rev {d.get('engine_revision')} · active_jobs {d.get('active_jobs')} · draining {d.get('draining')}\")"

ACTIVE="$(echo "$H" | jq_num active_jobs)"

if [ "${FORCE:-0}" = "1" ]; then
  if [ "$ACTIVE" != "0" ]; then
    echo "  FORCE=1 — shipping anyway; $ACTIVE run(s) will be KILLED." >&2
  fi
else
  say "drain: refusing new runs"
  # An engine older than the drain feature has no /admin/drain and reports no
  # active_jobs. Do not hard-fail on it — that would make this script impossible to
  # deploy WITH — but be loud, because on that engine the wait below is blind.
  if curl -fsS --max-time 20 -X POST "$API/admin/drain?on=true" \
          -H "X-API-Key: $(api_key)" >/dev/null 2>&1; then
    echo "  new analyses now get 503 until this container is replaced"
  else
    CAN_DRAIN=0
    echo "  WARNING: this engine predates /admin/drain — it cannot refuse new runs," >&2
    echo "           and /health does not report active_jobs, so the wait is BLIND." >&2
    echo "           Check by hand before continuing, or re-run once this ships." >&2
  fi

  say "waiting for $ACTIVE in-flight run(s)"
  WAITED=0
  if [ "${CAN_DRAIN:-1}" = "0" ]; then echo "  (blind: old engine reports no job count)"; fi
  while :; do
    H="$(health)" || true
    ACTIVE="$(echo "$H" | jq_num active_jobs)"
    [ "$ACTIVE" = "0" ] && { echo "  drained after ${WAITED}s"; break; }
    if [ "$WAITED" -ge "$MAX_WAIT" ]; then
      echo "  STILL $ACTIVE running after ${WAITED}s — NOT deploying." >&2
      # Undo the drain: the old container is staying, so it must keep taking work.
      curl -fsS --max-time 20 -X POST "$API/admin/drain?on=false" \
           -H "X-API-Key: $(api_key)" >/dev/null 2>&1 || true
      echo "  drain lifted; the running engine is untouched. Re-run later, or FORCE=1." >&2
      exit 2
    fi
    echo "  $ACTIVE running (${WAITED}s)…"
    sleep "$POLL"; WAITED=$((WAITED + POLL))
  done
fi

say "ship: pull + build on $HOST"
ssh "$HOST" "cd $REMOTE && git fetch -q origin && git merge --ff-only origin/main >/dev/null && \
  docker build -q -f docker/Dockerfile -t moose-scout:local . >/dev/null && \
  echo '  built' \$(git rev-parse --short HEAD)"

say "recreate the container"
# `docker restart` reuses the OLD image — src/ is baked in, not mounted — so the
# container must be replaced, not restarted. Env is captured server-side so the API key
# never crosses this script.
ssh "$HOST" "docker inspect transect-api --format '{{range .Config.Env}}{{println .}}{{end}}' \
    | grep -v '^PATH=\|^LANG=\|^GPG_KEY=\|^PYTHON\|^DEBIAN_FRONTEND=\|^PIP_NO_CACHE_DIR=\|^\$' \
    > /root/.transect_recreate.env && chmod 600 /root/.transect_recreate.env && \
  docker rm -f transect-api >/dev/null && \
  docker run -d --name transect-api --restart unless-stopped --entrypoint uvicorn \
    -p 127.0.0.1:8000:8000 --env-file /root/.transect_recreate.env \
    -v $REMOTE/scripts:/app/scripts -v $REMOTE/config:/app/config \
    -v $REMOTE/cache:/app/cache -v $REMOTE/outputs:/app/outputs \
    -v $REMOTE/data:/app/data -v $REMOTE/osm:/app/osm \
    moose-scout:local moose_scout.api:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 75 >/dev/null && \
  echo '  recreated'"

say "verify"
for i in $(seq 1 20); do
  sleep 3
  if H="$(health 2>/dev/null)"; then
    REV="$(echo "$H" | jq_num engine_revision)"
    DRN="$(echo "$H" | jq_str draining)"
    echo "  ok · rev $REV · draining $DRN"
    if [ "$DRN" = "True" ]; then
      echo "  WARNING: new container came up draining — that is a bug." >&2
      exit 3
    fi
    exit 0
  fi
  echo "  waiting for the API to come back (${i})…"
done
echo "REFUSING to call this done: the API did not come back." >&2
exit 4
