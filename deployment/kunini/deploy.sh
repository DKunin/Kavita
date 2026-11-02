#!/usr/bin/env bash
set -euo pipefail

app_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(git -C "${app_dir}" rev-parse --show-toplevel)"
config_dir="${app_dir}/config"
books_dir="/mnt/data/plex/books"
revision="$(git -C "${repo_dir}" rev-parse --short=12 HEAD)"
image="${KAVITA_IMAGE:-kavita-kunini:${revision}}"
export KAVITA_IMAGE="${image}"

install -d -m 0700 "${config_dir}"
install -d -m 0755 "${books_dir}"

cd "${app_dir}"
docker compose config --quiet
if [[ "${image}" == jvmilazz0/* ]]; then
    docker pull --quiet "${image}"
elif ! docker image inspect "${image}" >/dev/null 2>&1; then
    printf 'Required local image %s is not loaded. Build and transfer it before deployment.\n' "${image}" >&2
    exit 1
fi
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
