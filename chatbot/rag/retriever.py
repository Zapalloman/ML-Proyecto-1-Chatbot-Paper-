"""Hybrid (dense + BM25) retriever over the Pokédex.

Combines two complementary signals:

1. **Dense semantic search** via sqlite-vec over E5 embeddings — handles
   paraphrases and cross-lingual queries.
2. **BM25 keyword search** via SQLite FTS5 — handles factual queries with
   strong literal terms ("Johto", "Kanto", "starter", species names).

Results from both rankers are merged with **Reciprocal Rank Fusion** (RRF):
score(doc) = sum_i  1 / (rrf_k + rank_i(doc)). RRF is parameter-light, robust
to score-scale differences, and consistently outperforms either ranker alone
on factual + semantic mixes.

Usage:
    from rag.retriever import Retriever
    r = Retriever()
    docs = r.search("Pokémon legendario eléctrico de Johto", k=5)

CLI:
    python -m rag.retriever "fire-type starter from Kanto" -k 5
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path

import sqlite_vec
from sentence_transformers import SentenceTransformer

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "pokedex.sqlite"
EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
EMBEDDING_DIM = 384
QUERY_PREFIX = "query: "

DEFAULT_RRF_K = 60     # standard RRF damping constant from the literature
DEFAULT_FETCH = 25     # how many candidates each ranker returns before fusion


@dataclass
class RetrievedDoc:
    species_id: int
    name: str
    text: str
    score: float        # fused RRF score; higher = better


def _fts_query(raw: str) -> str:
    """Sanitize a free-text query for FTS5: drop punctuation, OR the tokens.

    FTS5 treats unquoted multi-word input as AND, which is too strict for
    natural-language queries. Splitting and OR-joining keeps recall high.
    """
    tokens = re.findall(r"[\wáéíóúñü]+", raw.lower(), flags=re.UNICODE)
    tokens = [t for t in tokens if len(t) >= 2]
    if not tokens:
        return ""
    return " OR ".join(f'"{t}"' for t in tokens)


class Retriever:
    """Hybrid (dense + BM25) retriever loaded once and reused per query."""

    def __init__(self, db_path: str | Path = DEFAULT_DB,
                 model_name: str = EMBEDDING_MODEL,
                 rrf_k: int = DEFAULT_RRF_K,
                 fetch_per_ranker: int = DEFAULT_FETCH) -> None:
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"{self.db_path} not found — run `python -m rag.build_index` first"
            )
        self.rrf_k = rrf_k
        self.fetch_per_ranker = fetch_per_ranker
        self._model = SentenceTransformer(model_name)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.enable_load_extension(True)
        sqlite_vec.load(self._conn)
        self._conn.enable_load_extension(False)
        self._conn.row_factory = sqlite3.Row

    # -- individual rankers ------------------------------------------------

    def _dense(self, query: str, k: int) -> list[tuple[int, float]]:
        emb = self._model.encode(
            [QUERY_PREFIX + query], normalize_embeddings=True, convert_to_numpy=True
        )[0]
        blob = struct.pack(f"{EMBEDDING_DIM}f", *emb)
        return [
            (int(r["species_id"]), float(r["distance"]))
            for r in self._conn.execute(
                """
                SELECT species_id, distance
                FROM vec_species
                WHERE embedding MATCH ? AND k = ?
                ORDER BY distance
                """,
                (blob, k),
            )
        ]

    def _bm25(self, query: str, k: int) -> list[tuple[int, float]]:
        fts_q = _fts_query(query)
        if not fts_q:
            return []
        try:
            return [
                (int(r["rowid"]), float(r["score"]))
                for r in self._conn.execute(
                    """
                    SELECT rowid, bm25(rag_docs_fts) AS score
                    FROM rag_docs_fts
                    WHERE rag_docs_fts MATCH ?
                    ORDER BY score
                    LIMIT ?
                    """,
                    (fts_q, k),
                )
            ]
        except sqlite3.OperationalError:
            # No matches against FTS5 — return empty silently.
            return []

    # -- fusion ------------------------------------------------------------

    def search(self, query: str, k: int = 5) -> list[RetrievedDoc]:
        if not query.strip():
            return []
        dense = self._dense(query, self.fetch_per_ranker)
        bm25 = self._bm25(query, self.fetch_per_ranker)

        rrf: dict[int, float] = {}
        for rank, (sid, _) in enumerate(dense):
            rrf[sid] = rrf.get(sid, 0.0) + 1.0 / (self.rrf_k + rank + 1)
        for rank, (sid, _) in enumerate(bm25):
            rrf[sid] = rrf.get(sid, 0.0) + 1.0 / (self.rrf_k + rank + 1)

        if not rrf:
            return []

        top_ids = sorted(rrf, key=lambda i: -rrf[i])[:k]
        placeholders = ",".join("?" * len(top_ids))
        rows = {
            int(r["species_id"]): r
            for r in self._conn.execute(
                f"SELECT species_id, name, text FROM rag_docs WHERE species_id IN ({placeholders})",
                top_ids,
            )
        }
        return [
            RetrievedDoc(
                species_id=sid,
                name=rows[sid]["name"],
                text=rows[sid]["text"],
                score=rrf[sid],
            )
            for sid in top_ids if sid in rows
        ]

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("query")
    p.add_argument("-k", "--top-k", type=int, default=5)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--show-text", action="store_true", help="print matched doc text")
    args = p.parse_args(argv)

    r = Retriever(db_path=args.db)
    docs = r.search(args.query, k=args.top_k)
    for d in docs:
        print(f"#{d.species_id:04d}  {d.name:20s}  rrf={d.score:.4f}")
        if args.show_text:
            print(d.text)
            print("-" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
