# VOICES KG v2 — top-level orchestration
# =========================================================================

SHELL := /bin/bash
PY    := python3
DC    := docker compose

.PHONY: help env build filter load index precompute up down logs seed smoke check clean reset ps

help:
	@echo "VOICES KG v2 — Makefile targets"
	@echo ""
	@echo "  make env         Copy .env.example to .env (first run)"
	@echo "  make build       Re-materialize v2 KG (strip SFI, re-mint places)"
	@echo "  make filter      Alias for build"
	@echo "  make up          Start the full stack (Fuseki, Redis, Meilisearch, Admin, App, Caddy)"
	@echo "  make load        Upload v2 .nq/.nqs into Fuseki"
	@echo "  make index       Build Meilisearch + FAISS indexes"
	@echo "  make precompute  Produce dropdown/Overview JSON caches"
	@echo "  make seed        Create/ensure first admin user"
	@echo "  make smoke       Run end-to-end smoke tests"
	@echo "  make check       Verify the dataset is 100% thesaurus-free"
	@echo "  make all         build → check → up → load → index → precompute → seed → smoke"
	@echo "  make down        Stop stack"
	@echo "  make logs        Tail logs"
	@echo "  make ps          Service status"
	@echo "  make reset       Stop + wipe volumes (destructive)"

env:
	@[ -f .env ] || cp .env.example .env && echo "Created .env from .env.example — edit secrets before 'make up'"

build:
	$(PY) -m src.rebuild.filter
	$(PY) -m src.rebuild.relabel
	@echo "v2 KG built → output/kg2026_v2.nq"

filter: build

up:
	$(DC) up -d
	@echo "Stack starting. Caddy on https://localhost:$${CADDY_HTTPS_PORT:-8443}/ (self-signed)"

down:
	$(DC) down

logs:
	$(DC) logs -f --tail=200

ps:
	$(DC) ps

load:
	bash scripts/fuseki_load.sh

index:
	$(DC) exec admin python /app/admin/../scripts/index_meilisearch.py || $(PY) scripts/index_meilisearch.py
	$(PY) scripts/index_faiss.py

precompute:
	$(PY) scripts/precompute_caches.py

seed:
	$(DC) exec admin python -m admin.seed

smoke:
	bash scripts/smoke.sh

check:
	bash scripts/check_thesaurus_free.sh

all: build check up load index precompute seed smoke

reset:
	$(DC) down -v
	rm -rf output/*.nq output/*.nqs output/caches output/*.faiss output/*.ids.json
	@echo "Volumes and generated artefacts wiped."
