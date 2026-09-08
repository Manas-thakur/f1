# syntax=docker/dockerfile:1.9
FROM oven/bun:1.3.14-debian AS build

ENV CI=1

WORKDIR /src

COPY package.json bun.lock ./
COPY apps/web/package.json apps/web/
RUN --mount=type=cache,target=/root/.bun/install/cache \
    bun install --frozen-lockfile

COPY packages/contracts/generated/ packages/contracts/generated/
COPY apps/web/ apps/web/
RUN bun run --filter @afterlap/web build

FROM nginx:1.29.4-alpine AS serve

RUN rm -f /etc/nginx/conf.d/default.conf
COPY infra/nginx.conf /etc/nginx/conf.d/afterlap.conf

COPY --from=build /src/apps/web/dist/ /usr/share/nginx/html/

RUN touch /var/run/nginx.pid \
 && chown -R 101:101 /var/run/nginx.pid /var/cache/nginx /usr/share/nginx/html

USER 101:101

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=4s --start-period=10s --retries=5 \
    CMD ["/bin/sh", "-c", "wget --spider -q http://127.0.0.1:8080/healthz || exit 1"]
