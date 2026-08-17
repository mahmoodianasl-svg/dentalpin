# syntax=docker/dockerfile:1.6
#
# Multi-stage build for the DentalPin documentation portal.
#
# Build context MUST be the repository root (or at minimum the `docs/`
# folder), because VitePress' `srcDir` is configured as `..` — pointing one
# level up from `docs/portal/` to `docs/` so all existing markdown is
# rendered without duplication.
#
# Coolify usage:
#   - Repository:        martinezsalmeron/dentalpin
#   - Build context:     /                  (repo root)
#   - Dockerfile path:   docs/portal/Dockerfile
#   - Exposed port:      80
#   - Domain:            docs.dentalpin.com
#   - TLS:               Coolify (Let's Encrypt)

# ---- Builder ----------------------------------------------------------------
ARG NODE_VERSION=24.19.0
ARG NODE_VARIANT=alpine3.24
FROM node:${NODE_VERSION}-${NODE_VARIANT} AS builder
WORKDIR /build

# Copy the entire docs tree so VitePress can read it.
COPY docs/ ./docs/

WORKDIR /build/docs/portal

# Install exactly the dependency graph committed in package-lock.json.
RUN npm ci --no-audit --no-fund \
 && npm run build

# ---- Runtime ----------------------------------------------------------------
FROM nginx:alpine AS runtime

# Replace the default config with ours (clean URLs, gzip, cache headers).
COPY docs/portal/nginx.conf /etc/nginx/conf.d/default.conf

# Static site output from the builder.
COPY --from=builder /build/docs/portal/.vitepress/dist/ /usr/share/nginx/html/

EXPOSE 80

# Healthcheck so Coolify can detect a broken build.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://localhost/ || exit 1
