#!/usr/bin/env bash
# Verify and restore an encrypted DentalPin recovery archive.
#
# Safety defaults:
# - checksums are verified before any database is created;
# - the target database must not already exist;
# - the media destination must be empty;
# - PostgreSQL system databases are never accepted as targets.

set -euo pipefail
umask 077

usage() {
    cat <<'EOF'
Usage: scripts/restore-encrypted.sh --archive PATH --identity PATH \
       --target-database NAME --storage-dir PATH [options]

Required:
  --archive PATH              encrypted .age recovery archive
  --identity PATH             age private identity file
  --target-database NAME      new, clean PostgreSQL database to create
  --storage-dir PATH          new or empty host directory for restored media

Options:
  --compose-file PATH         Compose file (default: docker-compose.prod.yml)
  --env-file PATH             optional Compose environment file
  --verify-only               decrypt and verify without restoring
  -h, --help                  show this help

The database is restored through the Compose service named "db".  Existing
databases and non-empty media directories are never overwritten.
EOF
}

die() {
    echo "error: $*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

validate_database_name() {
    local name="$1"
    [[ "$name" =~ ^[A-Za-z_][A-Za-z0-9_]{0,62}$ ]] \
        || die "invalid PostgreSQL database name: $name"
    case "$name" in
        postgres|template0|template1) die "refusing PostgreSQL system database target: $name" ;;
    esac
}

validate_tar_entries() {
    local archive="$1"
    local entry
    while IFS= read -r entry; do
        case "$entry" in
            /*|../*|*/../*|*/..|..) die "unsafe path in tar archive: $entry" ;;
        esac
    done < <(tar -tf "$archive")
}

archive=""
identity=""
target_database=""
storage_dir=""
compose_file="docker-compose.prod.yml"
env_file=""
verify_only=false

while (($#)); do
    case "$1" in
        --archive)
            (($# >= 2)) || die "--archive requires a value"
            archive="$2"
            shift 2
            ;;
        --identity)
            (($# >= 2)) || die "--identity requires a value"
            identity="$2"
            shift 2
            ;;
        --target-database)
            (($# >= 2)) || die "--target-database requires a value"
            target_database="$2"
            shift 2
            ;;
        --storage-dir)
            (($# >= 2)) || die "--storage-dir requires a value"
            storage_dir="$2"
            shift 2
            ;;
        --compose-file)
            (($# >= 2)) || die "--compose-file requires a value"
            compose_file="$2"
            shift 2
            ;;
        --env-file)
            (($# >= 2)) || die "--env-file requires a value"
            env_file="$2"
            shift 2
            ;;
        --verify-only)
            verify_only=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "unknown option: $1"
            ;;
    esac
done

[[ -n "$archive" ]] || die "--archive is required"
[[ -n "$identity" ]] || die "--identity is required"
[[ -f "$archive" ]] || die "archive not found: $archive"
[[ -f "$identity" ]] || die "age identity not found: $identity"
if [[ "$verify_only" != true ]]; then
    [[ -n "$target_database" ]] || die "--target-database is required unless --verify-only is used"
    [[ -n "$storage_dir" ]] || die "--storage-dir is required unless --verify-only is used"
    validate_database_name "$target_database"
    [[ -f "$compose_file" ]] || die "Compose file not found: $compose_file"
    if [[ -n "$env_file" ]]; then
        [[ -f "$env_file" ]] || die "Compose environment file not found: $env_file"
    fi
fi

require_command age
require_command sha256sum
require_command tar

if [[ "$verify_only" != true ]]; then
    require_command docker
    if docker compose version >/dev/null 2>&1; then
        compose=(docker compose)
    elif command -v docker-compose >/dev/null 2>&1; then
        compose=(docker-compose)
    else
        die "neither 'docker compose' nor 'docker-compose' is available"
    fi
    if [[ -n "$env_file" ]]; then
        compose+=(--env-file "$env_file")
    fi
    compose+=(-f "$compose_file")
fi

temp_root="${TMPDIR:-/tmp}"
[[ "$temp_root" = /* ]] || temp_root="/tmp"
tmp_dir="$(mktemp -d "${temp_root%/}/dentalpin-restore.XXXXXX")"
bundle="$tmp_dir/bundle.tar"
payload_dir="$tmp_dir/payload"
mkdir -p "$payload_dir"

cleanup() {
    if [[ -n "${tmp_dir:-}" && -d "$tmp_dir" ]]; then
        case "$tmp_dir" in
            "${temp_root%/}"/dentalpin-restore.*) rm -rf -- "$tmp_dir" ;;
            *) echo "warning: refusing to remove unexpected temporary path: $tmp_dir" >&2 ;;
        esac
    fi
}
trap cleanup EXIT

echo "Decrypting recovery archive..."
age --decrypt --identity "$identity" "$archive" > "$bundle"
[[ -s "$bundle" ]] || die "decrypted bundle is empty"

validate_tar_entries "$bundle"
mapfile -t bundle_entries < <(tar -tf "$bundle" | sed 's#^\./##' | sort -u)
expected_entries=("SHA256SUMS" "database.dump" "manifest.env" "media.tar")
if [[ "${bundle_entries[*]}" != "${expected_entries[*]}" ]]; then
    die "archive contains an unexpected file set"
fi

tar -xf "$bundle" -C "$payload_dir" manifest.env SHA256SUMS database.dump media.tar
(
    cd "$payload_dir"
    sha256sum --check --strict SHA256SUMS
)

format_version="$(sed -n 's/^format_version=//p' "$payload_dir/manifest.env")"
source_database="$(sed -n 's/^source_database=//p' "$payload_dir/manifest.env")"
[[ "$format_version" == "1" ]] || die "unsupported recovery archive format: $format_version"
[[ -n "$source_database" ]] || die "archive manifest has no source_database"

validate_tar_entries "$payload_dir/media.tar"
echo "Recovery archive verified (source database: $source_database)."

if [[ "$verify_only" == true ]]; then
    exit 0
fi

# The database environment and positional argument expand inside the container.
# shellcheck disable=SC2016
existing="$({
    printf "SELECT 1 FROM pg_database WHERE datname = :'target';\n"
} | "${compose[@]}" exec -T db sh -ceu \
    'exec psql -U "${POSTGRES_USER:-dental}" -d postgres -At -v ON_ERROR_STOP=1 -v target="$1"' \
    sh "$target_database" | tr -d '\r')"
[[ -z "$existing" ]] || die "target database already exists; refusing overwrite: $target_database"

if [[ -e "$storage_dir" ]]; then
    [[ -d "$storage_dir" ]] || die "media destination is not a directory: $storage_dir"
    [[ -z "$(find "$storage_dir" -mindepth 1 -maxdepth 1 -print -quit)" ]] \
        || die "media destination is not empty: $storage_dir"
else
    mkdir -p "$storage_dir"
fi

echo "Creating clean target database: $target_database"
# The database environment and positional argument expand inside the container.
# shellcheck disable=SC2016
"${compose[@]}" exec -T db sh -ceu \
    'exec createdb -U "${POSTGRES_USER:-dental}" "$1"' sh "$target_database"

echo "Restoring PostgreSQL dump..."
# The database environment and positional argument expand inside the container.
# shellcheck disable=SC2016
"${compose[@]}" exec -T db sh -ceu \
    'exec pg_restore -U "${POSTGRES_USER:-dental}" -d "$1" --exit-on-error --no-owner --no-privileges' \
    sh "$target_database" < "$payload_dir/database.dump"

echo "Restoring media snapshot..."
tar -xf "$payload_dir/media.tar" -C "$storage_dir"

echo "Restore completed: database=$target_database media=$storage_dir"
