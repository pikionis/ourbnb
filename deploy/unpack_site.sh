#!/usr/bin/env bash
# Unpack a tar of the public site's repository (on stdin) next to the folder Caddy serves.
#   unpack_site.sh <the served folder>
#
# It lands in <folder>.incoming; remote_up.sh swaps it in just before the new containers start, so a
# failed deploy leaves the running Caddy its folder. Only what visitors should see: on the web
# hosting Apache hid .htaccess and README.md, and PHP ran api/lead.php. Caddy would hand all of them
# out as plain files, so they never get here (ADR 0021).
set -euo pipefail

target=${1:?usage: unpack_site.sh <target folder>}
incoming=$target.incoming

rm -rf "$incoming"
mkdir -p "$incoming"
tar -x -C "$incoming" \
  --exclude='.git*' \
  --exclude='.htaccess' \
  --exclude='README.md' \
  --exclude='api' \
  --exclude='*.php'

[[ -f $incoming/index.html ]] || {
  echo "the site has no index.html: keeping the current copy" >&2
  rm -rf "$incoming"
  exit 1
}

chmod -R a+rX "$incoming"
