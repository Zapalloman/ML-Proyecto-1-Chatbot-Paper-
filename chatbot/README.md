# Pokédex Chatbot — Phase 2

Bilingual (Spanish / English) Pokémon Pokédex chatbot built with **prompt engineering + a local open LLM (via Ollama) + RAG** over data from [PokéAPI](https://pokeapi.co/), with a **SvelteKit** web frontend.

Phase 2 deliverable for **CINF104 Proyecto 1** — UNAB.

> **Status**: Phase 0 in progress (setup, model bench, ingest). See `.planning/phase-2/ROADMAP.md` for the full phased plan.

## Layout

```
chatbot/
├── data/      # SQLite Pokédex (built by ingest)  →  data/pokedex.sqlite
├── ingest/    # PokéAPI fetcher  →  python -m ingest.fetch_pokeapi
├── rag/       # document builder, embeddings, retriever (Phase 1)
├── server/    # FastAPI bridge between RAG and SvelteKit (Phase 2)
├── web/       # SvelteKit frontend + chat API route (Phase 2-3)
├── eval/      # bench script + 10-question evaluation set
└── docs/      # test report, domain slide, video script (Phase 4)
```

## Phase 0 — reproducible setup

### Prerequisites

- **Linux** with NVIDIA GPU + working `nvidia-smi` (CPU-only also works, slower).
  > If `nvidia-smi` reports `NVML library version mismatch`, the kernel modules and userland disagree (typical after `nvidia-utils` upgrade). Reboot fixes it.
- **Ollama** running on `localhost:11434` (`systemctl status ollama`).
- **Python 3.11+** (`.venv` is created locally).
- **Node 20+** (for Phase 2 onward; not needed for Phase 0).

### Steps

```bash
cd chatbot

# 1. Python deps
make setup

# 2. Pull candidate LLMs
ollama pull gemma3:4b
ollama pull qwen2.5:3b
ollama pull gemma3:1b

# 3. Ingest the National Pokédex from PokéAPI (~30-60 minutes; idempotent + resumable)
make ingest
# After completion: sqlite3 data/pokedex.sqlite "SELECT COUNT(*) FROM species" → 1025

# 4. Bench the candidate models against 5 standard prompts
make bench
# Writes: eval/model_selection.md  — pick winner per the rubric in
#         .planning/phase-2/MODEL-SELECTION.md
```

### Phase 0 done-when

- `data/pokedex.sqlite` has ≥ 1000 rows in `species` (target 1025)
- `eval/model_selection.md` exists and a winning model is declared
- `data/SCHEMA.md` documents the database

## Plan

The detailed phase-by-phase plan lives in `.planning/phase-2/`:

- `PROJECT.md` — context, requirements, decisions
- `ROADMAP.md` — Phase 0 → Phase 4 (with optional Phase 5)
- `MODEL-SELECTION.md` — model bench protocol

Each phase is a self-contained Claude Code session with explicit `INPUT` / `OUTPUT` contracts to keep token usage minimal across sessions.

## Data source

PokéAPI v2 (<https://pokeapi.co/>). Public, free for non-commercial use. The `make ingest` step caches all responses on disk under `data/raw_cache/` for reproducibility — re-runs hit the cache, not the network.
