#!/usr/bin/env bash
# The whole production stack on a CI runner, as the server runs it (ADR 0022): the shipped files,
# remote_up.sh, the host's nginx in front of Caddy with a self-signed certificate, and then what a
# visitor does. It proves what unit tests cannot: the image, the routes, the headers, the proxy chain,
# the login behind two proxies, and the scheduler delivering an email.
#   deploy/tests/smoke.sh <checkout of the public site>
set -Eeuo pipefail

repo=$(git rev-parse --show-toplevel)
site_source=$(cd "${1:?usage: smoke.sh <checkout of the public site>}" && pwd)
work=$(mktemp -d)
export KOSPM_ROOT=$work/kospm
env_root=$KOSPM_ROOT/staging
domain=staging.ourbnb.gr
port=8211
failures=0

check() { # description, expected, actual
  if [[ $3 == *"$2"* ]]; then
    printf 'ok    %s\n' "$1"
  else
    printf 'FAIL  %s: expected %q, got %q\n' "$1" "$2" "$3"
    failures=$((failures + 1))
  fi
}
absent() { # description, unexpected, actual
  if [[ $3 == *"$2"* ]]; then
    printf 'FAIL  %s: %q should not be there: %q\n' "$1" "$2" "$3"
    failures=$((failures + 1))
  else
    printf 'ok    %s\n' "$1"
  fi
}
dc() { bash "$env_root/app/deploy/dc.sh" staging "$@"; }

# Through Caddy alone, with the headers nginx would set.
caddy_status() { curl -s -o /dev/null -w '%{http_code}' -H "Host: $domain" -H 'X-Real-IP: 203.0.113.1' "http://127.0.0.1:$port$1"; }
caddy_headers() { curl -s -o /dev/null -D - -H "Host: $domain" -H 'X-Real-IP: 203.0.113.1' "http://127.0.0.1:$port$1"; }
# Through nginx and Caddy, as a visitor.
visit() { curl -s -k --resolve "$domain:443:127.0.0.1" "$@"; }

show_logs() {
  dc logs --tail 60 || true
  docker logs --tail 30 kospm-smoke-nginx 2>/dev/null || true
}
trap 'echo "== stopped at line $LINENO; the logs:"; show_logs' ERR

echo "== Ship, as ship.sh does"
mkdir -p "$env_root/app"
git -C "$repo" archive --format=tar HEAD backend deploy | tar -x -C "$env_root/app"
git -C "$site_source" archive --format=tar HEAD | bash "$repo/deploy/unpack_site.sh" "$env_root/site"
bash "$repo/deploy/setup_host.sh" staging --print-env >"$env_root/.env"
chmod 600 "$env_root/.env"
bash "$env_root/app/deploy/remote_up.sh" staging "$(git -C "$repo" rev-parse --short HEAD)" site

echo "== Production's configuration parses too"
docker run --rm -e KOSPM_ENV=production -v "$repo/deploy/Caddyfile:/etc/caddy/Caddyfile:ro" \
  caddy:2.11.7-alpine caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

echo "== nginx in front, with a self-signed certificate"
cert_dir=$work/letsencrypt/live/$domain
mkdir -p "$cert_dir"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=$domain" \
  -addext "subjectAltName=DNS:$domain" -keyout "$cert_dir/privkey.pem" -out "$cert_dir/fullchain.pem" 2>/dev/null
chmod 644 "$cert_dir/privkey.pem"
bash "$repo/deploy/setup_host.sh" staging --print-vhost=tls >"$work/vhost.conf"
docker run --detach --name kospm-smoke-nginx --network host \
  -v "$work/vhost.conf:/etc/nginx/conf.d/default.conf:ro" \
  -v "$work/letsencrypt:/etc/letsencrypt:ro" \
  nginx:1.28 >/dev/null
sleep 2
if ! docker exec kospm-smoke-nginx nginx -t; then
  docker logs kospm-smoke-nginx
  exit 1
fi

echo "== Routes"
check "the site's home page" "200" "$(caddy_status /)"
check "the privacy page" "200" "$(caddy_status /aporrito.html)"
check "the site's assets" "200" "$(caddy_status /assets/css/styles.css)"
check "Django's static files" "200" "$(caddy_status /static/admin/css/base.css)"
check "the admin's login" "200" "$(caddy_status /admin/login/)"
check "the owners' login" "200" "$(caddy_status /owner/login/)"
check "the health check" "200" "$(caddy_status /healthz)"
check "a page that does not exist" "404" "$(caddy_status /no-such-page)"
check "/administrator belongs to the site, not to Django" "404" "$(caddy_status /administrator)"
for hidden in /.htaccess /README.md /.gitignore /.git/config /api/ /lead.php; do
  check "$hidden is not served" "404" "$(caddy_status "$hidden")"
done
absent "the 404 page is the site's" "Not Found" "$(curl -s -H "Host: $domain" -H 'X-Real-IP: 203.0.113.1' "http://127.0.0.1:$port/no-such-page" | head -c 2000)"

echo "== Headers"
home=$(caddy_headers /)
check "a policy on the site's pages" "content-security-policy: default-src 'self'" "${home,,}"
check "the site's own header" "x-frame-options: sameorigin" "${home,,}"
check "pages are not cached" "cache-control: no-cache" "${home,,}"
check "staging stays out of search engines" "x-robots-tag: noindex" "${home,,}"
check "assets are cached" "max-age=604800" "$(caddy_headers /assets/css/styles.css)"
check "fonts are cached longest" "max-age=31536000" "$(caddy_headers /assets/fonts/geologica-var.woff2)"
check "a policy on the 404 page" "content-security-policy" "$(caddy_headers /no-such-page | tr '[:upper:]' '[:lower:]')"
admin=$(caddy_headers /admin/login/)
check "a policy on the admin" "content-security-policy: default-src 'self'" "${admin,,}"
check "the admin stays out of search engines" "x-robots-tag: noindex" "${admin,,}"
absent "the server's name is not advertised" "gunicorn" "${admin,,}"
check "robots.txt shuts staging" "Disallow: /" "$(curl -s -H "Host: $domain" "http://127.0.0.1:$port/robots.txt")"

echo "== Through nginx, as a visitor"
check "http goes to https" "https://$domain/owner/" "$(curl -s -o /dev/null -D - -H "Host: $domain" http://127.0.0.1/owner/)"
check "the home page" "200" "$(visit -o /dev/null -w '%{http_code}' "https://$domain/")"
check "the bare /admin finds the admin" "301" "$(visit -o /dev/null -w '%{http_code}' "https://$domain/admin")"
hsts=$(visit -o /dev/null -D - "https://$domain/admin/login/" | grep -ci '^strict-transport-security' || true)
check "HSTS is sent once" "1" "$hsts"

echo "== A login behind both proxies (CSRF, secure cookies)"
DJANGO_SUPERUSER_PASSWORD=smoke-test-only-1234 dc run --rm --no-deps -e DJANGO_SUPERUSER_PASSWORD backend \
  python manage.py createsuperuser --noinput --username smoke --email smoke@example.invalid
jar=$work/cookies
page=$(visit -c "$jar" "https://$domain/admin/login/?next=/admin/")
token=$(grep -o 'name="csrfmiddlewaretoken" value="[^"]*"' <<<"$page" | head -n 1 | cut -d'"' -f4)
login=$(visit -b "$jar" -c "$jar" -o /dev/null -D - -H "Referer: https://$domain/admin/login/" \
  --data-urlencode "csrfmiddlewaretoken=$token" --data-urlencode "username=smoke" \
  --data-urlencode "password=smoke-test-only-1234" --data-urlencode "next=/admin/" \
  "https://$domain/admin/login/?next=/admin/")
check "the right password logs in" "location: /admin/" "${login,,}"
check "the session cookie is secure" "secure" "$(grep -i '^set-cookie: sessionid' <<<"$login" | tr '[:upper:]' '[:lower:]')"
check "the admin opens" "200" "$(visit -b "$jar" -o /dev/null -w '%{http_code}' "https://$domain/admin/")"

echo "== The site's form, and the scheduler delivering its email"
lead=$(visit -H 'Accept: application/json' --data-urlencode 'name=Smoke' --data-urlencode 'phone=6940000000' \
  --data-urlencode 'area=Ψαλίδι' --data-urlencode 'bedrooms=2' --data-urlencode 'online=no' \
  --data-urlencode 'website=' "https://$domain/api/lead.php")
check "the form hears ok" '"ok": true' "$lead"
count_sent='from kospm.shared.outbox.models import OutboxMessage as M; print("sent:", M.objects.filter(status="SENT", template="properties.owner_lead").count())'
sent=''
for _ in $(seq 1 18); do
  sent=$(dc exec -T backend python manage.py shell -c "$count_sent" 2>/dev/null | grep 'sent:' || true)
  [[ $sent == 'sent: 0' || -z $sent ]] || break
  sleep 5
done
check "supercronic ran process_outbox and the email left" "sent: 1" "$sent"

echo "== The limit is per visitor, not one for everyone behind the proxies"
post_as() { curl -s -o /dev/null -w '%{http_code}' -H "Host: $domain" -H "X-Real-IP: $1" -H 'Accept: application/json' \
  --data 'name=Smoke&phone=6940000000' "http://127.0.0.1:$port/api/lead.php"; }
for _ in $(seq 1 10); do post_as 203.0.113.50 >/dev/null; done
check "one visitor is stopped" "429" "$(post_as 203.0.113.50)"
check "another visitor is not" "200" "$(post_as 203.0.113.51)"

echo "== Nothing is exposed but the localhost port"
published=$(dc ps --format '{{.Service}} {{.Publishers}}')
check "Caddy on localhost only" "127.0.0.1" "$(grep '^caddy' <<<"$published")"
absent "Caddy not on every address" "0.0.0.0" "$(grep '^caddy' <<<"$published")"
absent "the database on no address" "0.0.0.0" "$(grep '^postgres' <<<"$published")"
absent "the database not on localhost either" "127.0.0.1" "$(grep '^postgres' <<<"$published")"

echo "== The schedule runs on Athens time (ADR 0004)"
check "the scheduler's zone" "EE" "$(dc exec -T scheduler date +%Z)"

echo "== A second deploy brings a new site to the running stack"
git -C "$site_source" archive --format=tar HEAD | bash "$repo/deploy/unpack_site.sh" "$env_root/site"
echo smoke >"$env_root/site.incoming/smoke-marker.txt"
check "not served before the deploy" "404" "$(caddy_status /smoke-marker.txt)"
bash "$env_root/app/deploy/remote_up.sh" staging second site
check "served after the deploy" "200" "$(caddy_status /smoke-marker.txt)"
check "the old folder is gone" "absent" "$([[ -e $env_root/site.previous ]] && echo present || echo absent)"

if ((failures > 0)); then
  echo
  echo "== $failures check(s) failed; the logs:"
  show_logs
  exit 1
fi
echo
echo "== Every check passed"
