# Pokédex Chatbot — Phase 2
# Run from chatbot/ directory.

PY ?= python3
VENV ?= .venv
PIP := $(VENV)/bin/pip
PYTHON := $(VENV)/bin/python

DATA_DIR := data
DB := $(DATA_DIR)/pokedex.sqlite

.PHONY: help setup ingest index rag dev web web-install bench test-rag clean

help:
	@echo "Pokédex Chatbot — make targets:"
	@echo "  make setup        - create venv and install Python deps"
	@echo "  make ingest       - download PokéAPI -> $(DB)"
	@echo "  make index        - build RAG vector index over $(DB)"
	@echo "  make web-install  - install SvelteKit dependencies (one-off)"
	@echo "  make rag          - run FastAPI RAG bridge on :8001 (foreground)"
	@echo "  make dev          - run SvelteKit dev server (web/) on :5173"
	@echo "  make test-rag     - smoke-test the retriever (requires the index)"
	@echo "  make bench        - run optional model bench (Phase 0 F0.3, kept as smoke test)"
	@echo "  make clean        - remove venv and caches (keeps $(DB))"
	@echo
	@echo "Typical local flow (3 terminals):"
	@echo "  T1:  make rag"
	@echo "  T2:  make dev"
	@echo "  T3:  curl -N localhost:5173/api/chat ..."

$(VENV)/bin/python:
	$(PY) -m venv $(VENV)
	$(PIP) install --upgrade pip wheel

setup: $(VENV)/bin/python
	$(PIP) install -r requirements.txt

ingest: setup
	$(PYTHON) -m ingest.fetch_pokeapi --db $(DB)

index: setup
	$(PYTHON) -m rag.build_index --db $(DB)

rag: setup
	$(PYTHON) -m server.rag_api --db $(DB)

web-install:
	cd web && npm install

dev:
	cd web && npm run dev

test-rag: setup
	$(PYTHON) -m rag.test_retrieval

bench:
	$(PYTHON) -m eval.bench_models

clean:
	rm -rf $(VENV) **/__pycache__ .pytest_cache
