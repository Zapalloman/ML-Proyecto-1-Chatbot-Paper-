"""Embed every Pokédex document and persist the vectors in `pokedex.sqlite`
via the `sqlite-vec` extension.

We keep the vector table inside the same database (not a sidecar) because the
1025 × 384 float32 = ~1.5 MB of embeddings is negligible next to the ~30-80 MB
already in `pokedex.sqlite`, and a single file means one less moving part for
the chatbot backend to load.

Usage:
    python -m rag.build_index --db data/pokedex.sqlite
    python -m rag.build_index --db data/pokedex.sqlite --rebuild   # drop + recreate
"""

from __future__ import annotations

import argparse
import sqlite3
import struct
import sys
import time
from pathlib import Path

import sqlite_vec
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

from rag.document_builder import Doc, build_documents

EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
EMBEDDING_DIM = 384
VEC_TABLE = "vec_species"
DOCS_TABLE = "rag_docs"
FTS_TABLE = "rag_docs_fts"

# E5 family expects "query: " / "passage: " prefixes — see HF model card.
PASSAGE_PREFIX = "passage: "
QUERY_PREFIX = "query: "


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def _ensure_tables(conn: sqlite3.Connection, rebuild: bool) -> None:
    if rebuild:
        conn.execute(f"DROP TABLE IF EXISTS {VEC_TABLE}")
        conn.execute(f"DROP TABLE IF EXISTS {DOCS_TABLE}")
        conn.execute(f"DROP TABLE IF EXISTS {FTS_TABLE}")
    conn.execute(f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS {VEC_TABLE}
        USING vec0(
            species_id INTEGER PRIMARY KEY,
            embedding  FLOAT[{EMBEDDING_DIM}]
        )
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {DOCS_TABLE} (
            species_id INTEGER PRIMARY KEY,
            name       TEXT NOT NULL,
            text       TEXT NOT NULL
        )
    """)
    # FTS5 for BM25 keyword retrieval (hybrid search alongside the dense index).
    conn.execute(f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE}
        USING fts5(
            name, text,
            content='{DOCS_TABLE}',
            content_rowid='species_id',
            tokenize='unicode61 remove_diacritics 2'
        )
    """)
    conn.commit()


def _serialize(vec) -> bytes:
    """Pack a 1-D numpy float32 vector for sqlite-vec."""
    return struct.pack(f"{len(vec)}f", *vec)


def index_documents(db_path: Path, rebuild: bool, batch_size: int = 64) -> dict:
    docs = build_documents(str(db_path))
    print(f"built {len(docs)} documents", file=sys.stderr)

    print(f"loading {EMBEDDING_MODEL} ...", file=sys.stderr)
    t0 = time.monotonic()
    model = SentenceTransformer(EMBEDDING_MODEL)
    print(f"  loaded in {time.monotonic() - t0:.1f}s", file=sys.stderr)

    conn = _connect(db_path)
    _ensure_tables(conn, rebuild=rebuild)

    texts = [PASSAGE_PREFIX + d.text for d in docs]
    print(f"encoding {len(texts)} docs (batch={batch_size}) ...", file=sys.stderr)
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=True,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    assert embeddings.shape == (len(docs), EMBEDDING_DIM), embeddings.shape

    rows_vec = [(d.species_id, _serialize(e)) for d, e in zip(docs, embeddings)]
    rows_docs = [(d.species_id, d.name, d.text) for d in docs]

    conn.execute("BEGIN")
    conn.executemany(
        f"INSERT OR REPLACE INTO {VEC_TABLE} (species_id, embedding) VALUES (?, ?)",
        rows_vec,
    )
    conn.executemany(
        f"INSERT OR REPLACE INTO {DOCS_TABLE} (species_id, name, text) VALUES (?, ?, ?)",
        rows_docs,
    )
    # Keep FTS in sync. content='rag_docs' means we just (re)build the FTS rows.
    conn.execute(f"INSERT INTO {FTS_TABLE}({FTS_TABLE}) VALUES('rebuild')")
    conn.commit()

    counts = {
        "vec_species": conn.execute(f"SELECT COUNT(*) FROM {VEC_TABLE}").fetchone()[0],
        "rag_docs": conn.execute(f"SELECT COUNT(*) FROM {DOCS_TABLE}").fetchone()[0],
        "rag_docs_fts": conn.execute(f"SELECT COUNT(*) FROM {FTS_TABLE}").fetchone()[0],
    }
    conn.close()
    return counts


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--db", type=Path, default=Path("data/pokedex.sqlite"))
    p.add_argument("--rebuild", action="store_true", help="drop + recreate vec/docs tables")
    p.add_argument("--batch-size", type=int, default=64)
    args = p.parse_args(argv)

    counts = index_documents(args.db, rebuild=args.rebuild, batch_size=args.batch_size)
    print(f"done. counts={counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
