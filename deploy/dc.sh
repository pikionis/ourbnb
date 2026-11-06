#!/usr/bin/env bash
# docker compose for one environment, on the server:
#   dc.sh <staging|production> ps
#   dc.sh staging logs --tail 50 scheduler
#   dc.sh staging run --rm backend python manage.py createsuperuser
#
# KOSPM_ROOT moves the whole tree (the smoke test in CI); the default is the server's.
set -euo pipefail

if [[ $# -lt 2 || ! $1 =~ ^(staging|production)$ ]]; then
  echo "usage: dc.sh <staging|production> <docker compose arguments>" >&2
  exit 2
fi

environment=$1
shift
root=${KOSPM_ROOT:-/srv/kospm}/$environment

exec docker compose \
  --project-name "kospm-$environment" \
  --project-directory "$root/app/deploy" \
  --env-file "$root/.env" \
  --file "$root/app/deploy/docker-compose.prod.yml" \
  "$@"
