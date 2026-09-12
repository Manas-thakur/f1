from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

PROJECT = "afterlap"
PORTS_NAME = "ports.env"
ENV_NAME = ".env"
CONTAINER_BIND = "0.0.0.0"  # noqa: S104


def implementation_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in [here.parent, *here.parents]:
        if (candidate / "pyproject.toml").is_file() and (candidate / "infra").is_dir():
            return candidate
    return here.parents[1]


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line == "" or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'").strip('"')
    return values


def load_stack_env(root: Path) -> dict[str, str]:
    merged = parse_env_file(root / "infra" / PORTS_NAME)
    merged.update(parse_env_file(root / "infra" / ENV_NAME))
    merged.update({key: value for key, value in os.environ.items() if key.startswith("AFTERLAP_")})
    return merged


def require(env: dict[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if value == "":
        raise SystemExit(f"missing {key}; run `make env` first")
    return value


def python_env(env: dict[str, str], *, database_host: str, database_port: str) -> dict[str, str]:
    password = require(env, "AFTERLAP_DB_PASSWORD")
    return {
        "AFTERLAP_ENV": env.get("AFTERLAP_ENV", "development"),
        "AFTERLAP_DATABASE_URL": (
            f"postgresql+psycopg://afterlap:{password}@{database_host}:{database_port}/afterlap"
        ),
        "PYTHONUNBUFFERED": "1",
        "AFTERLAP_EXPERIMENT_QUOTA_BYTES": env.get("AFTERLAP_EXPERIMENT_QUOTA_BYTES", "2147483648"),
        "AFTERLAP_OPERATIONAL_RESERVE_BYTES": env.get("AFTERLAP_OPERATIONAL_RESERVE_BYTES", "268435456"),
    }


def artifact_volumes() -> list[dict[str, str]]:
    return [
        {"name": "artifacts", "target": "/app/artifacts"},
        {"name": "trajectories", "target": "/app/artifacts/trajectories"},
        {"name": "models", "target": "/app/artifacts/models"},
    ]


def build_manifest(root: Path, env: dict[str, str]) -> dict[str, Any]:
    web_port = require(env, "AFTERLAP_WEB_PORT")
    api_port = require(env, "AFTERLAP_API_PORT")
    db_port = require(env, "AFTERLAP_DB_PORT")
    gateway = env.get("AFTERLAP_AC_GATEWAY", "192.168.64.1").strip() or "192.168.64.1"
    password = require(env, "AFTERLAP_DB_PASSWORD")
    shared = python_env(env, database_host=gateway, database_port=db_port)
    return {
        "name": PROJECT,
        "description": "AFTERLAP local product stack: PostgreSQL, runtime, batch worker, Next.js.",
        "root": str(root),
        "profiles": {
            "local": {
                "platform": "linux/arm64",
                "push": False,
                "tag": "local",
                "registry": "",
            }
        },
        "builds": [
            {
                "name": "api",
                "dockerfile": "infra/api.Dockerfile",
                "context": ".",
                "image": "afterlap-api",
                "tags": ["local"],
            },
            {
                "name": "web",
                "dockerfile": "infra/web.Dockerfile",
                "context": ".",
                "image": "afterlap-web",
                "tags": ["local"],
            },
        ],
        "services": [
            {
                "name": "db",
                "image": "docker.io/library/postgres:17.7-alpine",
                "cpus": 2,
                "memory": "1g",
                "ports": [f"{db_port}:5432"],
                "env": {
                    "POSTGRES_DB": "afterlap",
                    "POSTGRES_USER": "afterlap",
                    "POSTGRES_PASSWORD": password,
                    "POSTGRES_INITDB_ARGS": "--encoding=UTF8 --locale=C",
                    "PGDATA": "/var/lib/postgresql/data/pgdata",
                },
                "volumes": [{"name": "db", "target": "/var/lib/postgresql/data"}],
                "readyCmd": ["pg_isready", "-U", "afterlap", "-d", "afterlap"],
                "readyTimeout": 90,
            },
            {
                "name": "runtime",
                "image": "afterlap-api:local",
                "cpus": 4,
                "memory": "4g",
                "ports": [f"{api_port}:8000"],
                "env": {
                    **shared,
                    "AFTERLAP_HOST": CONTAINER_BIND,
                    "AFTERLAP_PORT": "8000",
                    "AFTERLAP_RUNTIME_URL": "http://127.0.0.1:8000",
                },
                "volumes": artifact_volumes(),
                "args": [
                    "python",
                    "-m",
                    "afterlap_api.cli",
                    "serve",
                    "--host",
                    CONTAINER_BIND,
                    "--port",
                    "8000",
                ],
                "readyCmd": ["python", "-m", "afterlap_api.cli", "request", "GET", "/api/v1/health/ready"],
                "readyTimeout": 180,
            },
            {
                "name": "batch",
                "image": "afterlap-api:local",
                "cpus": 2,
                "memory": "2g",
                "env": shared,
                "volumes": artifact_volumes(),
                "args": ["python", "/app/scripts/batch_worker_main.py", "--poll-interval", "2.0"],
                "readyCmd": ["python", "/app/scripts/batch_worker_main.py", "--healthcheck"],
                "readyTimeout": 120,
            },
            {
                "name": "web",
                "image": "afterlap-web:local",
                "cpus": 2,
                "memory": "2g",
                "ports": [f"{web_port}:8080"],
                "env": {
                    "AFTERLAP_RUNTIME_URL": f"http://{gateway}:{api_port}",
                    "AFTERLAP_AUTOSTART_RUNTIME": "0",
                    "PORT": "8080",
                    "HOSTNAME": CONTAINER_BIND,
                },
                "readyCmd": [
                    "python",
                    "-c",
                    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/', timeout=4)",
                ],
                "readyTimeout": 120,
            },
        ],
        "scripts": {
            "demo": (f"uv run python scripts/demo.py --base-url http://127.0.0.1:{web_port}"),
            "psql": f"psql -h 127.0.0.1 -p {db_port} -U afterlap afterlap",
        },
    }


def default_manifest_path() -> Path:
    return Path.home() / ".config" / "ac" / "projects" / f"{PROJECT}.json"


def write_manifest(path: Path | None = None) -> Path:
    root = implementation_root()
    env = load_stack_env(root)
    target = path or default_manifest_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = build_manifest(root, env)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def main() -> None:
    written = write_manifest()
    print(written)


if __name__ == "__main__":
    main()
