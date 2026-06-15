# VOICES KG v2 — top-level orchestration
# =========================================================================

SHELL := /bin/bash
PY    := python3
DC    := docker compose

.PHONY: help env build filter load index precompute up down logs seed smoke check clean reset ps \
        pipeline-deps pipeline-sample build-from-transcripts

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

# ── Construction pipeline (transcripts → KG); see pipeline/README.md ──────────
pipeline-deps:
	$(PY) -m pip install -r pipeline/requirements.txt

# Standalone smoke build on the bundled SYNTHETIC sample — no gated inputs,
# no OpenAI, no SFI thesaurus. Produces pipeline/sample/output/kg2026_paper.nq.
pipeline-sample:
	cd pipeline && $(PY) sample/make_sample.py
	cd pipeline && $(PY) src/build.py --config config/config.sample.yaml
	@echo "Toy KG built → pipeline/sample/output/kg2026_paper.nq"

# Full build from YOUR OWN VHA XML transcripts (requires OPENAI_API_KEY; the SFI
# thesaurus is optional — without it places are minted locally with no outward
# GeoNames/Wikidata links). Usage: make build-from-transcripts XML=/path/to/xml
build-from-transcripts:
	@[ -n "$(XML)" ] || { echo "Set XML=/path/to/xml/transcripts"; exit 2; }
	@[ -n "$$OPENAI_API_KEY" ] || { echo "Set OPENAI_API_KEY in the environment"; exit 2; }
	cd pipeline && $(PY) stage1_parse/parse_transcripts.py --transcripts-dir "$(XML)" --output-dir sample/data/processed
	cd pipeline && $(PY) stage1_parse/create_utterances_v2.py --source sample/data/processed/utterances.parquet --target sample/data/processed/utterances_v2.parquet
	cd pipeline && $(PY) stage2_extract/event_extractor_v6.py
	cd pipeline && $(PY) scripts/resolve_events_v7.py
	cd pipeline && $(PY) src/build.py --config config/config.yaml
	@echo "KG built from transcripts → pipeline/sample/output/  (load into Fuseki with 'make up load')"

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
