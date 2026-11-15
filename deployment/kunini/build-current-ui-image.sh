#!/usr/bin/env bash
set -euo pipefail

app_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(git -C "${app_dir}" rev-parse --show-toplevel)"
revision="$(git -C "${repo_dir}" rev-parse HEAD)"
short_revision="$(git -C "${repo_dir}" rev-parse --short=12 HEAD)"
base_image="${KAVITA_BASE_IMAGE:?Set KAVITA_BASE_IMAGE to the deployed feature image}"
image="${KAVITA_IMAGE:-kavita-kunini:${short_revision}}"
ui_source_ref="v0.9.1.4"
ui_patch="${app_dir}/ui-v0.9.1.4.patch"
ink_patch="${app_dir}/ui-ink-v0.9.1.4.patch"
feature_patch="${app_dir}/ui-want-to-find-v0.9.1.4.patch"
mkdir -p "${repo_dir}/tmp"
build_root="$(mktemp -d "${repo_dir}/tmp/kavita-current-ui.XXXXXX")"
relative_build_root="${build_root#"${repo_dir}/"}"

cleanup() {
    rm -rf -- "${build_root}"
}
trap cleanup EXIT

if [[ -n "$(git -C "${repo_dir}" status --porcelain --untracked-files=all -- deployment/kunini)" ]]; then
    printf 'deployment/kunini must be clean so the image matches revision %s.\n' "${revision}" >&2
    exit 1
fi

git -C "${repo_dir}" archive --format=tar "${ui_source_ref}^{commit}" -- UI/Web | tar -xf - -C "${build_root}"
git -C "${repo_dir}" apply --directory="${relative_build_root}" --check "${ui_patch}"
git -C "${repo_dir}" apply --directory="${relative_build_root}" "${ui_patch}"
git -C "${repo_dir}" apply --unidiff-zero --directory="${relative_build_root}" --check "${ink_patch}"
git -C "${repo_dir}" apply --unidiff-zero --directory="${relative_build_root}" "${ink_patch}"
git -C "${repo_dir}" apply --unidiff-zero --directory="${relative_build_root}" --check "${feature_patch}"
git -C "${repo_dir}" apply --unidiff-zero --directory="${relative_build_root}" "${feature_patch}"

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
    "${build_root}/UI/Web"

printf 'Built %s for revision %s on feature base %s.\n' "${image}" "${revision}" "${base_revision}"
