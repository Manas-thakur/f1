# syntax=docker/dockerfile:1.9
#
# AFTERLAP numerical runtime image (Linux). Serves three roles from one build:
# the FastAPI control plane, the Alembic migration job and the batch worker.
#
# What is deliberately NOT in here:
#
#   * the `learning` extra. On Linux `torch` pulls the whole CUDA runtime
#     (cuda-toolkit, cudnn, nccl, triton) — several gigabytes for a control
#     plane that never trains. TECH_STACK.md already says GPU training gets its
#     own image, so this one installs every other extra and excludes that one
#     explicitly with `--no-extra learning`. `afterlap_core.learning` imports
#     lazily, `doctor` reports torch as degraded rather than missing-and-fatal,
#     and readiness does not depend on it.
#   * acados. Coordinator decision D-02: it is not built here and is not faked.
#     CasADi/IPOPT (the `solver` extra) is the active continuous solver and
#     `doctor` says so.
#
# The build context is the implementation workspace root, so `uv.lock` is used
# verbatim: this image installs frozen, never resolves.

# Explicit patch tag rather than a floating major. The digest this resolved to
# on the machine that built it is recorded in infra/README.md.
FROM python:3.12.14-slim-bookworm AS runtime

# uv pinned to the version in infra/dependency-baseline.md.
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /uvx /usr/local/bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON=/usr/local/bin/python3.12 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_COMPILE_BYTECODE=1

WORKDIR /app

# --- dependency layer -------------------------------------------------------
# Only the manifests, so a source edit does not re-download the numerical
# stack. `--no-install-workspace` installs the third-party graph and leaves the
# workspace members for the next layer.
COPY pyproject.toml uv.lock .python-version ./
COPY packages/contracts/pyproject.toml packages/contracts/
COPY packages/core/pyproject.toml packages/core/
COPY packages/application/pyproject.toml packages/application/
COPY packages/infrastructure/pyproject.toml packages/infrastructure/
COPY apps/api/pyproject.toml apps/api/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --all-packages --all-extras --no-extra learning \
            --no-dev --no-install-workspace

# --- source layer -----------------------------------------------------------
# `afterlap_core.paths.implementation_root()` looks upward for the directory
# holding both `pyproject.toml` and `packages/`, so the workspace layout is
# kept verbatim at /app and AFTERLAP_ROOT is left unset. `configs/` therefore
# resolves to /app/configs and `artifacts/` to /app/artifacts, which is where
# the named volumes mount.
COPY packages/ ./packages/
COPY apps/api/ ./apps/api/
COPY workers/ ./workers/
COPY configs/ ./configs/
COPY scripts/ ./scripts/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --all-packages --all-extras --no-extra learning --no-dev

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app

# The artefact roots are created and owned at build time so that a *fresh*
# named volume mounted over them inherits this ownership; the process never
# runs as root.
RUN groupadd --gid 10001 afterlap \
 && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin afterlap \
 && mkdir -p /app/artifacts/trajectories /app/artifacts/models /app/artifacts/reports \
             /app/artifacts/exports /app/artifacts/spool /app/artifacts/objects \
 && chown -R 10001:10001 /app/artifacts

USER 10001:10001

EXPOSE 8000

# Liveness is the process loop; readiness is measured capability. The container
# healthcheck uses readiness on purpose: a process that answers HTTP but cannot
# reach its storage or its numerics is not a decision system.
HEALTHCHECK --interval=10s --timeout=5s --start-period=40s --retries=6 \
    CMD ["python", "-c", "import sys,urllib.request;\
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/ready', timeout=4).status == 200 else 1)"]

# 0.0.0.0 *inside* the container only. The host-side publish in
# docker-compose.yml binds 127.0.0.1, so nothing is reachable off the machine.
CMD ["python", "-m", "afterlap_api.cli", "serve", "--host", "0.0.0.0", "--port", "8000"]
