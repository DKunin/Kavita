#!/usr/bin/env bash
set -euo pipefail

app_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(git -C "${app_dir}" rev-parse --show-toplevel)"
revision="$(git -C "${repo_dir}" rev-parse HEAD)"
short_revision="$(git -C "${repo_dir}" rev-parse --short=12 HEAD)"
image="${KAVITA_IMAGE:-kavita-kunini:${short_revision}}"

docker build \
    --platform linux/amd64 \
    --file "${app_dir}/Dockerfile.ui" \
    --build-arg "SOURCE_REVISION=${revision}" \
    --tag "${image}" \
    "${repo_dir}/UI/Web"

printf 'Built %s for revision %s.\n' "${image}" "${revision}"
