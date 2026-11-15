#!/usr/bin/env bash
set -euo pipefail

app_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(git -C "${app_dir}" rev-parse --show-toplevel)"
revision="$(git -C "${repo_dir}" rev-parse HEAD)"
short_revision="$(git -C "${repo_dir}" rev-parse --short=12 HEAD)"
base_image="${KAVITA_BASE_IMAGE:?Set KAVITA_BASE_IMAGE to the deployed feature image}"
image="${KAVITA_IMAGE:-kavita-kunini:${short_revision}}"

if [[ -n "$(git -C "${repo_dir}" status --porcelain --untracked-files=all -- UI/Web)" ]]; then
    printf 'UI/Web must be clean so the image matches revision %s.\n' "${revision}" >&2
    exit 1
fi

base_revision="$(docker image inspect "${base_image}" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')"
if [[ -z "${base_revision}" || "${base_revision}" == '<no value>' ]]; then
    printf 'Base image %s has no revision label.\n' "${base_image}" >&2
    exit 1
fi

docker build \
    --platform linux/amd64 \
    --file "${app_dir}/Dockerfile.ui" \
    --build-arg "KAVITA_RUNTIME_IMAGE=${base_image}" \
    --build-arg "SOURCE_REVISION=${revision}" \
    --build-arg "UI_SOURCE_REF=${revision}" \
    --build-arg "FEATURE_BASE_REVISION=${base_revision}" \
    --tag "${image}" \
    "${repo_dir}/UI/Web"

printf 'Built %s for revision %s on feature base %s.\n' "${image}" "${revision}" "${base_revision}"
