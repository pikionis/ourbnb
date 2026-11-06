#!/usr/bin/env bash
# Put one commit on the server and start it, from your computer (ADR 0022).
#   deploy/ship.sh <staging|production> [commit, default HEAD]
#
# The code travels over SSH with `git archive`: the server holds no GitHub key and never pulls. To
# roll back, ship an older commit (migrations are additive). Set KOSPM_SSH to reach the server
# another way than root@69.62.116.163.
set -euo pipefail
export MSYS_NO_PATHCONV=1 # Git Bash on Windows: leave the server's paths alone

if [[ $# -lt 1 || ! $1 =~ ^(staging|production)$ ]]; then
  echo "usage: deploy/ship.sh <staging|production> [commit]" >&2
  exit 2
fi

environment=$1
ref=${2:-HEAD}
server=${KOSPM_SSH:-root@69.62.116.163}
root=/srv/kospm/$environment

cd "$(git rev-parse --show-toplevel)"
kospm_commit=$(git rev-parse --short "$ref")

if [[ $environment == production ]]; then
  # Production gets only what is committed and already backed up on GitHub.
  git fetch --quiet origin kospm
  git merge-base --is-ancestor "$ref" origin/kospm || {
    echo "$kospm_commit is not on origin/kospm: push it first" >&2
    exit 1
  }
elif [[ -n $(git status --porcelain) ]]; then
  echo "note: uncommitted changes stay here; shipping the commit $kospm_commit"
fi

# The public site lives in main, Hostinger's branch until the switch (ADR 0021). Read only.
git fetch --quiet origin main
site_commit=$(git rev-parse --short origin/main)

echo "== Sending KosPM $kospm_commit to $server"
ssh "$server" "test -f $root/.env" || {
  echo "$root/.env is missing on the server: run deploy/setup_host.sh first" >&2
  exit 1
}
git archive --format=tar "$ref" backend deploy | ssh "$server" "
  set -e
  rm -rf $root/app.incoming
  mkdir -p $root/app.incoming
  tar -x -C $root/app.incoming
  rm -rf $root/app
  mv $root/app.incoming $root/app
"

echo "== Sending the public site $site_commit"
git archive --format=tar origin/main | ssh "$server" "bash $root/app/deploy/unpack_site.sh $root/site"

# shellcheck disable=SC2029 # expanded here on purpose: these name the commits being shipped
ssh "$server" "bash $root/app/deploy/remote_up.sh $environment $kospm_commit $site_commit"
