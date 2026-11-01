#!/usr/bin/env bash
set -euo pipefail

domain="books.kunini.ru"
expected_image="jvmilazz0/kavita:0.9.1@sha256:31181a32f0dda73cae68721867028a7253d57881b58bea5754cd9e578e75421a"
password_file="/var/apps/kavita/secrets/admin-password"
api_key_file="/var/apps/kavita/secrets/dkunin-kover-api-key"
temporary_dir="$(mktemp -d)"
trap 'rm -rf "${temporary_dir}"' EXIT

curl --fail --silent http://127.0.0.1:5000/api/health >/dev/null
curl --fail --silent http://127.0.0.1:5000/api/Settings/oidc >"${temporary_dir}/oidc-config.json"
docker exec kavita curl --fail --silent \
    https://auth.kunini.ru/oidc/.well-known/openid-configuration >"${temporary_dir}/oidc-discovery.json"

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

if [[ ! -s "${password_file}" || ! -s "${api_key_file}" \
    || "$(stat -c '%a' "${password_file}")" != "600" \
    || "$(stat -c '%a' "${api_key_file}")" != "600" ]]; then
    echo "Kavita credential files are missing or have unsafe permissions." >&2
    exit 1
fi

jq -n --arg username dkunin --rawfile password "${password_file}" \
    '{username: $username, password: ($password | rtrimstr("\n"))}' >"${temporary_dir}/native-login.json"
native_login_status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    --request POST --header 'Content-Type: application/json' \
    --data-binary "@${temporary_dir}/native-login.json" \
    http://127.0.0.1:5000/api/Account/login)"

printf 'x-api-key: ' >"${temporary_dir}/api-key-header"
tr -d '\r\n' <"${api_key_file}" >"${temporary_dir}/api-key-value"
cat "${temporary_dir}/api-key-value" >>"${temporary_dir}/api-key-header"
printf '\n' >>"${temporary_dir}/api-key-header"
curl --fail --silent --show-error --header "@${temporary_dir}/api-key-header" \
    --resolve "${domain}:443:127.0.0.1" \
    "https://${domain}/api/Library/libraries" >"${temporary_dir}/libraries.json"
curl --fail --silent --show-error --request POST --get \
    --data-urlencode "apiKey@${temporary_dir}/api-key-value" --data-urlencode 'pluginName=kover' \
    --resolve "${domain}:443:127.0.0.1" \
    "https://${domain}/api/Plugin/authenticate" >"${temporary_dir}/plugin-auth.json"

if [[ "${http_status}" != "301" || "${login_location}" != https://auth.kunini.ru/login* ]]; then
    echo "Browser SSO boundary verification failed." >&2
    exit 1
fi
if [[ -z "${api_health}" || "${api_auth_status}" != "401" || "${login_status}" != "401" ]]; then
    echo "API authentication boundary verification failed." >&2
    exit 1
fi
if ! jq -e 'any(.[]; .name == "Books" and (.folders | index("/books")))' \
    "${temporary_dir}/libraries.json" >/dev/null \
    || ! jq -e 'select(.username == "dkunin") | (.token | length > 0)' \
    "${temporary_dir}/plugin-auth.json" >/dev/null; then
    echo "Authenticated API, Kover login, or Books library verification failed." >&2
    exit 1
fi
if [[ "${native_login_status}" != "401" ]] \
    || ! jq -e '.enabled == true and .autoLogin == true and .disablePasswordAuthentication == true and .providerName == "Kunini"' \
    "${temporary_dir}/oidc-config.json" >/dev/null \
    || ! jq -e '.issuer == "https://auth.kunini.ru/oidc" and (.code_challenge_methods_supported | index("S256"))' \
    "${temporary_dir}/oidc-discovery.json" >/dev/null; then
    echo "Kunini OIDC or native-password-disable verification failed." >&2
    exit 1
fi

printf 'Verified %s: Kunini OIDC, disabled native passwords, dkunin API/Kover auth, Books library, TLS, loopback listener, and read-only media mount.\n' "${domain}"
