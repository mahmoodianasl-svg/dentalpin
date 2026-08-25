# Encrypted backup and clean-restore runbook

This runbook is the Wave 0 recovery contract for a single-host DentalPin
deployment using PostgreSQL and local media storage. A valid recovery point
contains both datasets from the same backup operation:

- a PostgreSQL custom-format dump;
- the `/app/storage` media tree;
- a checksum manifest, encrypted together with `age`.

The backup host receives only an `age` public recipient. Keep the private
identity offline and outside the application host. Losing that identity makes
the archive unrecoverable; placing it beside the archive defeats the recovery
control.

## Recovery objectives

- **RPO:** at most 24 hours for normal operation, plus an on-demand recovery
  point immediately before every migration or release.
- **RTO target:** 60 minutes for a single-host deployment with up to 50 GB of
  database and media data. Measure this in the clinic's own environment;
  storage and network throughput can change the result.
- **Retention:** keep at least 14 daily recovery points and the latest four
  pre-release recovery points in encrypted off-host storage.
- **Drill:** perform and record a clean restore at least quarterly and before a
  high-risk schema release.

## 1. One-time key setup

Install `age` 1.1 or newer on the backup and recovery hosts. Generate the key
on a trusted workstation, not on the DentalPin server:

```bash
age-keygen -o dentalpin-recovery-identity.txt
age-keygen -y dentalpin-recovery-identity.txt
```

The second command prints the public recipient (`age1...`). Store the identity
file in the clinic's credential vault and a separately controlled offline
recovery location. Give the application host only the public recipient.

## 2. Create a recovery point

Run from the repository/deployment directory. Put the application in a short
maintenance window first so no database or media write can cross the snapshot
boundary. Keep PostgreSQL running, but stop the backend; the backup command
uses a one-off container to read the media volume:

```bash
docker compose --env-file .env -f docker-compose.prod.yml stop backend

AGE_RECIPIENT='age1replace-with-clinic-recipient' \
  ./scripts/backup-encrypted.sh \
  --compose-file docker-compose.prod.yml \
  --env-file .env \
  --output /var/backups/dentalpin/dentalpin-$(date -u +%Y%m%dT%H%M%SZ).tar.age

docker compose --env-file .env -f docker-compose.prod.yml up -d backend
```

The command refuses to overwrite an existing archive. Copy the resulting
`.age` file to encrypted off-host storage, then apply the retention policy.
Never copy the private identity with the backups.

For a host bind-mounted media directory, pass `--storage-dir /path/to/storage`
instead of reading `/app/storage` from the backend container.

## 3. Verify an archive without restoring

On the trusted recovery host:

```bash
./scripts/restore-encrypted.sh \
  --archive /recovery/dentalpin-20260825T090000Z.tar.age \
  --identity /secure/dentalpin-recovery-identity.txt \
  --verify-only
```

Verification decrypts into a private temporary directory, rejects unsafe tar
paths or unexpected files, and validates the database/media SHA-256 checksums.
Temporary plaintext is removed when the command exits.

## 4. Restore into clean targets

Do not restore over the active database or a populated media directory. Start
only PostgreSQL in an isolated recovery deployment, then choose a new database
name and empty media destination:

```bash
docker compose --env-file .env -f docker-compose.prod.yml up -d db

./scripts/restore-encrypted.sh \
  --archive /recovery/dentalpin-20260825T090000Z.tar.age \
  --identity /secure/dentalpin-recovery-identity.txt \
  --compose-file docker-compose.prod.yml \
  --env-file .env \
  --target-database dental_clinic_restore_20260825 \
  --storage-dir /srv/dentalpin-restore/storage
```

The restore command fails if the database already exists or the media
directory is non-empty. It does not delete the failed target automatically, so
diagnostic evidence remains available.

## 5. Validate before cutover

Before application traffic is enabled:

1. compare all restored `alembic_version` heads with the source manifest or
   the expected release;
2. run the migrated-schema parity check against the restored database;
3. verify representative patient, appointment, financial-audit, document, and
   image records;
4. start the backend against the restored database and media in an isolated
   network, then check `/health` and `/ready`;
5. record archive name, restore duration, restored byte counts, verifier,
   result, and any corrective action in the recovery log.

Only after those checks pass should the deployment configuration be switched
to the restored database and clean media volume. Preserve the failed/old
environment until the recovery is accepted; prefer forward-fix after cutover
instead of silently rewriting recovered clinical or financial data.

## Automated evidence

`.github/workflows/wave0-recovery-drill.yml` generates an ephemeral age key,
migrates a clean PostgreSQL database to current heads, adds database and media
probes, creates an encrypted archive, restores into clean targets, compares
the probes and Alembic heads, and proves overwrite guards. CI uses synthetic
data; it supplements but does not replace the clinic's quarterly restore drill.
