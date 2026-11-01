#!/usr/bin/env bash
set -euo pipefail

app_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
config_dir="${app_dir}/config"
books_dir="/mnt/data/plex/books"

install -d -m 0700 "${config_dir}"
install -d -m 0755 "${books_dir}"

cd "${app_dir}"
docker compose config --quiet
docker compose pull --quiet
docker compose up -d --remove-orphans

for _ in $(seq 1 60); do
    health="$(docker inspect kavita --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' 2>/dev/null || true)"
    if [[ "${health}" == "healthy" ]]; then
        curl --fail --silent http://127.0.0.1:5000/api/health >/dev/null
        printf 'Kavita is healthy on 127.0.0.1:5000.\n'
        exit 0
    fi
    sleep 2
done

docker compose ps
docker compose logs --tail 100 kavita >&2
echo "Kavita did not become healthy in time." >&2
exit 1
