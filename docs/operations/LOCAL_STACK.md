# Local stack

Start the product from the repository root with Make. The Makefile is the
orchestration entry point. It writes `infra/.env`, builds images, and starts
PostgreSQL, the Python runtime, the batch worker, and Next.js.

Docker compose runs the stack. `infra/docker-compose.yml` is the single
service catalog, and every Make target is a thin wrapper over
`docker compose -f infra/docker-compose.yml --env-file infra/.env`. Docker
with the compose plugin is the only prerequisite beyond `uv` and `bun`.

## Ports

Host publishes are uncommon on purpose so they do not collide with 3000, 8000,
8080, 5432, or 5433. They are fixed in `infra/ports.env`, not rolled per start,
so bookmarks and scripts stay stable.

| Surface | Address |
|---|---|
| Engineer console (Next.js) | http://127.0.0.1:18473 |
| API through Next.js | http://127.0.0.1:18473/api/v1 |
| Session stream | http://127.0.0.1:18473/api/v1/sessions/{id}/stream |
| Python runtime (CLI IPC, not HTTP) | 127.0.0.1:19284 |
| PostgreSQL | 127.0.0.1:17539 |

Inside containers the runtime still listens on 8000 and Next.js on 8080. Only
the host mapping changed. All host publishes bind loopback. There is no
authentication in this release, so nothing here may be exposed on a routable
interface.

## Commands

```
make env
make up
make urls
make demo
make down
```

`make env` creates `infra/.env` with a generated `AFTERLAP_DB_PASSWORD` when
the file is missing. There is still no default password in git.

`make up` builds `afterlap/api:local` and `afterlap/web:local`, then runs
`docker compose up --build --detach --wait`. The database comes up first, the
migration job runs to completion, and runtime, batch and web follow, each
gated on its healthcheck.

Every stack target writes `infra/.env` first, so `make ps`, `make down`,
`make stop`, `make logs` and `make wait` work on a fresh checkout.

`make dev` is the native path: PostgreSQL in compose, Python and Next.js on
the host using the same unique ports. `make stop-dev` stops those two
processes and leaves postgres running.

`make doctor` and `make migrate` wrap the existing Python CLIs.

## Files

| Path | Role |
|---|---|
| `Makefile` | Start, stop, logs, demo, native |
| `infra/ports.env` | Committed host ports |
| `infra/.env.example` | Password-less template |
| `infra/docker-compose.yml` | The service catalog: db, migrate, runtime, batch, web |

## Inter-container reachability

Compose puts every service on one network and resolves them by service name.
Runtime and batch reach PostgreSQL at `db:5432` and Next.js reaches the
runtime at `runtime:8000`, so the host ports above are for you, not for the
containers.
