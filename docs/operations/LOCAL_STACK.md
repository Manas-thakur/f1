# Local stack

Start the product from the repository root with Make. The Makefile is the
orchestration entry point. It writes `infra/.env`, installs the `ac` project
manifest, builds images, and starts PostgreSQL, the Python runtime, the batch
worker, and Next.js.

Apple `container` via `ac` is the local runtime on this machine. The Compose
file under `infra/docker-compose.yml` is the Linux service catalog and uses
the same host ports. `make compose-up` calls docker compose when `docker` is
installed; otherwise it tells you to use `make up`.

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

`make up` renders `~/.config/ac/projects/afterlap.json` from the current
checkout and `infra/.env`, builds `afterlap-api:local` and `afterlap-web:local`,
then `ac afterlap start`. Services start in order, each gated on `readyCmd`.

`make dev` is the native path: PostgreSQL via `ac`, Python and Next.js on the
host using the same unique ports. `make stop-dev` stops those two processes
and leaves postgres running.

`make doctor` and `make migrate` wrap the existing Python CLIs.

## Files

| Path | Role |
|---|---|
| `Makefile` | Start, stop, logs, demo, native, compose fallback |
| `infra/ports.env` | Committed host ports |
| `infra/.env.example` | Password-less template |
| `infra/docker-compose.yml` | Linux compose catalog, same ports |
| `scripts/afterlap_ops/stack_manifest.py` | Renders the `ac` project manifest |

## Inter-container reachability

Apple containers do not use Compose DNS names. The rendered `ac` manifest
points runtime and batch at PostgreSQL, and Next.js at the runtime, through
`AFTERLAP_AC_GATEWAY` (default `192.168.64.1`) plus the unique host ports.
Override that gateway in `infra/.env` if the vmnet address differs.
