"""FastAPI bridge exposing the Python-side Retriever to the SvelteKit app.

The retriever loads heavy dependencies (sentence-transformers, sqlite-vec,
~300 MB of model weights at startup) — we keep it warm in this single
long-lived process and call it via HTTP from `+server.ts`. Spawning a
subprocess per chat turn would re-load the model each time, which is
unacceptable.

Endpoints:
    GET  /healthz                       -> { ok: true, model: ..., db: ... }
    POST /retrieve  { query, k? }       -> { docs: [{species_id, name, text, score}, ...] }
    POST /build_prompt  { messages, k?} -> { messages: [...], retrieved: [...], lang: ... }

Run with:
    .venv/bin/python -m server.rag_api
or via the Makefile:
    make rag
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from rag.retriever import Retriever
from server.prompts import build_messages, detect_language, load_corpus_facts

log = logging.getLogger("rag_api")

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "pokedex.sqlite"


class RetrieveRequest(BaseModel):
    query: str
    k: int = 5


class DocResponse(BaseModel):
    species_id: int
    name: str
    text: str
    score: float


class RetrieveResponse(BaseModel):
    docs: list[DocResponse]


class Message(BaseModel):
    role: str  # "user" | "assistant" | "system"
    content: str


class BuildPromptRequest(BaseModel):
    messages: list[Message] = Field(..., description="Full chat history including the latest user turn.")
    k: int = 5


class BuildPromptResponse(BaseModel):
    messages: list[Message]
    retrieved: list[DocResponse]
    lang: str


def _make_app(db_path: Path) -> FastAPI:
    app = FastAPI(title="Pokédex RAG bridge", version="0.1")
    log.info("loading retriever (db=%s) ...", db_path)
    retriever = Retriever(db_path=db_path)
    log.info("retriever loaded.")
    corpus_facts = load_corpus_facts(str(db_path))
    log.info("corpus facts loaded: %d species, %d types, %d chains.",
             corpus_facts.total_species, corpus_facts.total_types, corpus_facts.total_chains)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True, "db": str(db_path)}

    @app.post("/retrieve", response_model=RetrieveResponse)
    def retrieve(req: RetrieveRequest) -> RetrieveResponse:
        if not req.query.strip():
            raise HTTPException(status_code=400, detail="empty query")
        docs = retriever.search(req.query, k=req.k)
        return RetrieveResponse(docs=[
            DocResponse(species_id=d.species_id, name=d.name, text=d.text, score=d.score)
            for d in docs
        ])

    @app.post("/build_prompt", response_model=BuildPromptResponse)
    def build_prompt(req: BuildPromptRequest) -> BuildPromptResponse:
        if not req.messages or req.messages[-1].role != "user":
            raise HTTPException(status_code=400, detail="last message must be from user")
        history = [m.model_dump() for m in req.messages[:-1]]
        last_user = req.messages[-1].content
        retrieved = retriever.search(last_user, k=req.k)
        retrieved_dicts = [
            {"species_id": d.species_id, "name": d.name, "text": d.text, "score": d.score}
            for d in retrieved
        ]
        msgs = build_messages(history=history, retrieved_docs=retrieved_dicts,
                              user_message=last_user, corpus_facts=corpus_facts)
        return BuildPromptResponse(
            messages=[Message(role=m["role"], content=m["content"]) for m in msgs],
            retrieved=[DocResponse(**d) for d in retrieved_dicts],
            lang=detect_language(last_user),
        )

    return app


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--db", type=Path, default=Path(os.getenv("POKEDEX_DB", DEFAULT_DB)))
    p.add_argument("--host", default=os.getenv("RAG_API_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.getenv("RAG_API_PORT", "8001")))
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    import uvicorn
    app = _make_app(args.db)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
