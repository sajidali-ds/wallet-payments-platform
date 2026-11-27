SHELL := /bin/bash
.DEFAULT_GOAL := help

# Load .env so the Makefile (and anything it runs) sees the same values as docker compose.
-include .env
export

POSTGRES_PORT ?= 5432
RABBITMQ_PORT ?= 5672
REDIS_PORT ?= 6379
VENV := $(CURDIR)/.venv
SERVICES := auth-service wallet-service notification-service
DB_HOST_URL := postgresql://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@localhost:$(POSTGRES_PORT)
RABBITMQ_HOST_URL := amqp://$(RABBITMQ_DEFAULT_USER):$(RABBITMQ_DEFAULT_PASS)@localhost:$(RABBITMQ_PORT)/
REDIS_TEST_URL := redis://localhost:$(REDIS_PORT)/15
DB ?= auth_db
COMPOSE_LOAD := docker compose -f docker-compose.yml -f docker-compose.loadtest.yml

.PHONY: frontend-install frontend-dev frontend-test frontend-build help init-env secret check-env install infra-up up down reset logs ps psql create-admin test test-unit lint format gateway-check smoke loadtest-up loadtest loadtest-report verify test-scripts

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

init-env: ## Create .env from .env.example (never overwrites)
	@if [ -f .env ]; then echo ".env already exists"; else cp .env.example .env && echo "Created .env - now set JWT_SECRET (make secret) and the passwords"; fi

secret: ## Print a random value suitable for JWT_SECRET
	@python3 -c "import secrets; print(secrets.token_urlsafe(48))"

check-env:
	@test -f .env || (echo "Missing .env - run: make init-env" && exit 1)
	@if grep -qiE 'change[-_]me' .env; then echo ".env still contains placeholder values (change_me...). Set real passwords and a JWT_SECRET (make secret)." >&2; exit 1; fi

install: ## Create .venv and install dev dependencies (needs Python 3.12)
	python3 -m venv .venv
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install $(foreach s,$(SERVICES),-r services/$(s)/requirements-dev.txt)

infra-up: check-env ## Start only Postgres, Redis, RabbitMQ and wait until healthy
	docker compose up -d --wait postgres redis rabbitmq

up: check-env ## Build and start everything
	docker compose up -d --build --wait

down: ## Stop everything (data is kept)
	docker compose down

reset: ## Stop everything AND delete all data volumes
	docker compose down -v

logs: ## Follow logs from all containers
	docker compose logs -f --tail=100

ps: ## Show container status
	docker compose ps

psql: check-env ## Open psql (default auth_db; e.g. make psql DB=wallet_db)
	docker compose exec postgres psql -U $(POSTGRES_USER) -d $(DB)

create-admin: check-env ## Create/promote an admin: make create-admin EMAIL=admin@example.com
	@test -n "$(EMAIL)" || (echo "Usage: make create-admin EMAIL=admin@example.com" && exit 1)
	docker compose exec auth-service python -m app.create_admin --email $(EMAIL)

test-unit: ## Unit tests only (no database or broker needed)
	@set -e; for s in $(SERVICES); do echo "== $$s"; (cd services/$$s && $(VENV)/bin/pytest -m "not integration"); done

test: check-env infra-up ## All tests (unit + integration against real Postgres, RabbitMQ and Redis)
	@set -e; for s in $(SERVICES); do echo "== $$s"; (cd services/$$s && TEST_DATABASE_URL=$(DB_HOST_URL)/$${s%-service}_test_db TEST_RABBITMQ_URL=$(RABBITMQ_HOST_URL) TEST_REDIS_URL=$(REDIS_TEST_URL) $(VENV)/bin/pytest); done

lint: ## ruff lint + format check
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

format: ## Auto-format and auto-fix
	$(VENV)/bin/ruff format .
	$(VENV)/bin/ruff check --fix .

frontend-install: ## Install the web app's npm dependencies (needs Node 20.19+)
	cd frontend && npm install

frontend-dev: ## Run the web app with hot reload on http://localhost:5173 (stack must be up; API paths proxy to the gateway)
	cd frontend && npm run dev

frontend-test: ## Typecheck and unit-test the web app
	cd frontend && npm run typecheck && npm test

frontend-build: ## Production build of the web app into frontend/dist
	cd frontend && npm run build

gateway-check: ## Validate gateway/nginx.conf with nginx -t (needs Docker, no stack required)
	docker run --rm -v $(CURDIR)/gateway/nginx.conf:/etc/nginx/nginx.conf:ro nginx:1.27-alpine nginx -t

smoke: check-env ## End-to-end check through the gateway, incl. request-id tracing (stack must be up)
	bash scripts/smoke.sh

test-scripts: ## Unit tests of the helper scripts (load-test report generator)
	python3 -m unittest discover -s scripts/tests -v

loadtest-up: check-env ## Start the stack with per-user rate limits relaxed and quiet logs
	$(COMPOSE_LOAD) up -d --build --wait

loadtest: check-env ## Run the k6 load test: ADMIN_EMAIL=... ADMIN_PASSWORD=... [USERS=50 TRANSFER_RATE=50 ...] make loadtest
	@test -n "$$ADMIN_EMAIL" && test -n "$$ADMIN_PASSWORD" || (echo "Usage: ADMIN_EMAIL=... ADMIN_PASSWORD=... make loadtest   (create the admin first: make create-admin EMAIL=...)" && exit 1)
	$(COMPOSE_LOAD) run --rm k6 run /loadtests/k6/transfer.js

loadtest-report: ## Markdown results table from the last k6 run
	python3 scripts/loadtest_report.py

verify: check-env ## SQL consistency checks: ledger sums to zero, no negative balances, events delivered once
	bash scripts/verify_consistency.sh
