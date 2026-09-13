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
POLICY ?=
TRAINING_OUTPUT ?= .afterlap/race/boost-policy
METRICS ?= $(TRAINING_OUTPUT).metrics.json
HOST ?= http://127.0.0.1:18760
GPIO ?= 17
CYCLES ?= 5
EVAL_EPISODES ?= 3
DECISION_CARS ?= 6
DECISION_DURATION ?= 60
RACE_LINE_ARGS := --contact-mode $(CONTACT_MODE) --line-randomness $(LINE_RANDOMNESS) --corner-line-strength $(CORNER_LINE_STRENGTH) --line-wander-m $(LINE_WANDER_M) --line-lookahead-m $(LINE_LOOKAHEAD_M) --line-smoothing-m $(LINE_SMOOTHING_M) $(RACING_LINE_FLAGS)

.PHONY: help install dev race race-server race-generate race-train race-train-decision race-evaluate-decision race-status race-boost race-boost-off race-button race-check race-browser-check race-up race-down
help:
	@echo "make install             Install Python and web dependencies"
	@echo "make race (or make dev)  Start simulator and dashboard on port 18760"
	@echo "make race-server         Start only the WebSocket simulator"
	@echo "make race-generate       Write RL transitions as JSONL"
	@echo "make race-train          Train and save a PPO policy"
	@echo "make race-train-decision Train the boost recommendation PPO policy"
	@echo "make race-evaluate-decision Evaluate a saved boost policy"
	@echo "make race-status         Read live recommendation telemetry through Next.js"
	@echo "make race-boost          Apply the live recommendation through Next.js"
	@echo "make race-boost-off      Return energy deployment to automatic"
	@echo "make race-button         Run the GPIO boost button with file logging"
	@echo "make race-check          Run physics tests, lint, and type checks"
	@echo "make race-browser-check  Test the live dashboard and port forwarding"
	@echo "make race-up / race-down Start or stop the Docker simulator"

install:
	uv sync --frozen --all-packages
	bun install --frozen-lockfile

dev: race

race:
	$(if $(strip $(POLICY)),RACE_POLICY=$(POLICY) RACE_METRICS=$(METRICS),) $(PYTHON) scripts/race_stack.py

race-server:
	$(PYTHON) scripts/race.py serve --circuit $(CIRCUIT) --seed $(SEED) --cars $(CARS) $(if $(strip $(LAPS)),--laps $(LAPS)) --duration $(DURATION) $(RACE_LINE_ARGS) $(if $(strip $(POLICY)),--policy $(POLICY) --metrics $(METRICS))

race-generate:
	$(PYTHON) scripts/race.py generate --circuit $(CIRCUIT) --seed $(SEED) --cars $(CARS) $(if $(strip $(LAPS)),--laps $(LAPS)) --duration $(DURATION) $(RACE_LINE_ARGS) --output $(OUTPUT)

race-train:
	uv run --group learning python scripts/race.py train --circuit $(CIRCUIT) --seed $(SEED) --cars $(CARS) $(if $(strip $(LAPS)),--laps $(LAPS)) --duration $(DURATION) $(RACE_LINE_ARGS) --steps $(STEPS) --output .afterlap/race/policy-$(SEED)

race-train-decision:
	uv run --group learning python scripts/race.py train-decision --circuit $(CIRCUIT) --seed $(SEED) --cars $(DECISION_CARS) $(if $(strip $(LAPS)),--laps $(LAPS)) --duration $(DECISION_DURATION) $(RACE_LINE_ARGS) --steps $(STEPS) --cycles $(CYCLES) --eval-episodes $(EVAL_EPISODES) --output $(TRAINING_OUTPUT)

race-evaluate-decision:
	uv run --group learning python scripts/race.py evaluate-decision --circuit $(CIRCUIT) --seed $(SEED) --cars $(DECISION_CARS) $(if $(strip $(LAPS)),--laps $(LAPS)) --duration $(DECISION_DURATION) $(RACE_LINE_ARGS) --policy $(if $(strip $(POLICY)),$(POLICY),$(TRAINING_OUTPUT)) --eval-episodes $(EVAL_EPISODES)

race-status:
	$(PYTHON) scripts/race_control.py status

race-boost:
	$(PYTHON) scripts/race_control.py boost

race-boost-off:
	$(PYTHON) scripts/race_control.py boost-off

race-button:
	HOST=$(HOST) BOOST_GPIO=$(GPIO) python3 scripts/button_command.py

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
