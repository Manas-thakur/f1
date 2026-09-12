.DEFAULT_GOAL := help
PYTHON := uv run python
CIRCUIT ?= silverstone
SEED ?= 42
CARS ?= 20
LAPS ?=
DURATION ?= 1800
STEPS ?= 10000
CONTACT_MODE ?= ignore
LINE_RANDOMNESS ?= 0.7
CORNER_LINE_STRENGTH ?= 0.9
LINE_WANDER_M ?= 0.8
LINE_LOOKAHEAD_M ?= 65
LINE_SMOOTHING_M ?= 30
RACING_LINE_FLAGS ?= --racing-line --corner-overtakes
OUTPUT ?= .afterlap/race/$(CIRCUIT)-$(SEED).jsonl
RACE_LINE_ARGS := --contact-mode $(CONTACT_MODE) --line-randomness $(LINE_RANDOMNESS) --corner-line-strength $(CORNER_LINE_STRENGTH) --line-wander-m $(LINE_WANDER_M) --line-lookahead-m $(LINE_LOOKAHEAD_M) --line-smoothing-m $(LINE_SMOOTHING_M) $(RACING_LINE_FLAGS)

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
	$(PYTHON) scripts/race.py serve --circuit $(CIRCUIT) --seed $(SEED) --cars $(CARS) $(if $(strip $(LAPS)),--laps $(LAPS)) --duration $(DURATION) $(RACE_LINE_ARGS)

race-generate:
	$(PYTHON) scripts/race.py generate --circuit $(CIRCUIT) --seed $(SEED) --cars $(CARS) $(if $(strip $(LAPS)),--laps $(LAPS)) --duration $(DURATION) $(RACE_LINE_ARGS) --output $(OUTPUT)

race-train:
	uv run --group learning python scripts/race.py train --circuit $(CIRCUIT) --seed $(SEED) --cars $(CARS) $(if $(strip $(LAPS)),--laps $(LAPS)) --duration $(DURATION) $(RACE_LINE_ARGS) --steps $(STEPS) --output .afterlap/race/policy-$(SEED)

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
