export PATH := $(HOME)/.local/bin:$(PATH)
ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
BACKEND := $(ROOT)/backend
FRONTEND := $(ROOT)/frontend

.PHONY: install lint test test-live check-models cost-report e2e dev-backend dev-frontend

install:
	cd $(BACKEND) && uv sync --group dev
	if [ -f $(FRONTEND)/package.json ]; then cd $(FRONTEND) && npm install; fi

lint:
	cd $(BACKEND) && uv run ruff check app tests
	cd $(BACKEND) && uv run ruff format --check app tests || true
	cd $(BACKEND) && uv run mypy app || true

test:
	cd $(BACKEND) && uv run pytest -q -m "not live"

test-live:
	cd $(BACKEND) && uv run pytest -q -m live

check-models:
	cd $(BACKEND) && uv run python $(ROOT)/scripts/check_models.py

cost-report:
	cd $(BACKEND) && uv run python $(ROOT)/scripts/cost_report.py

e2e:
	cd $(BACKEND) && uv run pytest -q tests/e2e

dev-backend:
	cd $(BACKEND) && uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8765

dev-frontend:
	cd $(FRONTEND) && npm run dev -- --host 127.0.0.1 --port 5173
