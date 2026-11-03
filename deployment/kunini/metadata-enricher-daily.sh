#!/usr/bin/env bash
set -euo pipefail

umask 077
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

app_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python_bin="${KAVITA_METADATA_PYTHON:-/usr/bin/python3}"
flock_bin="${KAVITA_METADATA_FLOCK:-/usr/bin/flock}"
enricher="${KAVITA_METADATA_ENRICHER:-${app_dir}/metadata_enricher.py}"
state_dir="${KAVITA_METADATA_STATE_DIR:-/var/apps/kavita/metadata-enricher}"
api_key_file="${KAVITA_METADATA_API_KEY_FILE:-/var/apps/kavita/secrets/dkunin-kover-api-key}"
database_path="${KAVITA_METADATA_DATABASE_PATH:-${app_dir}/config/kavita.db}"
library_root="${KAVITA_METADATA_LIBRARY_ROOT:-/mnt/data/plex/books}"
kavita_url="${KAVITA_METADATA_KAVITA_URL:-https://books.kunini.ru}"
contact="${KAVITA_METADATA_CONTACT:-https://books.kunini.ru}"
cache_ttl_days="${KAVITA_METADATA_CACHE_TTL_DAYS:-1}"
metron_token_file="${KAVITA_METADATA_METRON_TOKEN_FILE:-}"

runs_dir="${state_dir}/runs"
cache_dir="${state_dir}/cache"
backup_dir="${state_dir}/backups"
install -d -m 700 "${state_dir}" "${runs_dir}" "${cache_dir}" "${backup_dir}"
touch "${state_dir}/daily.log"
chmod 600 "${state_dir}/daily.log"
exec >>"${state_dir}/daily.log" 2>&1

exec 9>"${state_dir}/daily.lock"
if ! "${flock_bin}" -n 9; then
    printf '%s outcome=skipped reason=already-running\n' "$(date -u +%FT%TZ)"
    exit 0
fi

run_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
report="${runs_dir}/${run_id}-report.json"
audit_result="${runs_dir}/${run_id}-audit-result.json"
audit_log="${runs_dir}/${run_id}-audit.log"
journal="${runs_dir}/${run_id}-apply-journal.json"

printf '%s run=%s stage=audit outcome=started\n' "$(date -u +%FT%TZ)" "${run_id}"
audit_command=(
    "${python_bin}" "${enricher}" audit
    --kavita-url "${kavita_url}"
    --api-key-file "${api_key_file}"
    --cache-dir "${cache_dir}"
    --cache-ttl-days "${cache_ttl_days}"
    --contact "${contact}"
    --library-root "${library_root}"
    --output "${report}"
)
if [[ -n "${metron_token_file}" ]]; then
    audit_command+=(--metron-token-file "${metron_token_file}")
fi

if ! "${audit_command[@]}" >"${audit_result}" 2>"${audit_log}"; then
    printf '%s run=%s stage=audit outcome=failed log=%s\n' \
        "$(date -u +%FT%TZ)" "${run_id}" "${audit_log}"
    exit 1
fi
ln -sfn "${report}" "${state_dir}/latest-report.json"

read -r provider_errors approved < <(
    "${python_bin}" - "${report}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    report = json.load(stream)
print(len(report.get("providerErrors", [])), report.get("stats", {}).get("autoApproved", 0))
PY
)
if ((provider_errors > 0)); then
    printf '%s run=%s stage=audit outcome=blocked provider_errors=%d report=%s\n' \
        "$(date -u +%FT%TZ)" "${run_id}" "${provider_errors}" "${report}"
    exit 1
fi
if ((approved == 0)); then
    printf '%s run=%s outcome=no-op approved=0 report=%s\n' \
        "$(date -u +%FT%TZ)" "${run_id}" "${report}"
    exit 0
fi

report_sha="$(
    "${python_bin}" - "${report}" <<'PY'
import hashlib
import sys

digest = hashlib.sha256()
with open(sys.argv[1], "rb") as stream:
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
print(digest.hexdigest())
PY
)"
printf '%s run=%s stage=apply outcome=started approved=%d report_sha256=%s\n' \
    "$(date -u +%FT%TZ)" "${run_id}" "${approved}" "${report_sha}"
"${python_bin}" "${enricher}" apply \
    --kavita-url "${kavita_url}" \
    --api-key-file "${api_key_file}" \
    --report "${report}" \
    --confirm-sha256 "${report_sha}" \
    --database-path "${database_path}" \
    --backup-dir "${backup_dir}" \
    --journal "${journal}"
ln -sfn "${journal}" "${state_dir}/latest-journal.json"

read -r journal_status journal_items < <(
    "${python_bin}" - "${journal}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    journal = json.load(stream)
print(journal.get("status", "missing"), len(journal.get("items", [])))
PY
)
if [[ "${journal_status}" != "complete" ]] || ((journal_items != approved)); then
    printf '%s run=%s stage=verify outcome=failed status=%s items=%d expected=%d\n' \
        "$(date -u +%FT%TZ)" "${run_id}" "${journal_status}" "${journal_items}" "${approved}"
    exit 1
fi

printf '%s run=%s outcome=complete applied=%d report=%s journal=%s\n' \
    "$(date -u +%FT%TZ)" "${run_id}" "${approved}" "${report}" "${journal}"
