.DEFAULT_GOAL := help
PYTHON := uv run python
CIRCUIT ?= silverstone
SEED ?= 42
CARS ?= 20
LAPS ?= 3
DURATION ?= 1800
STEPS ?= 10000
WORKERS ?= 1
ROLLOUT_STEPS ?= 128
BATCH_SIZE ?= 64
OUTPUT ?= .afterlap/race/$(CIRCUIT)-$(SEED).jsonl

.PHONY: help install dev race race-server race-generate race-train race-check race-browser-check race-up race-down
help:
	@echo "make install             Install Python and web dependencies"
	@echo "make race (or make dev)  Start simulator and dashboard on port 18760"
	@echo "make race-server         Start only the WebSocket simulator"
	@echo "make race-generate       Write RL transitions as JSONL"
	@echo "make race-train          Train and save a PPO policy"
	@echo "make race-check          Run physics tests, lint, and type checks"
	@echo "make race-browser-check  Test the live dashboard and port forwarding"
	@echo "make race-up / race-down Start or stop the Docker simulator"

install:
	uv sync --frozen --all-packages
	bun install --frozen-lockfile

dev: race

race:
	$(PYTHON) scripts/race_stack.py

race-server:
	$(PYTHON) scripts/race.py serve

race-generate:
	$(PYTHON) scripts/race.py generate --circuit $(CIRCUIT) --seed $(SEED) --cars $(CARS) --laps $(LAPS) --duration $(DURATION) --output $(OUTPUT)

race-train:
	uv run --group learning python scripts/race.py train --circuit $(CIRCUIT) --seed $(SEED) --cars $(CARS) --laps $(LAPS) --duration $(DURATION) --steps $(STEPS) --workers $(WORKERS) --rollout-steps $(ROLLOUT_STEPS) --batch-size $(BATCH_SIZE) --output .afterlap/race/policy-$(SEED)

race-check:
	uv run pytest
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy
	uv run python scripts/check_no_comments.py
	bun run typecheck
	bun run lint

race-browser-check:
	cd apps/web && bunx playwright test --config playwright.race.config.ts

race-up:
	docker compose -f infra/race-compose.yml up --build --detach --wait

race-down:
	docker compose -f infra/race-compose.yml down
