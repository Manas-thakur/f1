# Local packaging

Compose project for the whole product: PostgreSQL 17, a migration job, the API,
the batch worker, and nginx serving the built web assets while proxying `/api`
and `/ws` on the same origin.

Everything here was **built and run** on the machine named below. Where a claim
is not measured, it says so.

## Quick start

```
cd .
cp infra/.env.example infra/.env
python -c "import secrets; print(secrets.token_urlsafe(32))"   # put it in infra/.env
docker compose -f infra/docker-compose.yml --env-file infra/.env up -d --wait
```

| Surface | Address |
|---|---|
| Engineer console (nginx) | http://127.0.0.1:8080 |
| API (direct, for debugging) | http://127.0.0.1:8010 |
| API through nginx (same origin) | http://127.0.0.1:8080/api/v1 |
| Session stream | ws://127.0.0.1:8080/api/v1/sessions/{id}/stream |
| PostgreSQL | 127.0.0.1:5433 |

All four bind `127.0.0.1`. There is no authentication in this release, so
nothing here may be exposed on a routable interface. `docker compose down`
stops the stack; `down -v` also discards the four named volumes.

Verify the loop without a browser:

```
./.venv/Scripts/python.exe scripts/demo.py --base-url http://127.0.0.1:8080
```

## Files

| File | What it is |
|---|---|
| `docker-compose.yml` | db, migrate, api, batch, web; four named volumes; loopback publishes |
| `api.Dockerfile` | Linux numerical image. Serves the API, the migration job and the batch worker |
| `web.Dockerfile` | bun build stage, then nginx serving the output |
| `nginx.conf` | Static assets plus `/api` and `/ws` on one origin, with WebSocket upgrade |
| `*.Dockerfile.dockerignore` | Per-Dockerfile ignore files (BuildKit reads these first) |
| `.env.example` | Copy to `.env`. `AFTERLAP_DB_PASSWORD` has **no default** |
| `dependency-baseline.md` | A01's frozen versions and the G0 solver spike |

The build context for both images is the implementation workspace root, so the
ignore files live beside their Dockerfile rather than at the context root —
that directory is not this package's to write.

## What the images contain, and what they deliberately do not

`api.Dockerfile` installs `uv sync --frozen --all-packages --all-extras
--no-extra learning`. The exclusion is the interesting part:

* **`learning` is excluded on purpose.** On Linux, `torch` pulls the entire
  CUDA runtime (`cuda-toolkit`, `cudnn`, `nccl`, `triton`) — gigabytes, for a
  control plane that never trains. `TECH_STACK.md` already gives GPU training
  its own image. `afterlap_core.learning` imports lazily, `doctor` reports
  torch and the learning stack as **degraded** inside the container, and
  readiness does not depend on either. Anyone who needs the learning path in a
  container needs a second image; this one honestly says it cannot.
* **acados is not built and is not faked.** Coordinator decision D-02:
  CasADi/IPOPT is the active continuous solver and `doctor` reports acados as
  degraded/not installed. Building it from a pinned commit inside this image
  remains open work.
* **`psycopg` is included** (the `postgres` extra of `afterlap-api`), which is
  what makes the PostgreSQL service usable.

Measured inside the running container:

```
$ curl -s http://127.0.0.1:8080/api/v1/health/ready
{"status":"ready","detail":{"python":"available","contracts":"available",
 "numerics":"available","solver":"available","acados":"degraded",
 "torch":"degraded","learning":"degraded","database":"available",
 "storage":"available"}}
```

Compare the native Windows run, where torch and the learning stack are present
and the database check is degraded because no `AFTERLAP_DATABASE_URL` is set.
Both reports are accurate about their own environment; neither is edited.

## Base images

Pinned by explicit patch tag rather than by digest, so the file stays readable
and a version bump is a reviewable one-line change. The digests those tags
resolved to on the build machine, recorded with
`docker buildx imagetools inspect <tag> --format '{{.Manifest.Digest}}'`:

| Tag | Digest at build time |
|---|---|
| `python:3.12.14-slim-bookworm` | `sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254` |
| `ghcr.io/astral-sh/uv:0.12.10` | `sha256:2bb3ebca0a796a155094a27773d290c4b074572e6107f171d88d086682fd2500` |
| `postgres:17.7-alpine` | `sha256:bb377b7239d2774ac8cc76f481596ce96c5a6b5e9d141f6d0a0ee371a6e7c0f2` |
| `nginx:1.29.4-alpine` | `sha256:4870c12cd2ca986de501a804b4f506ad3875a0b1874940ba0a2c7f763f1855b2` |
| `node:24.19.0-bookworm-slim` | `sha256:a9f5f7c91a432850b2a8a7797adf5eadb6c733ceed61167806cee7ea7fbc29df` |

To pin harder, replace each `FROM tag` with `FROM tag@digest` from the table.
Do that from a fresh `imagetools inspect` rather than trusting this table
indefinitely: a tag can be repointed.

## Volumes

Four named volumes with explicit `name:` keys, so this task owns them and they
are not silently shared with another compose project:

| Volume | Mount | Holds |
|---|---|---|
| `afterlap-db` | `/var/lib/postgresql/data` | sessions, decisions, operator events, outbox, manifests |
| `afterlap-artifacts` | `/app/artifacts` | spool, exports, reports, content-addressed objects, staging |
| `afterlap-trajectories` | `/app/artifacts/trajectories` | Parquet recordings |
| `afterlap-models` | `/app/artifacts/models` | frozen model bundles |

The last two are nested mounts inside the first. That is deliberate: the
high-volume, recomputable trees can be sized, snapshotted and discarded without
touching operational evidence, which is the same ordering the disk-quota guard
enforces (`scripts/afterlap_ops/quota.py`).

`AFTERLAP_ROOT` is left unset in the image so `implementation_root()` resolves
to `/app`, which is why `configs/` reads from `/app/configs` and the volumes
mount over `/app/artifacts`. Setting `AFTERLAP_ROOT` would move the config
lookup too, and the configs are baked into the image, not into a volume.

## Measured on this machine

Windows 11 Home Single Language 10.0.26200, Intel64 Family 6 Model 183
Stepping 1 (24 logical CPUs), Docker 29.6.2 with Docker Compose v5.3.1 on the
WSL2 Linux backend (`Linux-6.18.33.2-microsoft-standard-WSL2-x86_64`), overlayfs.

| Measurement | Value |
|---|---|
| `afterlap/api:local` image size | 1.27 GB |
| `afterlap/web:local` image size | 101 MB |
| Cold start: `down -v` then `up -d --wait` to all-healthy | **13.41 s** |
| Full demo runbook through nginx (13 steps) | **2.81 s** and 2.95 s (two runs) |
| `POST /sessions/{id}/commands` `kind=step`, p50 | **77 ms** (min 61, max 91, n=8) |

Native Windows comparison, same runbook, same code, SQLite instead of
PostgreSQL:

| Measurement | Compose (Linux, PostgreSQL 17.7) | Native (Windows, SQLite) |
|---|---|---|
| Demo runbook, 13 steps | 2.81 s | **159.44 s** |
| `step` command p50 | 77 ms | **5 905 ms** |

That is a 77× difference on the operator command path, and it is not physics:
A08 measured `advance(1.0 s)` at about 56 ms in-process, which is most of the
77 ms container figure. The remaining ~5.85 s per step on the native path is
consistent with SQLite's `synchronous=FULL` fsync-per-commit on NTFS — several
commits happen per step (decision, outbox, session row) — but that attribution
was **not** isolated further and should not be quoted as a measured cause.

Two consequences worth acting on:

1. **Do not benchmark anything on the native Windows/SQLite path.** Numbers
   from it are dominated by commit latency and say nothing about the product.
2. The same run produced the **same snapshot hash** on both platforms
   (`sha256:eab94853b460759caf76c31cff1411a4687f1075ccf3a29ec4e2c8a52efdfd43`),
   so the simulation is bit-reproducible across Windows and Linux for this
   scenario and seed. That is one observation, not a determinism proof.

## Compose acceptance

`TECH_STACK.md`: *"Compose acceptance requires a working closed-loop synthetic
session, not just healthy containers."* Verified, in this order:

1. `up -d --wait` — db, api, batch and web all healthy; `migrate` exited 0
   having reported `alembic head: c04e287ba46c` and 19 tables on PostgreSQL.
2. `scripts/demo.py --base-url http://127.0.0.1:8080` — 13/13 steps, exit 0:
   a session reached an actionable instruction at t = 26 s, was selected,
   marked communicated, executed by the simulated driver at t = 26.35 s with
   `match_status=matched`, snapshotted, branched and exported.
3. The WebSocket upgraded **through nginx** (`ws://127.0.0.1:8080/api/v1/
   sessions/{id}/stream` reached state `OPEN` and delivered
   `resync_required` then heartbeats). This is the production analogue of
   coordinator decision D-07 defect 3, where the dev proxy carried `ws: true`
   only on the unused `/ws` rule.
4. The `batch` service claimed the queued experiment and completed it:
   `job exp-449864f00c3444b0 finished: status=completed partial=False
   units=['legal_fixed_schedule', 'legal_greedy_attacker']`, with a report at
   `/app/artifacts/reports/exp-449864f00c3444b0.json` whose hash matches the
   `report_hash` on the job row.

## Known limitations of this packaging

1. **The `batch` service's healthcheck is disabled.** It inherits the API
   image, whose healthcheck probes `/api/v1/health/ready`; the batch worker
   serves no HTTP. Disabling is better than a container permanently unhealthy
   for a reason nobody intends, but it means compose cannot tell you the batch
   worker has wedged. A real check would read its lease heartbeat.
2. **`deploy.resources.limits.cpus` on `batch` is a ceiling, not a
   reservation.** `ARCHITECTURE.md` asks that batch work "cannot consume the
   runtime's reserved CPU cores". A ceiling on the batch service is not the
   same as a reservation for the runtime: under contention the API still
   competes. Doing this properly needs `cpuset` pinning, which depends on the
   host's core count and is therefore not something this file can choose.
3. **No TLS, no authentication, no roles.** `AFTERLAP_ENV=production` disables
   the development bootstrap operator, which in this release means nobody can
   operate a session at all — the refusal is deliberate, and it is why the only
   supported mode is `development` on loopback.
4. **The API healthcheck uses `/health/ready`**, which currently reflects only
   process-level capabilities and not whether any session can actually decide
   (defect A14-4 in `handoffs/A14-integration-patch.md`). If that patch lands,
   revisit this healthcheck: a paused session would otherwise make the
   container unhealthy.
5. **`api.Dockerfile` runs the session runtime in the API process.** A08 §9.5:
   the out-of-process proxy is not written. The `batch` service is genuinely
   separate; the session runtime is not.
6. **Not verified on a clean machine.** Both images built and ran here, but no
   pull-and-run from a registry on a second host has been attempted, and the
   `uv` and `bun` layers need network access at build time.
7. **`docker compose down -v` deletes the audit trail.** There is no backup
   step in this packaging, and `ROLLBACK.md` in the release bundle assumes the
   database survives. A `pg_dump` sidecar is unbuilt.
