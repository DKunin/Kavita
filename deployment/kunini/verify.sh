#!/usr/bin/env bash
set -euo pipefail

domain="books.kunini.ru"
expected_image="jvmilazz0/kavita:0.9.1@sha256:31181a32f0dda73cae68721867028a7253d57881b58bea5754cd9e578e75421a"

curl --fail --silent http://127.0.0.1:5000/api/health >/dev/null

health="$(docker inspect kavita --format '{{.State.Health.Status}}')"
published_port="$(docker port kavita 5000/tcp)"
books_mode="$(docker inspect kavita --format '{{range .Mounts}}{{if eq .Destination "/books"}}{{.Mode}}{{end}}{{end}}')"
configured_image="$(docker inspect kavita --format '{{.Config.Image}}')"
if [[ "${health}" != "healthy" || "${published_port}" != "127.0.0.1:5000" \
    || "${books_mode}" != "ro" || "${configured_image}" != "${expected_image}" ]]; then
    echo "Container health, listener, image, or media mount verification failed." >&2
    exit 1
fi

http_status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
    --resolve "${domain}:80:127.0.0.1" "http://${domain}/")"
login_location="$(curl --silent --head --resolve "${domain}:443:127.0.0.1" \
    "https://${domain}/" | tr -d '\r' | awk 'tolower($1) == "location:" { print $2 }')"
api_health="$(curl --fail --silent --resolve "${domain}:443:127.0.0.1" \
    "https://${domain}/api/health")"
api_auth_status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
    --resolve "${domain}:443:127.0.0.1" \
    "https://${domain}/api/Library/libraries")"
login_status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
    --request POST --header 'Content-Type: application/json' --data '{}' \
    --resolve "${domain}:443:127.0.0.1" "https://${domain}/api/account/login")"

if [[ "${http_status}" != "301" || "${login_location}" != https://auth.kunini.ru/login* ]]; then
    echo "Browser SSO boundary verification failed." >&2
    exit 1
fi
if [[ -z "${api_health}" || "${api_auth_status}" != "401" || "${login_status}" != "401" ]]; then
    echo "API authentication boundary verification failed." >&2
    exit 1
fi

printf 'Verified %s: browser SSO, API 401 behavior, TLS, loopback listener, and read-only media mount.\n' "${domain}"
