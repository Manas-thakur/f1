FROM python:3.12.14-slim-bookworm AS simulator
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /uvx /usr/local/bin/
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock .python-version ./
COPY packages/ packages/
COPY apps/api/ apps/api/
COPY configs/ configs/
COPY scripts/ scripts/
RUN uv sync --frozen --all-packages --no-dev
ENV PATH="/app/.venv/bin:${PATH}"
CMD ["python", "scripts/race.py", "serve", "--host", "0.0.0.0"]

FROM oven/bun:1.3.14-debian AS web-build
WORKDIR /src
COPY package.json bun.lock ./
COPY apps/web/package.json apps/web/
RUN bun install --frozen-lockfile --filter @afterlap/web && rm -rf /root/.bun/install/cache
COPY apps/web/ apps/web/
ENV AFTERLAP_RACE_UPSTREAM=http://simulator:18761
RUN bun run --filter @afterlap/web build

FROM node:22-bookworm-slim AS web
WORKDIR /app
COPY --from=web-build /src/apps/web/.next/standalone ./
COPY --from=web-build /src/apps/web/.next/static ./apps/web/.next/static
ENV PORT=18760 HOSTNAME=0.0.0.0
USER node
CMD ["node", "apps/web/server.js"]
