#!/usr/bin/env bash
set -euo pipefail

app_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
domain="books.kunini.ru"
site_name="${domain}.conf"
staging_dir="/home/dekunin/nginx-sites"
staged_config="${staging_dir}/${site_name}"
bootstrap_config="${app_dir}/nginx/${domain}.bootstrap.conf"
tls_config="${app_dir}/nginx/${site_name}"
apply_helper="/usr/local/sbin/codex-nginx-apply"
certbot_config="/home/dekunin/letsencrypt"
certbot_work="/home/dekunin/letsencrypt-work"
certbot_logs="/home/dekunin/letsencrypt-logs"
challenge_root="${app_dir}/acme"
challenge_dir="${challenge_root}/.well-known/acme-challenge"
temporary_dir="$(mktemp -d)"
backup_config="${temporary_dir}/${site_name}"

cleanup() {
    rm -rf "${temporary_dir}"
}
trap cleanup EXIT

restore_site() {
    if [[ -s "${backup_config}" ]]; then
        install -m 0644 "${backup_config}" "${staged_config}"
    else
        install -m 0644 "${bootstrap_config}" "${staged_config}"
    fi
    sudo -n "${apply_helper}" "${site_name}"
}

curl --fail --silent http://127.0.0.1:5000/api/health >/dev/null
install -d -m 0755 "${staging_dir}" "${challenge_dir}"
if [[ -s "${staged_config}" ]]; then
    install -m 0600 "${staged_config}" "${backup_config}"
fi

certificate_dir="${certbot_config}/live/${domain}"
if [[ -s "${certificate_dir}/fullchain.pem" && -s "${certificate_dir}/privkey.pem" ]]; then
    install -m 0644 "${tls_config}" "${staged_config}"
else
    install -m 0644 "${bootstrap_config}" "${staged_config}"
fi
if ! sudo -n "${apply_helper}" "${site_name}"; then
    restore_site
    echo "Initial Nginx configuration failed; restored the previous site." >&2
    exit 1
fi

challenge_name="kavita-preflight-$$"
challenge_value="kavita-${RANDOM}-${RANDOM}"
printf '%s' "${challenge_value}" >"${challenge_dir}/${challenge_name}"
trap 'rm -f "${challenge_dir}/${challenge_name}"; cleanup' EXIT
served_value="$(curl --fail --silent --max-time 15 --resolve "${domain}:80:127.0.0.1" \
    "http://${domain}/.well-known/acme-challenge/${challenge_name}")"
if [[ "${served_value}" != "${challenge_value}" ]]; then
    restore_site
    echo "The ACME challenge path is not served by Nginx." >&2
    exit 1
fi

if [[ ! -s "${certificate_dir}/fullchain.pem" || ! -s "${certificate_dir}/privkey.pem" ]]; then
    if ! certbot certonly \
        --webroot \
        --webroot-path "${challenge_root}" \
        --domain "${domain}" \
        --cert-name "${domain}" \
        --non-interactive \
        --agree-tos \
        --config-dir "${certbot_config}" \
        --work-dir "${certbot_work}" \
        --logs-dir "${certbot_logs}" \
        --deploy-hook "sudo -n ${apply_helper} ${site_name}"; then
        restore_site
        echo "Certificate issuance failed; restored the previous site." >&2
        exit 1
    fi
fi

install -m 0644 "${tls_config}" "${staged_config}"
if ! sudo -n "${apply_helper}" "${site_name}"; then
    restore_site
    echo "TLS configuration failed; restored the previous site." >&2
    exit 1
fi

"${app_dir}/renew-certificate.sh" --dry-run

cron_line="31 4 * * * ${app_dir}/renew-certificate.sh"
cron_file="${temporary_dir}/crontab"
crontab -l >"${cron_file}" 2>/dev/null || true
if ! grep -Fqx "${cron_line}" "${cron_file}"; then
    printf '%s\n' "${cron_line}" >>"${cron_file}"
    crontab "${cron_file}"
fi

"${app_dir}/verify.sh"
