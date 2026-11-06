#!/usr/bin/env bash
# What KosPM needs to know about the shared VPS. READ-ONLY: it changes nothing and prints no secrets
# (no file contents of the other applications, no keys, no .env values).
#
# From your computer; not even this script is written to the server:
#   ssh root@VPS 'bash -s' < deploy/survey.sh > survey.txt
set -uo pipefail
shopt -s nullglob

[[ $EUID -eq 0 ]] || {
  echo "run as root (it only reads)" >&2
  exit 1
}

h() { printf '\n## %s\n' "$*"; }
run() { "$@" 2>&1 | sed 's/^/  /'; }

main() {
  h "System"
  # shellcheck source=/dev/null
  . /etc/os-release
  echo "  $PRETTY_NAME, $(uname -m), kernel $(uname -r), $(nproc) vCPU, $(awk '/^MemTotal:/ { printf "%.1f GB RAM", $2 / 1048576 }' /proc/meminfo)"
  run df -h / /srv /var
  run free -h
  run uptime

  h "Network and DNS"
  run ip -o addr show scope global
  for name in staging.ourbnb.gr ourbnb.gr www.ourbnb.gr; do
    echo "  $name resolves to: $(getent ahosts "$name" | awk '{ print $1 }' | sort -u | paste -sd' ' -)"
  done

  h "Listening TCP ports (address, process)"
  ss -ltnpH | awk '{ match($0, /users:\(\("[^"]*"/); print "  " $4 "  " substr($0, RSTART + 9, RLENGTH - 10) }' | sort -u
  for port in 8210 8211; do
    echo "  port $port for KosPM: $(ss -ltnH "sport = :$port" | grep -q . && echo TAKEN || echo free)"
  done

  h "nginx"
  echo "  version: $(nginx -v 2>&1 | sed 's/.*nginx\///'), active: $(systemctl is-active nginx)"
  echo "  nginx -t: $(nginx -t 2>&1 | tail -n 1)"
  echo "  includes: $(grep -Eo '^[[:space:]]*include[[:space:]]+[^;]+' /etc/nginx/nginx.conf | awk '{ print $2 }' | paste -sd' ' -)"
  for f in /etc/nginx/sites-enabled/* /etc/nginx/conf.d/*.conf; do
    echo "  $f"
    grep -Eh '^[[:space:]]*(listen|server_name)[[:space:]]' "$f" | sed 's/^[[:space:]]*/      /' | sort -u
  done

  h "The other applications answer (status only)"
  for host in feedgenix.com feed-intel.site; do
    echo "  $host: $(curl -s -k -o /dev/null -w '%{http_code}' --max-time 15 --resolve "$host:443:127.0.0.1" "https://$host/")"
  done

  h "Docker"
  if command -v docker >/dev/null; then
    echo "  $(docker --version)"
    echo "  $(docker compose version 2>&1 | head -n 1)"
    echo "  $(docker buildx version 2>&1 | head -n 1)"
    echo "  service: $(systemctl is-active docker)"
    docker ps --format '  container: {{.Names}} ({{.Image}}), ports {{.Ports}}'
  else
    echo "  not installed"
  fi

  h "apt: what installing Docker would do (a simulation; [old] = upgrade, Remv = removal)"
  for package in docker.io docker-compose-v2 docker-buildx; do
    echo "  $package candidate: $(apt-cache policy "$package" 2>/dev/null | awk '/Candidate:/ { print $2 }')"
  done
  apt-get -s install --no-install-recommends docker.io docker-compose-v2 docker-buildx 2>&1 |
    grep -E '^(Inst|Remv|Conf|E:)' | sed 's/^/  /'

  h "dpkg: unfinished packages (the next apt run re-runs their maintainer scripts)"
  unfinished=$(dpkg-query -W -f='${Package} ${Status}\n' 2>/dev/null |
    awk '$3 != "ok" || ($4 != "installed" && $4 != "not-installed" && $4 != "config-files") { print $1 }' | sort -u)
  echo "  ${unfinished:-none}" | paste -sd' ' -
  echo "  /tmp/cloudpanel exists: $([[ -e /tmp/cloudpanel ]] && echo YES || echo no)"
  echo "  policy-rc.d exists: $([[ -e /usr/sbin/policy-rc.d ]] && echo YES || echo no)"

  h "Certificates (names and expiry only)"
  if command -v certbot >/dev/null; then
    certbot certificates 2>/dev/null | grep -E 'Certificate Name|Domains|Expiry' | sed 's/^ */  /'
    echo "  certbot accounts: $(ls /etc/letsencrypt/accounts/*/directory/ 2>/dev/null | wc -l), timer: $(systemctl is-enabled certbot.timer 2>/dev/null)"
  else
    echo "  certbot is not installed"
  fi

  h "Firewall"
  if command -v ufw >/dev/null; then ufw status 2>&1 | head -n 12 | sed 's/^/  /'; else echo "  no ufw"; fi
  echo "  FORWARD policy: $(iptables -S FORWARD 2>/dev/null | head -n 1)"

  h "KosPM"
  if [[ -d /srv/kospm ]]; then ls -la /srv/kospm | sed 's/^/  /'; else echo "  not set up yet"; fi

  echo
  echo "Survey done: nothing was changed."
}

# stdin is the script itself: nothing main runs may read it.
main </dev/null
