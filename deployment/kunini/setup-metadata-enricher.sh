#!/usr/bin/env bash
set -euo pipefail

app_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
daily_script="${app_dir}/metadata-enricher-daily.sh"
state_dir="/var/apps/kavita/metadata-enricher"
cron_line="17 3 * * * /bin/bash ${daily_script}"
temporary_dir="$(mktemp -d)"
trap 'rm -rf "${temporary_dir}"' EXIT

install -d -m 700 "${state_dir}" "${state_dir}/runs" "${state_dir}/cache" "${state_dir}/backups"
crontab -l >"${temporary_dir}/crontab" 2>/dev/null || true
if ! grep -Fqx "${cron_line}" "${temporary_dir}/crontab"; then
    printf '%s\n' "${cron_line}" >>"${temporary_dir}/crontab"
    crontab "${temporary_dir}/crontab"
fi

if ! crontab -l | grep -Fqx "${cron_line}"; then
    echo "Metadata enricher cron installation failed." >&2
    exit 1
fi
printf 'Installed daily metadata enrichment at 03:17 server time: %s\n' "${daily_script}"
