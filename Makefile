THIS_MAKEFILE := $(abspath $(firstword $(MAKEFILE_LIST)))
ROOT := $(patsubst %/,%,$(dir $(THIS_MAKEFILE)))
include $(ROOT)/infra/ports.env

ENV_FILE := $(ROOT)/infra/.env
STATE := $(ROOT)/.afterlap
AC_PROJECT := afterlap
PYTHON := uv run python
WEB_URL := http://127.0.0.1:$(AFTERLAP_WEB_PORT)
API_URL := http://127.0.0.1:$(AFTERLAP_API_PORT)
DB_ADDR := 127.0.0.1:$(AFTERLAP_DB_PORT)

export AFTERLAP_WEB_PORT
export AFTERLAP_API_PORT
export AFTERLAP_DB_PORT
export AFTERLAP_AC_GATEWAY

.DEFAULT_GOAL := help

.PHONY: help env install-ac build up down stop start restart logs ps wait urls doctor demo migrate install dev stop-dev compose-up compose-down

help:
	@printf '%s\n' \
	  'AFTERLAP local stack. Host ports: web $(AFTERLAP_WEB_PORT), runtime $(AFTERLAP_API_PORT), postgres $(AFTERLAP_DB_PORT).' \
	  '' \
	  'make env          write infra/.env with a generated password if missing' \
	  'make up           build images and start db, runtime, batch, web via ac' \
	  'make down         stop and remove containers; volumes stay' \
	  'make stop         stop containers in place' \
	  'make start        start an already-created stack' \
	  'make restart      restart the stack' \
	  'make logs         follow container logs' \
	  'make ps           show container status' \
	  'make wait         block until every readyCmd passes' \
	  'make urls         print loopback addresses' \
	  'make doctor       run afterlap_core.cli doctor' \
	  'make demo         run the 13-step live runbook against $(WEB_URL)' \
	  'make migrate      alembic upgrade against the stack database' \
	  'make install      uv and bun frozen installs' \
	  'make dev          native runtime + web on the unique ports, postgres via ac' \
	  'make stop-dev     stop native runtime/web/batch started by make dev' \
	  'make compose-up   Linux docker compose path (not used on this machine)' \
	  'make compose-down stop the docker compose project'

env:
	@if [ ! -f "$(ENV_FILE)" ]; then \
	  password="$$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"; \
	  printf '%s\n' \
	    "AFTERLAP_DB_PASSWORD=$$password" \
	    "AFTERLAP_ENV=development" \
	    "AFTERLAP_WEB_PORT=$(AFTERLAP_WEB_PORT)" \
	    "AFTERLAP_API_PORT=$(AFTERLAP_API_PORT)" \
	    "AFTERLAP_DB_PORT=$(AFTERLAP_DB_PORT)" \
	    "AFTERLAP_EXPERIMENT_QUOTA_BYTES=2147483648" \
	    "AFTERLAP_OPERATIONAL_RESERVE_BYTES=268435456" \
	    "AFTERLAP_BATCH_CPUS=2.0" \
	    > "$(ENV_FILE)"; \
	  echo "wrote $(ENV_FILE)"; \
	fi

install-ac: env
	@$(PYTHON) scripts/afterlap_ops/stack_manifest.py

build: install-ac
	ac $(AC_PROJECT) build

up: install-ac
	ac $(AC_PROJECT) build
	ac $(AC_PROJECT) start
	@$(MAKE) urls

down:
	ac $(AC_PROJECT) down

stop:
	ac $(AC_PROJECT) stop

start: install-ac
	ac $(AC_PROJECT) start
	@$(MAKE) urls

restart: install-ac
	ac $(AC_PROJECT) restart
	@$(MAKE) urls

logs:
	ac $(AC_PROJECT) logs -f

ps:
	ac $(AC_PROJECT) ls

wait:
	ac $(AC_PROJECT) wait

urls:
	@printf '%s\n' \
	  "engineer console  $(WEB_URL)" \
	  "api via next      $(WEB_URL)/api/v1" \
	  "session stream    $(WEB_URL)/api/v1/sessions/<id>/stream" \
	  "python runtime    $(API_URL)" \
	  "postgres          $(DB_ADDR)"

doctor:
	$(PYTHON) -m afterlap_core.cli doctor

demo: env
	$(PYTHON) scripts/demo.py --base-url $(WEB_URL)

migrate: env
	set -a && . "$(ENV_FILE)" && set +a && \
	AFTERLAP_DATABASE_URL="postgresql+psycopg://afterlap:$${AFTERLAP_DB_PASSWORD}@127.0.0.1:$(AFTERLAP_DB_PORT)/afterlap" \
	$(PYTHON) scripts/migrate.py --wait-for-database 60

install:
	uv sync --frozen --all-packages
	bun install --frozen-lockfile

dev: env install-ac
	@command -v ac >/dev/null
	ac $(AC_PROJECT) start db
	ac $(AC_PROJECT) wait db
	@$(MAKE) migrate
	@mkdir -p "$(STATE)"
	@set -a && . "$(ENV_FILE)" && set +a && \
	  AFTERLAP_ENV=development \
	  AFTERLAP_HOST=127.0.0.1 \
	  AFTERLAP_PORT=$(AFTERLAP_API_PORT) \
	  AFTERLAP_RUNTIME_URL=$(API_URL) \
	  AFTERLAP_DATABASE_URL="postgresql+psycopg://afterlap:$${AFTERLAP_DB_PASSWORD}@127.0.0.1:$(AFTERLAP_DB_PORT)/afterlap" \
	  $(PYTHON) -m afterlap_api.cli serve --host 127.0.0.1 --port $(AFTERLAP_API_PORT) \
	  >"$(STATE)/runtime.log" 2>&1 & echo $$! >"$(STATE)/runtime.pid"
	@set -a && . "$(ENV_FILE)" && set +a && \
	  AFTERLAP_ENV=development \
	  AFTERLAP_AUTOSTART_RUNTIME=0 \
	  AFTERLAP_RUNTIME_URL=$(API_URL) \
	  bun run --filter @afterlap/web dev \
	  >"$(STATE)/web.log" 2>&1 & echo $$! >"$(STATE)/web.pid"
	@$(MAKE) urls
	@echo "native logs: $(STATE)/runtime.log $(STATE)/web.log"

stop-dev:
	@if [ -f "$(STATE)/web.pid" ]; then kill "$$(cat "$(STATE)/web.pid")" 2>/dev/null || true; rm -f "$(STATE)/web.pid"; fi
	@if [ -f "$(STATE)/runtime.pid" ]; then kill "$$(cat "$(STATE)/runtime.pid")" 2>/dev/null || true; rm -f "$(STATE)/runtime.pid"; fi
	@echo "native processes stopped; postgres is still the ac db service (make down to stop it)"

compose-up: env
	@if ! command -v docker >/dev/null 2>&1; then \
	  echo "docker is not installed; use make up (Apple container via ac)"; \
	  exit 1; \
	fi
	docker compose -f infra/docker-compose.yml --env-file "$(ENV_FILE)" up --build -d --wait
	@$(MAKE) urls

compose-down:
	@if ! command -v docker >/dev/null 2>&1; then \
	  echo "docker is not installed; use make down"; \
	  exit 1; \
	fi
	docker compose -f infra/docker-compose.yml --env-file "$(ENV_FILE)" down
