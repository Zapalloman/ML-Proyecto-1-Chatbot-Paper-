# Prompt design — Phase 2 deliverable

This document records the rationale, structure, and observed behavior of the
system prompt used by the Pokédex chatbot. It is **the** prompt-engineering
artifact requested by Enunciado Fase 2 ("desarrollar usando prompt
engineering... un modelo que responda preguntas usando el conocimiento
recopilado").

The runtime prompt assembly lives in `chatbot/server/prompts.py`.

---

## What "prompt engineering" means in this project

The chatbot does **no fine-tuning**. The LLM (one of `gemma3:4b`,
`qwen2.5:3b`, `gemma3:1b`) is generic. The mechanism that makes it behave as
a Pokédex expert is the **prompt we send on every turn**:

```
┌──────────────────────────────────────────────────┐
│  SYSTEM (constant) — role, rules, refusal logic  │
├──────────────────────────────────────────────────┤
│  CONTEXT (dynamic)  — top-k Pokédex docs (RAG)   │
├──────────────────────────────────────────────────┤
│  HISTORY (last 4 turns) + new USER message       │
└──────────────────────────────────────────────────┘
```

Each rule below maps to a specific failure mode that surfaced during
backend testing.

---

## System prompt — final version

The `SYSTEM_PROMPT` constant in `server/prompts.py` is bilingual on purpose:
small instruction-tuned models (1B-4B parameters) follow rules more
reliably when the system message uses the same language as the user turn,
and the cleanest way to do that for a *bilingual* assistant is to state the
rules in both languages side-by-side. The cost is ~250 tokens of context;
the payoff is language compliance during the eval.

The seven rules are identical in English and Spanish:

| # | Rule | Failure it prevents |
|---|---|---|
| 1 | Answer ONLY with facts in the CONTEXT block | Model invents stats/types from training data |
| 2 | If not in CONTEXT, say literal "No tengo esa información en mi Pokédex" / "I don't have that in my Pokédex." | Soft hallucination ("I think Pikachu is…") |
| 3 | Reply in the user's input language; do not switch mid-message | Spanish question → English reply (bug observed with `gemma3:1b` zero-shot) |
| 4 | Refuse one-line if not about Pokémon | Out-of-domain leakage ("capital of France?") |
| 5 | Use **bold** for Pokémon / move / ability names | Improves UI readability via the chat client's markdown renderer |
| 6 | ≤ 6 sentences unless asked for more | `gemma3:4b` was producing 600-token rambles on `qwen2.5:3b`-length queries |
| 7 | Cite Pokédex number `#0025` first time a species is named | Anchors responses to the data source — visible in eval transcripts |

---

## Context block format

`format_context(docs, lang)` produces:

```
<header line in user's language>

CONTEXT:

[Doc 1 — Pikachu (#0025)]
# Pikachu (Pokédex #0025)
...full retrieval doc...

[Doc 2 — Pichu (#0172)]
# Pichu (Pokédex #0172)
...
```

Decisions:

- **Header in user's language** — primes the model: "the rules above are
  about *this* language" plus the answer-language rule (#3) is reinforced
  before the user turn is read.
- **Numbered `Doc i`** — gives the LLM a stable identifier it can cite
  ("according to Doc 1 …"), and lets a human auditor cross-reference.
- **Pokédex number in the heading** — the model picks it up for rule #7
  citation without explicit prompting.
- **No truncation** — average doc is ~250 tokens; top-5 = ~1.3K tokens of
  context. Fits comfortably in the 4 K context window even on `gemma3:1b`.

Empty-retrieval guard: if the retriever returns 0 docs (legitimate when the
query is out-of-domain), the CONTEXT block contains a single sentinel line
in the user's language. Combined with rule #2 the model reliably refuses
instead of falling back to training-data trivia.

---

## Language detection (`detect_language`)

Implementation in `server/prompts.py`:

1. **Diacritic test** — presence of any of `á é í ó ú ñ ü ¿ ¡` ⇒ Spanish.
2. **Stopword ratio** — fraction of tokens in a 30-word Spanish stopword set.
   ≥ 18 % ⇒ Spanish.
3. Default to English.

Why a heuristic and not the LLM itself: the language of the *prompt header*
must be set **before** invoking the LLM. Using the LLM to classify language
would require a round-trip per turn. The heuristic is correct on every
sample tested in the backend smoke runs — Spanish queries with ASCII-only
ASCII produce one or two stopword hits ("qué", "es") which is enough.

Edge case observed: **mixed-language queries** (e.g. "tell me about
**Pikachu**'s tipos") — these get classified as English. The chatbot then
answers in English. In the Phase 4 eval this happens once and is correctly
flagged as a known limitation.

---

## Turn assembly (`build_messages`)

`messages` array sent to Ollama (OpenAI-compatible chat format):

```
[
  { role: "system",    content: <SYSTEM_PROMPT + "\n\n" + CONTEXT_BLOCK> },
  ...history (last 8 messages, i.e. 4 turns)...,
  { role: "user",      content: <new user message> },
]
```

Why the system message includes the dynamic CONTEXT (instead of being a
separate `role: system`):

- Some Ollama-served chat templates don't fold multiple system messages
  reliably — `gemma3` in particular concatenates them with a separator that
  the model treats as a turn boundary, corrupting rule application.
- Putting them together inside one `system` message guarantees the LLM
  reads the rules in the same instruction frame that holds the data they
  apply to.

History truncation to the last 8 messages bounds the prompt at ~3 K tokens
in the worst case (large CONTEXT + 8 chatty turns) — well under the 4 K
context all 3 models support.

---

## Iteration log (what changed and why)

| Version | Change | Reason |
|---|---|---|
| v0 | English-only system prompt, no language rule | All Phase 2 tests pass in English, all Spanish tests answer in English |
| v1 | Added rule #3 (mirror user's language), kept English system | Spanish answers improved but `gemma3:1b` still drifts mid-message |
| v2 | Bilingual system prompt (rules duplicated in EN + ES) | Spanish compliance jumps to 100 % across smoke tests |
| v3 | Added rule #7 (cite #0025) | Eval transcripts now self-document which doc grounded the answer |
| v4 | Added empty-retrieval sentinel in CONTEXT | Eliminates the "Tell me about Pokémon #2000" hallucination |
| v5 | Header line in user's language | Reinforces #3; observed one fewer mid-message language flip on `gemma3:1b` |
| v6 (current) | History truncation to last 8 messages | Caps prompt size; no quality loss vs. full history in tests |

---

## Backend behavior verified

End-to-end smoke run from `curl localhost:5173/api/chat` against each model:

| Query | Model | Behavior |
|---|---|---|
| "What types is Pikachu? Be brief." | `gemma3:1b` | Streamed bullet list, type "Electric" correct (mixed with genus "Mouse Pokémon" — minor). |
| "¿Qué tipo es Pikachu? Responde breve." | `qwen2.5:3b` | "Electric (#0025)" — perfect, citation per rule #7. |
| "What is the evolution chain of Eevee? Be brief." | `gemma3:4b` | Partial: named one Eeveelution then said "I don't have that in my Pokédex" — accurate refusal because top-5 retrieval cannot fit Eevee + all 8 evolutions. |

The Eevee partial-refusal is **correct under the rules** — it's a known
retrieval-coverage limitation that gets logged in the Phase 4 test report,
not a prompt bug.

---

## Open issues (carried into Phase 4)

1. **Genre vs. type confusion** in `gemma3:1b` ("Mouse Pokémon" listed
   alongside "Electric"). The CONTEXT clearly separates them; the smaller
   model conflates the two adjacent fields.
2. **Long-chain queries** (Eevee, Tyrogue, Wurmple) overflow top-5
   retrieval. Either bump `k` for these specific intents or accept partial
   answers as a known limitation.
3. **Mixed-language queries** answer in English. Acceptable for Phase 2;
   may revisit if the eval surfaces it as user-confusing.

These will be revisited *with empirical data* in Phase 4 when all 30
question×model responses are scored.
