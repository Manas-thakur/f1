# syntax=docker/dockerfile:1.9
FROM oven/bun:1.3.14-debian AS build

ENV CI=1

WORKDIR /src

COPY package.json bun.lock ./
COPY apps/web/package.json apps/web/
COPY apps/video/package.json apps/video/
RUN --mount=type=cache,target=/root/.bun/install/cache \
    bun install --frozen-lockfile

COPY packages/contracts/generated/ packages/contracts/generated/
COPY apps/web/ apps/web/
RUN bun run --filter @afterlap/web build

FROM python:3.12.14-slim-bookworm AS serve

COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /uvx /usr/local/bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON=/usr/local/bin/python3.12 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    AFTERLAP_RUNTIME_URL=http://runtime:8000 \
    AFTERLAP_AUTOSTART_RUNTIME=0 \
    PORT=8080 \
    HOSTNAME=0.0.0.0

WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
COPY packages/contracts/pyproject.toml packages/contracts/
COPY packages/core/pyproject.toml packages/core/
COPY apps/api/pyproject.toml apps/api/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --all-packages --all-extras --no-extra learning \
            --no-dev --no-install-workspace

COPY packages/ ./packages/
COPY apps/api/ ./apps/api/
COPY workers/ ./workers/
COPY configs/ ./configs/
COPY scripts/ ./scripts/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --all-packages --all-extras --no-extra learning --no-dev

COPY --from=build /src/apps/web/.next/standalone ./
COPY --from=build /src/apps/web/.next/static ./apps/web/.next/static
COPY --from=build /src/apps/web/public ./apps/web/public

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=4s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/', timeout=4).status == 200 else 1)"]

CMD ["node", "apps/web/server.js"]
