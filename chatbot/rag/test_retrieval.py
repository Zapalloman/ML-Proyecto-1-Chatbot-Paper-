"""Smoke test for the RAG retriever — Phase 1 acceptance gate (F1.5).

Reads `chatbot/eval/sample_queries.md`, runs each query through the Retriever,
and asserts that for at least 8 of the 10 cases the top-5 result set contains
at least one of the expected species.

Exit codes:
    0 — passed (≥ 8 / 10 hits)
    2 — failed (fewer than 8 hits)
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from rag.retriever import Retriever

QUERIES_MD = Path(__file__).resolve().parent.parent / "eval" / "sample_queries.md"


@dataclass
class Case:
    id: int
    lang: str
    query: str
    expected: set[str]


def parse_cases(md_path: Path) -> list[Case]:
    text = md_path.read_text(encoding="utf-8")
    cases: list[Case] = []
    for line in text.splitlines():
        m = re.match(r"\|\s*(\d+)\s*\|\s*(EN|ES)\s*\|\s*\"(.+?)\"\s*\|\s*(.+?)\s*\|", line)
        if not m:
            continue
        idx, lang, query, expected_raw = m.groups()
        expected = {s.strip().lower() for s in expected_raw.split(",")}
        cases.append(Case(int(idx), lang, query, expected))
    return cases


def main() -> int:
    cases = parse_cases(QUERIES_MD)
    if not cases:
        print(f"ERROR: no cases parsed from {QUERIES_MD}", file=sys.stderr)
        return 2

    retriever = Retriever()
    hits = 0
    misses: list[tuple[Case, list[str]]] = []
    for c in cases:
        docs = retriever.search(c.query, k=5)
        names = [d.name.lower() for d in docs]
        if set(names) & c.expected:
            hits += 1
            mark = "HIT "
        else:
            mark = "MISS"
            misses.append((c, names))
        print(f"  {mark}  [{c.id:2d}] {c.lang}  {c.query!r}")
        print(f"             top-5 = {names}")
        print(f"             expected any of {sorted(c.expected)}")

    threshold = 8
    print()
    print(f"score: {hits}/{len(cases)}  (threshold {threshold})")
    if hits < threshold:
        print("\nFAILED. Misses:")
        for c, names in misses:
            print(f"  [{c.id:2d}] {c.query!r}\n         got {names}\n         wanted any of {sorted(c.expected)}")
        return 2
    print("PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
