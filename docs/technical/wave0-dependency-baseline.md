# Wave 0.1 — Reproducible runtime and dependency baseline

This implementation wave pins supported runtime families and converts active npm/pip build paths to deterministic lock consumption.

## Runtime baseline

- Node: 24.19.0; frontend Docker variant bookworm-slim
- Documentation portal builder: Node 24.19.0; Docker variant alpine3.24
- Python: 3.11.15; Docker variant slim-trixie (CI/backend image)
- Backend lock generator: uv 0.12.1

## Backend locks

`backend/requirements.lock` and `backend/requirements-dev.lock` are generated, never hand-edited.

```bash
cd backend
./scripts/compile_dependency_locks.sh
./scripts/verify_dependency_locks.sh
```

Docker installs `requirements.lock` with `pip --require-hashes` and installs DentalPin itself with `--no-deps`, preventing a second live resolution. CI uses the development hash lock the same way.

## Frontend/docs

Active CI and Docker paths use `npm ci`, so `package-lock.json` is authoritative. The connected finalizer performs the reviewed Nuxt security refresh and checks the resulting transitive `@nuxt/devtools` and Vite versions.

```bash
./scripts/wave0_1_finalize_connected.sh
```

## Gate

Wave 0.1 is not complete until the connected finalizer succeeds, all configured tests pass on the pinned runtime, and release image digests/SBOM evidence are captured.

## GitHub Actions finalization

When the local environment cannot reach npm/PyPI, run the manual workflow:

```text
.github/workflows/wave0-1-finalize.yml
```

It uses the pinned Node/Python/uv baseline, regenerates the reviewed lock files, runs the backend/frontend/Alembic/E2E gates, builds the production images, generates CycloneDX SBOMs with Syft, scans the images with Grype, and uploads one evidence artifact. It **does not commit or push generated lock files automatically**; review and apply the uploaded generated locks/patch before marking W0.1 complete.

After downloading and extracting the finalization artifact, apply the reviewed generated lock files with either:

```bash
./scripts/wave0_1_apply_finalization_artifact.sh /path/to/extracted-artifact
```

or on Windows PowerShell:

```powershell
.\scripts\wave0_1_apply_finalization_artifact.ps1 -ArtifactDirectory C:\path\to\extracted-artifact
```

Both commands fail closed if the strict W0.1 lock/version gate is not satisfied.
