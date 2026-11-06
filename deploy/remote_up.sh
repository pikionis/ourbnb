#!/usr/bin/env bash
# Build and start one environment from the code ship.sh has just put on the server (ADR 0022).
#   remote_up.sh <staging|production> <kospm commit> <site commit>
#
# The order matters: the database and its migrations first, then the new site folder and the new
# containers. A failure before that step leaves what visitors see as it was.
set -euo pipefail

environment=${1:?usage: remote_up.sh <staging|production> <kospm commit> <site commit>}
kospm_commit=${2:-unknown}
site_commit=${3:-unknown}

deploy_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=${KOSPM_ROOT:-/srv/kospm}/$environment
dc() { bash "$deploy_dir/dc.sh" "$environment" "$@"; }
manage() { dc run --rm --no-deps backend python manage.py "$@"; }
say() { printf '\n== %s\n' "$*"; }

[[ -f $root/.env ]] || {
  echo "$root/.env is missing: run deploy/setup_host.sh first" >&2
  exit 1
}
[[ -d $root/site || -d $root/site.incoming ]] || {
  echo "the public site is missing: deploy with deploy/ship.sh" >&2
  exit 1
}
# Production's mail settings are filled in by hand, on the server (docs/RUNBOOK.md).
if grep -q 'CHANGE_ME' "$root/.env"; then
  echo "$root/.env still has CHANGE_ME values:" >&2
  grep -n 'CHANGE_ME' "$root/.env" | cut -d= -f1 >&2
  exit 1
fi

say "Building $kospm_commit"
dc build backend

say "Database"
dc up --detach --wait postgres
manage check --deploy --fail-level ERROR
manage migrate --noinput
manage createcachetable

say "Static files"
manage collectstatic --noinput --clear --verbosity 0

say "Starting the new containers"
# The running Caddy has the current folder mounted. If .previous is still here, the last deploy
# failed after its swap and that older folder may be the mounted one, so it stays until a deploy
# has succeeded. Nothing before this point touches what visitors see.
site=$root/site
if [[ -d $site.incoming ]]; then
  if [[ -d $site.previous ]]; then
    rm -rf "$site"
  elif [[ -d $site ]]; then
    mv "$site" "$site.previous"
  fi
  mv "$site.incoming" "$site"
fi
# --force-recreate: the bind mounts point at folders that this deploy has just replaced.
dc up --detach --wait --force-recreate --remove-orphans backend scheduler caddy
rm -rf "$site.previous"

say "Checking through Caddy"
domain=$(grep -E '^KOSPM_DOMAIN=' "$root/.env" | cut -d= -f2)
port=$(grep -E '^KOSPM_HTTP_PORT=' "$root/.env" | cut -d= -f2)
for path in /healthz / /admin/login/; do
  status=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 \
    -H "Host: $domain" -H 'X-Real-IP: 127.0.0.1' "http://127.0.0.1:$port$path")
  echo "  $path -> $status"
  [[ $status == 200 ]] || {
    echo "$path answered $status: look at: deploy/dc.sh $environment logs --tail 50" >&2
    exit 1
  }
done

printf '%s kospm=%s site=%s\n' "$(date -u +%FT%TZ)" "$kospm_commit" "$site_commit" >>"$root/deploys.log"
docker image prune --force --filter "until=168h" >/dev/null

say "$environment runs kospm $kospm_commit and site $site_commit"
