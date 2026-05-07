# Sample queries for RAG smoke test (Phase 1 task F1.4)

These are **retrieval-only** sanity checks (no LLM involved). Each row asserts that the retriever's top-k contains an expected species. The Phase 4 user-facing eval (10 questions) is a different file (`eval/questions.md` — to be authored in Phase 4).

Queries are designed to mirror how users will phrase real chatbot questions: direct fact lookups, type+region filters, evolution path, and short bilingual variants. They are **not** trivia challenges that depend on lore the corpus doesn't contain — that kind of robustness is a Phase 4 (LLM-grounded) concern.

| # | Lang | Query | Expected in top-5 (any of) |
|---|---|---|---|
| 1 | EN | "What's a fire-type starter from Kanto?" | charmander, charmeleon, charizard |
| 2 | EN | "Tell me about an electric mouse Pokémon." | pikachu, raichu, pichu, pawmi, pawmo |
| 3 | ES | "¿Qué Pokémon legendario eléctrico hay en Johto?" | raikou |
| 4 | EN | "Fast dragon Pokémon that evolves from Gabite" | garchomp |
| 5 | EN | "Which Pokémon evolves into Clefable using a Moon Stone?" | clefairy, cleffa |
| 6 | EN | "Ghost Pokémon from the Hoenn region" | shuppet, banette, duskull, dusclops |
| 7 | ES | "Pokémon parecido a un león de melena ardiente" | pyroar, litleo, entei |
| 8 | EN | "The Psi Pokémon Kadabra holds a silver spoon" | kadabra, abra, alakazam |
| 9 | EN | "Bug-type Pokémon that becomes a butterfly" | butterfree, vivillon, beautifly |
| 10 | ES | "Pokémon legendario que controla los océanos y las lluvias" | kyogre, groudon, rayquaza |

## How Phase 1's `test_retrieval.py` should use this

```python
# Pseudocode — implementer writes the real version in Phase 1.
from rag.retriever import Retriever

cases = parse_table_above()
retriever = Retriever()
hits = miss = 0
for q in cases:
    docs = retriever.search(q.query, k=5)
    names = {d.name for d in docs}
    if names & set(q.expected):
        hits += 1
    else:
        miss += 1
        print(f"MISS [{q.id}] {q.query!r}: got {names}, expected any of {q.expected}")
assert hits >= 8, f"retrieval below threshold: {hits}/10"
```

## Acceptance

≥ 8/10 queries must return at least one expected species in the top-5. If retrieval scores below this, the RAG document template (Phase 1 task F1.1) needs more structure — add type names verbatim, add habitat names, add Spanish synonyms (e.g. "ratón eléctrico" → ensure flavor_text_es is included in the document).
