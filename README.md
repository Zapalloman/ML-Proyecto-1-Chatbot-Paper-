# CINF104 Proyecto 1 — Pokédex Chatbot + DRG Paper

This repository contains two deliverables:

| Path        | Deliverable                                                                 |
|-------------|------------------------------------------------------------------------------|
| `chatbot/`  | Bilingual (es/en) Pokédex chatbot — local LLM via Ollama + RAG + SvelteKit. |
| `paper/`    | LaTeX report (`paper/main.pdf`) plus its sources (`figures/`, `tables/`, `references/`). |

---

## Running the chatbot

### Prerequisites

- **Python 3.11+**
- **Node 20+**
- **Ollama** running on `localhost:11434` with `gemma3:4b` pulled
  ```bash
  ollama serve &
  ollama pull gemma3:4b      # ~3 GB, one-off
  ```

### One-time setup

```bash
cd chatbot
make setup           # create .venv, install Python deps
make ingest          # download PokéAPI → data/pokedex.sqlite (1025 species)
make index           # build hybrid RAG index (embeddings + FTS)
make web-install     # install SvelteKit dependencies
```

### Run (two terminals)

```bash
# Terminal 1 — RAG bridge on :8001
make rag

# Terminal 2 — SvelteKit frontend on :5173
make dev
```

Open <http://localhost:5173> and chat.

### Test the backend without the UI

Stream a response straight from the SvelteKit `/api/chat` SSE route:

```bash
curl -N http://localhost:5173/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"¿cuántas evoluciones tiene Eevee?"}]}'
```

Smoke-test the retriever alone (no LLM, no frontend):

```bash
cd chatbot && make test-rag
```

### Stack

PokéAPI → SQLite → `multilingual-e5-small` embeddings + SQLite FTS (BM25) →
FastAPI bridge (`/retrieve`, `/build_prompt`) → bilingual prompt with
CORPUS FACTS + retrieved CONTEXT → Ollama (`gemma3:4b`) → SSE → SvelteKit chat UI.

---

## Building the paper

```bash
cd paper
latexmk -pdf main.tex
```

Compiles `paper/main.pdf` from `paper/main.tex` plus the inputs already in
`figures/`, `tables/`, and `references/refs.bib`.
