#!/usr/bin/env bash
# Create an encrypted DentalPin recovery archive.
#
# The archive contains a PostgreSQL custom-format dump, a media tarball,
# metadata, and SHA-256 checksums.  Plaintext staging files live only in a
# mode-0700 temporary directory and are removed on exit.

set -euo pipefail
umask 077

usage() {
    cat <<'EOF'
Usage: scripts/backup-encrypted.sh [options]

Options:
  --recipient AGE_RECIPIENT   age public recipient (or set AGE_RECIPIENT)
  --output PATH               encrypted archive path (default: backups/<timestamp>.tar.age)
  --compose-file PATH         Compose file (default: docker-compose.prod.yml)
  --env-file PATH             optional Compose environment file
  --storage-dir PATH          archive this host directory instead of the backend volume
  --storage-service NAME      Compose service that owns media (default: backend)
  --storage-path PATH         media path inside that service (default: /app/storage)
  -h, --help                  show this help

The database is dumped from the Compose service named "db".  The command
never accepts a private age identity; keep decryption keys off the app host.
EOF
}

die() {
    echo "error: $*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

recipient="${AGE_RECIPIENT:-}"
output=""
compose_file="docker-compose.prod.yml"
env_file=""
storage_dir=""
storage_service="backend"
storage_path="/app/storage"

while (($#)); do
    case "$1" in
        --recipient)
            (($# >= 2)) || die "--recipient requires a value"
            recipient="$2"
            shift 2
            ;;
        --output)
            (($# >= 2)) || die "--output requires a value"
            output="$2"
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
        --storage-dir)
            (($# >= 2)) || die "--storage-dir requires a value"
            storage_dir="$2"
            shift 2
            ;;
        --storage-service)
            (($# >= 2)) || die "--storage-service requires a value"
            storage_service="$2"
            shift 2
            ;;
        --storage-path)
            (($# >= 2)) || die "--storage-path requires a value"
            storage_path="$2"
            shift 2
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

[[ -n "$recipient" ]] || die "set AGE_RECIPIENT or pass --recipient"
[[ -f "$compose_file" ]] || die "Compose file not found: $compose_file"
if [[ -n "$env_file" ]]; then
    [[ -f "$env_file" ]] || die "Compose environment file not found: $env_file"
fi
if [[ -n "$storage_dir" ]]; then
    [[ -d "$storage_dir" ]] || die "storage directory not found: $storage_dir"
fi

require_command age
require_command docker
require_command sha256sum
require_command tar

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

created_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
if [[ -z "$output" ]]; then
    output="backups/dentalpin-${timestamp}.tar.age"
fi
[[ ! -e "$output" ]] || die "refusing to overwrite existing archive: $output"

output_dir="$(dirname "$output")"
mkdir -p "$output_dir"
partial_output="${output}.partial.$$"
[[ ! -e "$partial_output" ]] || die "temporary output already exists: $partial_output"

temp_root="${TMPDIR:-/tmp}"
[[ "$temp_root" = /* ]] || temp_root="/tmp"
tmp_dir="$(mktemp -d "${temp_root%/}/dentalpin-backup.XXXXXX")"
payload_dir="$tmp_dir/payload"
mkdir -p "$payload_dir"

cleanup() {
    if [[ -n "${partial_output:-}" && -f "$partial_output" ]]; then
        rm -f -- "$partial_output"
    fi
    if [[ -n "${tmp_dir:-}" && -d "$tmp_dir" ]]; then
        case "$tmp_dir" in
            "${temp_root%/}"/dentalpin-backup.*) rm -rf -- "$tmp_dir" ;;
            *) echo "warning: refusing to remove unexpected temporary path: $tmp_dir" >&2 ;;
        esac
    fi
}
trap cleanup EXIT

db_name="$(
    "${compose[@]}" exec -T db sh -ceu \
        'printf "%s" "${POSTGRES_DB:-dental_clinic}"' | tr -d '\r'
)"
[[ -n "$db_name" ]] || die "could not resolve POSTGRES_DB from the db service"
[[ "$db_name" =~ ^[A-Za-z_][A-Za-z0-9_]{0,62}$ ]] \
    || die "invalid POSTGRES_DB value returned by the db service"

echo "Creating PostgreSQL dump..."
"${compose[@]}" exec -T db sh -ceu \
    'exec pg_dump -U "${POSTGRES_USER:-dental}" -d "${POSTGRES_DB:-dental_clinic}" --format=custom --no-owner --no-privileges' \
    > "$payload_dir/database.dump"
[[ -s "$payload_dir/database.dump" ]] || die "PostgreSQL dump is empty"

echo "Creating media snapshot..."
if [[ -n "$storage_dir" ]]; then
    tar -C "$storage_dir" -cf "$payload_dir/media.tar" .
    media_source="host-directory"
else
    "${compose[@]}" run --rm --no-deps -T --entrypoint sh "$storage_service" -ceu \
        'test -d "$1"; exec tar -C "$1" -cf - .' sh "$storage_path" \
        > "$payload_dir/media.tar"
    media_source="compose-service"
fi
[[ -s "$payload_dir/media.tar" ]] || die "media snapshot is empty"

source_commit="unknown"
if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    source_commit="$(git rev-parse HEAD)"
fi

{
    printf 'format_version=1\n'
    printf 'created_at=%s\n' "$created_at"
    printf 'source_database=%s\n' "$db_name"
    printf 'source_commit=%s\n' "$source_commit"
    printf 'media_source=%s\n' "$media_source"
} > "$payload_dir/manifest.env"

(
    cd "$payload_dir"
    sha256sum database.dump media.tar > SHA256SUMS
)

echo "Encrypting recovery archive..."
tar -C "$payload_dir" -cf - manifest.env SHA256SUMS database.dump media.tar \
    | age --encrypt --recipient "$recipient" > "$partial_output"
[[ -s "$partial_output" ]] || die "encrypted archive is empty"

mv -- "$partial_output" "$output"
partial_output=""
echo "Encrypted recovery archive created: $output"
