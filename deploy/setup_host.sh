#!/usr/bin/env bash
# Prepare the shared VPS for one KosPM environment (ADR 0022): Docker, the folders, the secrets and
# one nginx vhost with its certificate. It is safe to run again.
#
# This host also runs FeedGenix and a frozen legacy app, behind CloudPanel's nginx. Every run here
# needs the owner's go-ahead. It starts with --dry-run, from your computer:
#   ssh root@VPS 'bash -s -- staging --dry-run' < deploy/setup_host.sh
#   ssh root@VPS 'bash -s -- staging --allow-unfinished=cloudpanel' < deploy/setup_host.sh
#
# What it never does: restart a service of another application, edit another vhost, or edit the
# firewall or SSH settings. Installing Docker follows the guards of FeedGenix's provisioning on this
# host: apt starts no service while it runs, and it stops if apt would upgrade or remove anything.
# Docker itself, once started, adds its own iptables chains, normally sets the FORWARD policy to DROP
# and turns on ip_forward. Nothing here forwards today (the survey shows it), and KosPM's containers
# publish only one port, on localhost.
#
# Options:
#   --dry-run               print what would change, change nothing
#   --skip-vhost            everything but nginx and the certificate: before DNS points here
#   --allow-unfinished=A,B  packages dpkg left half-configured, after reading their scripts
#   --allow-upgrades        let apt upgrade installed packages, after reading the list
#   --print-env             print a new .env for this environment, change nothing (the smoke test)
#   --print-vhost=http|tls  print the nginx vhost, change nothing (the smoke test)
set -euo pipefail
shopt -s nullglob

ACME_ROOT=/var/lib/kospm-acme
DOCKER_PACKAGES=(docker.io docker-compose-v2 docker-buildx)
# The sites that must keep answering after any change here.
OTHER_SITES=(feedgenix.com feed-intel.site)

die() {
  printf 'STOP: %s\n' "$*" >&2
  exit 1
}
say() { printf '\n== %s\n' "$*"; }
note() { printf '   %s\n' "$*"; }

[[ $# -ge 1 && $1 =~ ^(staging|production)$ ]] || die "usage: setup_host.sh <staging|production> [options]"
environment=$1
shift

DRY_RUN=0 SKIP_VHOST=0 ALLOW_UPGRADES=0 ALLOW_UNFINISHED='' PRINT_ENV=0 PRINT_VHOST=''
for arg in "$@"; do
  case $arg in
    --dry-run) DRY_RUN=1 ;;
    --skip-vhost) SKIP_VHOST=1 ;;
    --allow-upgrades) ALLOW_UPGRADES=1 ;;
    --allow-unfinished=*) ALLOW_UNFINISHED=${arg#*=} ;;
    --print-env) PRINT_ENV=1 ;;
    --print-vhost=http | --print-vhost=tls) PRINT_VHOST=${arg#*=} ;;
    *) die "unknown option: $arg" ;;
  esac
done

case $environment in
  staging)
    DOMAIN=staging.ourbnb.gr
    REDIRECT_HOSTS=''
    PORT=8211
    ;;
  production)
    DOMAIN=ourbnb.gr
    REDIRECT_HOSTS=www.ourbnb.gr
    PORT=8210
    ;;
esac
ALL_HOSTS="$DOMAIN${REDIRECT_HOSTS:+ $REDIRECT_HOSTS}"
ENV_ROOT=${KOSPM_ROOT:-/srv/kospm}/$environment
CERT_DIR=/etc/letsencrypt/live/$DOMAIN

# --- the environment's secrets -----------------------------------------------------------------

print_env() {
  cat <<EOF
# KosPM $environment. Written once by deploy/setup_host.sh. Secrets: stays on this server, mode 600.
KOSPM_ENV=$environment
KOSPM_DOMAIN=$DOMAIN
KOSPM_HTTP_PORT=$PORT

DJANGO_SECRET_KEY=$(openssl rand -hex 48)
FERNET_KEYS=$(openssl rand -base64 32 | tr '+/' '-_')
DJANGO_ALLOWED_HOSTS=$DOMAIN
DJANGO_CSRF_TRUSTED_ORIGINS=https://$DOMAIN
PORTAL_BASE_URL=https://$DOMAIN
PORTAL_NAME=OurBnb
DEFAULT_FROM_EMAIL="OurBnb <no-reply@ourbnb.gr>"

POSTGRES_USER=kospm
POSTGRES_PASSWORD=$(openssl rand -hex 24)
POSTGRES_DB=kospm

# WhatsApp arrives in Phase 6; until then its messages go to the scheduler's log.
OUTBOX_SENDER=console
# Without a key the owner fills in the profile by hand.
# ANTHROPIC_API_KEY=
EOF
  if [[ $environment == staging ]]; then
    cat <<EOF

# Staging sends no email to anyone: messages go to the scheduler's log.
EMAIL_URL=consolemail://
LEAD_NOTIFY_EMAIL=leads@staging.invalid
EOF
  else
    cat <<EOF

# Fill these in by hand, on this server, before the first deploy (docs/RUNBOOK.md).
# smtp+tls://no-reply%40ourbnb.gr:PASSWORD@smtp.hostinger.com:587 (the password percent-encoded)
EMAIL_URL=CHANGE_ME
# Where the requests for an estimate from the site's form go.
LEAD_NOTIFY_EMAIL=CHANGE_ME
EOF
  fi
}

# --- the nginx vhost ---------------------------------------------------------------------------

nginx_version() { nginx -v 2>&1 | sed 's/.*nginx\///; s/ .*//'; }

render_vhost() { # http|tls
  local kind=$1 http2_listen='' http2_directive='http2 on;' ipv6_80='' ipv6_443=''
  if command -v nginx >/dev/null && ! dpkg --compare-versions "$(nginx_version)" ge 1.25.1; then
    http2_listen=' http2'
    http2_directive=''
  fi
  if [[ -n $(ip -6 -o addr show scope global 2>/dev/null) ]]; then
    ipv6_80='listen [::]:80;'
    ipv6_443="listen [::]:443 ssl$http2_listen;"
  fi

  cat <<EOF
# KosPM $environment. Written by deploy/setup_host.sh; edits here are overwritten.
# TLS ends here. Caddy in the KosPM stack routes by path, on a localhost port (ADR 0021, 0022).
server {
    listen 80;
    $ipv6_80
    server_name $ALL_HOSTS;

    location ^~ /.well-known/acme-challenge/ {
        root $ACME_ROOT;
        default_type text/plain;
    }

    location / {
        return 301 https://$DOMAIN\$request_uri;
    }
}
EOF
  [[ $kind == tls ]] || return 0

  cat <<EOF

server {
    listen 443 ssl$http2_listen;
    $ipv6_443
    $http2_directive
    server_name $DOMAIN;

    ssl_certificate $CERT_DIR/fullchain.pem;
    ssl_certificate_key $CERT_DIR/privkey.pem;
    server_tokens off;

    # Above PORTAL_UPLOAD_MAX_MB; the same limit as the Caddyfile.
    client_max_body_size 64m;

    # No access log: the paths of signed links carry their tokens (ADR 0021).
    access_log off;
    error_log /var/log/nginx/kospm-$environment.error.log warn;

    # One day until HTTPS has proven itself; raised in Phase 7.
    add_header Strict-Transport-Security "max-age=86400" always;

    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        # Longer than gunicorn's timeout (Dockerfile.prod).
        proxy_read_timeout 180s;
        proxy_send_timeout 180s;
        proxy_hide_header Strict-Transport-Security;
    }
}
EOF
  if [[ -n $REDIRECT_HOSTS ]]; then
    cat <<EOF

server {
    listen 443 ssl$http2_listen;
    $ipv6_443
    $http2_directive
    server_name $REDIRECT_HOSTS;

    ssl_certificate $CERT_DIR/fullchain.pem;
    ssl_certificate_key $CERT_DIR/privkey.pem;
    server_tokens off;
    access_log off;

    location / {
        return 301 https://$DOMAIN\$request_uri;
    }
}
EOF
  fi
}

if ((PRINT_ENV)); then
  print_env
  exit 0
fi
if [[ -n $PRINT_VHOST ]]; then
  render_vhost "$PRINT_VHOST"
  exit 0
fi

# --- everything below changes the host ----------------------------------------------------------

[[ $EUID -eq 0 ]] || die "run as root"
changing() { # a description; true when the change should really be made
  if ((DRY_RUN)); then note "would: $*"; else note "$*"; fi
  ((!DRY_RUN))
}

declare -A OTHERS_BEFORE=()
status_of() { curl -s -k -o /dev/null -w '%{http_code}' --max-time 15 --resolve "$1:443:127.0.0.1" "https://$1/" || true; }
record_others() {
  local site
  for site in "${OTHER_SITES[@]}"; do
    OTHERS_BEFORE[$site]=$(status_of "$site")
    note "$site answers ${OTHERS_BEFORE[$site]}"
  done
}
others_still_answer() {
  local site now answered=0
  for site in "${OTHER_SITES[@]}"; do
    now=$(status_of "$site")
    if [[ ${OTHERS_BEFORE[$site]} =~ ^[1-4] && ! $now =~ ^[1-4] ]]; then
      printf 'STOP: %s answered %s before and %s now\n' "$site" "${OTHERS_BEFORE[$site]}" "$now" >&2
      answered=1
    fi
  done
  return "$answered"
}

# --- Docker -------------------------------------------------------------------------------------

unfinished_packages() {
  dpkg-query -W -f='${Package} ${Status}\n' 2>/dev/null |
    awk '$3 != "ok" || ($4 != "installed" && $4 != "not-installed" && $4 != "config-files") { print $1 }' |
    sort -u
}
not_allowed() {
  awk -v allowed="$ALLOW_UNFINISHED" 'BEGIN { n = split(allowed, a, ","); for (i = 1; i <= n; i++) ok[a[i]] = 1 }
    NF && !($1 in ok) { print $1 }'
}
apt_run() {
  DEBIAN_FRONTEND=noninteractive NEEDRESTART_SUSPEND=1 apt-get -q -y -o DPkg::Lock::Timeout=300 \
    -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold "$@"
}
# What an install would do to packages that are already there, from apt's own simulation.
disruptions() {
  local simulation
  simulation=$(apt-get -s install --no-install-recommends "${DOCKER_PACKAGES[@]}" 2>&1) || {
    printf '%s\n' "$simulation" | tail -n 20 >&2
    die "apt cannot install ${DOCKER_PACKAGES[*]}"
  }
  awk '/^Inst [^ ]+ \[/ { print "upgrade " $2 } /^Remv / { print "remove " $2 }' <<<"$simulation"
}
check_disruptions() {
  local found
  found=$(disruptions)
  [[ -n $found ]] || return 0
  printf '   apt would also:\n'
  sed 's/^/             /' <<<"$found"
  ! grep -q '^remove ' <<<"$found" || die "apt would REMOVE installed packages; nothing was changed"
  ((ALLOW_UPGRADES)) || die "apt would UPGRADE installed packages; read the list, then add --allow-upgrades"
}
remove_policy() { rm -f /usr/sbin/policy-rc.d; }

install_docker() {
  say "Docker"
  if command -v docker >/dev/null && docker compose version >/dev/null 2>&1 &&
    docker buildx version >/dev/null 2>&1; then
    note "already installed: $(docker --version)"
    return 0
  fi

  [[ ! -e /tmp/cloudpanel ]] ||
    die "/tmp/cloudpanel exists: the next apt run would stop and restart CloudPanel's services"
  [[ ! -e /usr/sbin/policy-rc.d ]] || die "/usr/sbin/policy-rc.d exists: another install is running?"

  local unfinished blockers
  unfinished=$(unfinished_packages | paste -sd, -)
  if [[ -n $unfinished ]]; then
    blockers=$(tr ',' '\n' <<<"$unfinished" | not_allowed | paste -sd, -)
    [[ -z $blockers ]] ||
      die "dpkg left these unfinished: $blockers. Any apt install re-runs their scripts. Read /var/lib/dpkg/info/PKG.postinst, then add --allow-unfinished=$unfinished. Nothing was installed."
    note "apt will re-run the scripts of $unfinished (allowed): their failure is tolerated, nothing else's"
  fi
  check_disruptions

  changing "install ${DOCKER_PACKAGES[*]} (apt starts and restarts no service)" || return 0

  # policy-rc.d exits 101: while apt runs, no package script may start or restart a service.
  printf '#!/bin/sh\n# Temporary (KosPM deploy/setup_host.sh).\nexit 101\n' >/usr/sbin/policy-rc.d
  chmod 0755 /usr/sbin/policy-rc.d
  trap remove_policy EXIT

  apt_run update >/dev/null
  check_disruptions # again, against the fresh lists
  if ! apt_run install --no-install-recommends "${DOCKER_PACKAGES[@]}"; then
    [[ -n $unfinished ]] || die "apt-get install failed"
    local package left
    for package in "${DOCKER_PACKAGES[@]}"; do
      [[ $(dpkg-query -W -f='${Status}' "$package" 2>/dev/null) == 'install ok installed' ]] ||
        die "apt-get install failed: $package is not installed"
    done
    left=$(unfinished_packages | not_allowed | paste -sd' ' -)
    [[ -z $left ]] || die "apt-get install left packages unfinished: $left"
    note "apt reported the allowed package failing again; every Docker package is installed"
  fi
  remove_policy
  trap - EXIT

  systemctl enable --now --quiet containerd docker
  note "$(docker --version), service $(systemctl is-active docker)"
  others_still_answer || die "another site stopped answering after the Docker install: investigate before going on"
}

# --- folders and secrets ------------------------------------------------------------------------

setup_folders() {
  say "Folders and secrets in $ENV_ROOT"
  if [[ -f $ENV_ROOT/.env ]]; then
    note ".env already there: left as it is"
    return 0
  fi
  changing "create $ENV_ROOT and a new .env with fresh secrets (mode 600)" || return 0
  install -d -m 0750 "${ENV_ROOT%/*}" "$ENV_ROOT"
  (
    umask 077
    print_env >"$ENV_ROOT/.env"
  )
}

# --- nginx and the certificate ------------------------------------------------------------------

hosts_not_here() {
  local ours ours6 host found found6
  ours=$(ip -4 -o addr show scope global 2>/dev/null | awk '{ split($4, a, "/"); print a[1] }' | sort -u)
  ours6=$(ip -6 -o addr show scope global 2>/dev/null | awk '{ split($4, a, "/"); print a[1] }' | sort -u)
  for host in $ALL_HOSTS; do
    found=$({ getent ahostsv4 "$host" 2>/dev/null || true; } | awk '{ print $1 }' | sort -u)
    # Let's Encrypt prefers IPv6, so a parked AAAA record would fail the challenge.
    found6=$({ getent ahostsv6 "$host" 2>/dev/null || true; } | awk '$1 !~ /^::ffff:/ { print $1 }' | sort -u)
    if [[ -z $found || -n $(comm -23 <(printf '%s\n' "$found") <(printf '%s\n' "$ours")) ]] ||
      [[ -n $found6 && -n $(comm -23 <(printf '%s\n' "$found6") <(printf '%s\n' "$ours6")) ]]; then
      printf '%s\n' "$host"
    fi
  done
}

sites_layout() {
  if grep -Eq '^[[:space:]]*include[[:space:]]+/etc/nginx/sites-enabled/' /etc/nginx/nginx.conf; then
    echo sites-enabled
  elif grep -Eq '^[[:space:]]*include[[:space:]]+/etc/nginx/conf\.d/' /etc/nginx/nginx.conf; then
    echo conf.d
  else
    die "nginx.conf includes neither sites-enabled/ nor conf.d/: add the vhost by hand"
  fi
}

apply_vhost() { # http|tls. nginx -t, a graceful reload, then the other sites must still answer.
  local kind=$1 site link layout
  layout=$(sites_layout)
  if [[ $layout == sites-enabled ]]; then
    site=/etc/nginx/sites-available/kospm-$environment.conf
    link=/etc/nginx/sites-enabled/kospm-$environment.conf
  else
    site=/etc/nginx/conf.d/kospm-$environment.conf
    link=''
  fi

  local new
  new=$(render_vhost "$kind")
  if [[ -f $site && $(<"$site") == "$new" ]]; then
    note "vhost ($kind) is up to date"
    return 0
  fi
  changing "write $site ($kind), nginx -t, graceful reload" || return 0

  local had_previous=0 had_link=0
  if [[ -f $site ]]; then
    cp -p "$site" "$site.kospm-previous"
    had_previous=1
  fi
  if [[ -n $link && -e $link ]]; then had_link=1; fi
  revert() {
    if ((had_previous)); then
      mv -f "$site.kospm-previous" "$site"
    else
      rm -f "$site"
    fi
    if [[ -n $link ]] && ((!had_link)); then rm -f "$link"; fi
  }

  printf '%s\n' "$new" >"$site"
  if [[ -n $link ]]; then ln -sfn "$site" "$link"; fi

  local test_output
  if ! test_output=$(nginx -t 2>&1); then
    printf '%s\n' "$test_output" >&2
    revert
    die "nginx -t failed: KosPM's vhost was reverted and nginx was NOT reloaded"
  fi
  systemctl reload nginx
  sleep 2
  if ! others_still_answer; then
    revert
    nginx -t -q && systemctl reload nginx
    die "another site stopped answering after the reload: KosPM's vhost was reverted"
  fi
  rm -f "$site.kospm-previous"
  note "nginx reloaded; the other sites still answer"
}

setup_vhost_and_certificate() {
  say "nginx and the certificate for $ALL_HOSTS"
  command -v certbot >/dev/null || die "certbot is not installed"

  local not_here
  not_here=$(hosts_not_here | paste -sd' ' -)
  if [[ -n $not_here ]]; then
    if ((DRY_RUN)); then
      note "warning: $not_here does not point to this host yet"
    else
      die "$not_here does not point to this host yet. Add the DNS record, wait for it, and run this again."
    fi
  fi

  if ! ((DRY_RUN)); then install -d -m 0755 "$ACME_ROOT"; fi
  if [[ -f $CERT_DIR/fullchain.pem ]]; then
    apply_vhost tls
    return 0
  fi

  apply_vhost http
  changing "certbot certonly --webroot for $ALL_HOSTS (edits no nginx config)" || return 0
  local -a names=() account=()
  local host
  for host in $ALL_HOSTS; do names+=(-d "$host"); done
  local accounts=(/etc/letsencrypt/accounts/*/directory/*)
  if ((${#accounts[@]} == 0)); then account=(--register-unsafely-without-email); fi
  certbot certonly --webroot -w "$ACME_ROOT" --cert-name "$DOMAIN" "${names[@]}" --non-interactive \
    --agree-tos --keep-until-expiring "${account[@]}" --deploy-hook 'nginx -t -q && systemctl reload nginx'
  apply_vhost tls
}

# --- the run ------------------------------------------------------------------------------------

preflight() {
  command -v nginx >/dev/null || die "nginx is not installed"
  systemctl is-active --quiet nginx || die "nginx is not running: nothing was changed"
  nginx -t -q 2>/dev/null || die "nginx -t fails before any change here: nothing was changed"
  local taken
  taken=$(ss -ltnpH "sport = :$PORT" | grep -v docker || true)
  [[ -z $taken ]] || die "port $PORT is taken by another program: nothing was changed"
}

main() {
  say "KosPM $environment on $(hostname)$( ((DRY_RUN)) && echo ' (dry run: nothing changes)')"
  preflight
  record_others
  install_docker
  setup_folders
  if ((SKIP_VHOST)); then
    note "--skip-vhost: nginx and the certificate come after DNS points here"
  else
    setup_vhost_and_certificate
  fi

  if command -v feedgenix-check >/dev/null && ! ((DRY_RUN)); then
    say "FeedGenix's own check (read-only)"
    feedgenix-check 2>&1 | tail -n 5 || true
  fi

  say "Done$( ((DRY_RUN)) && echo ' (dry run)')"
  note "Next, from your computer: deploy/ship.sh $environment"
}

# The script arrives on stdin and bash reads it as it runs. With the whole script read before main
# starts, and stdin closed for what it runs, no apt script can eat the rest of it.
main </dev/null
