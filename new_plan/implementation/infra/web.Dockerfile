# syntax=docker/dockerfile:1.9
#
# Two stages: build the React bundle with the pinned pnpm lockfile, then serve
# the static output from nginx and proxy /api and /ws to the API on the *same
# origin*. No API host is compiled into the bundle — `apps/web/vite.config.ts`
# already relies on same-origin paths, and this image is the production half of
# that arrangement.

# --- build ------------------------------------------------------------------
FROM node:24.19.0-bookworm-slim AS build

ENV CI=1 \
    PNPM_HOME=/pnpm \
    PATH="/pnpm:${PATH}"

# corepack ships with the Node image; the pnpm version comes from
# infra/dependency-baseline.md, not from whatever is newest.
RUN corepack enable && corepack prepare pnpm@10.34.5 --activate

WORKDIR /src

# Manifests first so a source edit does not re-resolve the dependency graph.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
COPY apps/web/package.json apps/web/
RUN --mount=type=cache,target=/pnpm/store \
    pnpm install --frozen-lockfile

# The web build imports the generated contract types through the `@contracts`
# alias, so `packages/contracts/generated` has to be present. It is generated
# and committed by the coordinator; this image consumes it and never
# regenerates it, so a drifted checkout fails the build instead of silently
# shipping stale types.
COPY packages/contracts/generated/ packages/contracts/generated/
COPY apps/web/ apps/web/
RUN pnpm --filter @afterlap/web build

# --- serve ------------------------------------------------------------------
FROM nginx:1.29.4-alpine AS serve

# The upstream image's default site would shadow ours.
RUN rm -f /etc/nginx/conf.d/default.conf
COPY infra/nginx.conf /etc/nginx/conf.d/afterlap.conf

COPY --from=build /src/apps/web/dist/ /usr/share/nginx/html/

# nginx:alpine already provides an unprivileged entrypoint that rewrites the
# listen directive; running as uid 101 (nginx) means the container never needs
# a privileged port, which is why nginx.conf listens on 8080.
RUN touch /var/run/nginx.pid \
 && chown -R 101:101 /var/run/nginx.pid /var/cache/nginx /usr/share/nginx/html

USER 101:101

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=4s --start-period=10s --retries=5 \
    CMD ["/bin/sh", "-c", "wget --spider -q http://127.0.0.1:8080/healthz || exit 1"]
