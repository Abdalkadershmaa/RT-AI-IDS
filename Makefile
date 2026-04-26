.PHONY: help bootstrap install lint format typecheck test test-unit test-integration \
        compose-up compose-down compose-logs migrate clean

PYTHON ?= python3
COMPOSE ?= docker compose

help:
	@echo "Targets:"
	@echo "  bootstrap        Generate a .env with safe random secrets (idempotent: skips if .env exists)"
	@echo "  install          Install dev + runtime dependencies"
	@echo "  lint             Run ruff check"
	@echo "  format           Run ruff format + black"
	@echo "  typecheck        Run mypy"
	@echo "  test             Run pytest"
	@echo "  compose-up       Build and start all services"
	@echo "  compose-down     Stop and remove all services"
	@echo "  compose-logs     Follow logs for all services"
	@echo "  migrate          Run Alembic migrations against DATABASE_URL"

bootstrap:
	@if [ -f .env ]; then \
		echo ".env already exists. Refusing to overwrite. Delete it first if you want to regenerate."; \
		exit 1; \
	fi
	@cp .env.example .env
	@SECRET=$$($(PYTHON) -c "import secrets; print(secrets.token_urlsafe(48))"); \
	JWT=$$($(PYTHON) -c "import secrets; print(secrets.token_urlsafe(48))"); \
	ADMIN_PW=$$($(PYTHON) -c "import secrets; print(secrets.token_urlsafe(24))"); \
	sed -i.bak "s|^SECRET_KEY=.*|SECRET_KEY=$$SECRET|" .env && \
	sed -i.bak "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$$JWT|" .env && \
	sed -i.bak "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=$$ADMIN_PW|" .env && \
	rm -f .env.bak
	@echo ".env generated with random SECRET_KEY, JWT_SECRET_KEY, ADMIN_PASSWORD."
	@echo "Admin credentials:"
	@grep -E '^ADMIN_(USERNAME|PASSWORD)=' .env

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install ruff==0.6.9 black==24.10.0 mypy==1.11.2 pre-commit==3.8.0

lint:
	ruff check .

format:
	ruff format .
	ruff check . --fix

typecheck:
	mypy services shared

test:
	$(PYTHON) -m pytest

test-unit:
	$(PYTHON) -m pytest tests/unit

test-integration:
	$(PYTHON) -m pytest tests/integration

compose-up:
	$(COMPOSE) up --build -d

compose-down:
	$(COMPOSE) down -v

compose-logs:
	$(COMPOSE) logs -f --tail=200

migrate:
	$(PYTHON) -m alembic -c shared/db/migrations/alembic.ini upgrade head

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov dist build *.egg-info
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +
