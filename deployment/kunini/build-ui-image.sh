#!/usr/bin/env bash
set -euo pipefail

app_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(git -C "${app_dir}" rev-parse --show-toplevel)"
revision="$(git -C "${repo_dir}" rev-parse HEAD)"
short_revision="$(git -C "${repo_dir}" rev-parse --short=12 HEAD)"
image="${KAVITA_IMAGE:-kavita-kunini:${short_revision}}"
ui_source_ref="v0.9.1.4"
ui_patch="${app_dir}/ui-v0.9.1.4.patch"
mkdir -p "${repo_dir}/tmp"
build_root="$(mktemp -d "${repo_dir}/tmp/kavita-ui-build.XXXXXX")"
archive_path="${build_root}/source.tar"
relative_build_root="${build_root#"${repo_dir}/"}"

cleanup() {
    rm -rf -- "${build_root}"
}
trap cleanup EXIT

git -C "${repo_dir}" archive --format=tar --output="${archive_path}" "${ui_source_ref}^{commit}"
tar -xf "${archive_path}" -C "${build_root}"
rm "${archive_path}"
git -C "${repo_dir}" apply --directory="${relative_build_root}" --check "${ui_patch}"
git -C "${repo_dir}" apply --directory="${relative_build_root}" "${ui_patch}"

docker build \
    --platform linux/amd64 \
    --file "${app_dir}/Dockerfile.ui" \
    --build-arg "SOURCE_REVISION=${revision}" \
    --build-arg "UI_SOURCE_REF=${ui_source_ref}" \
    --tag "${image}" \
    "${build_root}/UI/Web"

printf 'Built %s for revision %s from UI source %s.\n' "${image}" "${revision}" "${ui_source_ref}"
