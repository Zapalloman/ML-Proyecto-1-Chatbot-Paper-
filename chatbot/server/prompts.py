"""System prompt + prompt-builder for the Pokédex chatbot.

Designed deliberately (this is the "prompt engineering" deliverable in the
assignment). Each rule below maps to a specific failure mode the production
chatbot would otherwise exhibit. See `chatbot/docs/PROMPT-DESIGN.md` for the
rationale and iteration history.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Language detection — cheap heuristic, runs per turn before prompt building.
# We intentionally avoid a full NLP library: the chatbot's output language
# follows the user's *input* language and a heuristic with a Spanish-feature
# bias is correct often enough for our 10-question eval.
# ---------------------------------------------------------------------------

_ES_DIACRITICS = re.compile(r"[áéíóúñ¿¡üÁÉÍÓÚÑÜ]")
_ES_STOPWORDS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas",
    "de", "del", "que", "qué", "y", "o", "pero", "si", "no",
    "me", "te", "se", "lo", "le", "les", "su", "tu", "mi",
    "es", "son", "fue", "era", "ser", "estar", "tiene", "tienen", "hay",
    "como", "cómo", "para", "por", "con", "sin", "más", "muy",
    "qué", "cuál", "cuáles", "dónde", "cuándo", "quién", "porque",
    "pokémon", "tipo", "evoluciona", "evolución",
}


def detect_language(text: str) -> str:
    """Return 'es' or 'en'. Defaults to 'en' if signal is ambiguous."""
    if not text:
        return "en"
    if _ES_DIACRITICS.search(text):
        return "es"
    tokens = re.findall(r"\b\w+\b", text.lower())
    es_hits = sum(1 for t in tokens if t in _ES_STOPWORDS)
    if tokens and es_hits / max(len(tokens), 1) >= 0.18:
        return "es"
    return "en"


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
# The prompt is bilingual on purpose: a small (1B-4B) instruction-tuned model
# is more reliable when the system message uses the same language as the user
# turn, and the cleanest way to do that for a *bilingual* assistant is to
# state the rules in both languages side-by-side. This costs ~250 tokens of
# context but pays back in language-compliance during the eval.

SYSTEM_PROMPT_BASE = """\
You are POKEDEX-CHAT, an expert assistant whose knowledge of the Pokémon \
world comes from two sources, both grounded in the local Pokédex database: \
(a) the CORPUS FACTS block — global, always-on counts and reference info; \
(b) the CONTEXT block — per-turn retrieved species documents. Treat both as \
your *only* sources of truth. Do not invent anything that is not in either.

Rules (English):
1. Answer ONLY with facts from CORPUS FACTS or CONTEXT. Never invent \
species, types, abilities, evolutions, stats, or lore.
2. If neither block contains the answer, reply exactly: \
"I don't have that in my Pokédex."
3. Detect the user's language. If they wrote in Spanish, answer in Spanish; \
if in English, answer in English. Do not switch languages mid-message.
4. Refuse politely (one short sentence) when the question is not about Pokémon.
5. Use **bold** for Pokémon names and move/ability names.
6. Be concise — at most 6 sentences unless the user explicitly asks for more.
7. Cite the Pokédex number with the species the first time it appears, e.g. \
**Pikachu** (#0025).
8. For aggregate questions (totals, counts, "how many…"), answer from CORPUS \
FACTS. For species-specific questions, prefer CONTEXT.

Reglas (Español):
1. Responde SOLO con datos de CORPUS FACTS o CONTEXT. Nunca inventes \
especies, tipos, habilidades, evoluciones, estadísticas o lore.
2. Si ninguno de los dos bloques tiene la respuesta, responde exactamente: \
"No tengo esa información en mi Pokédex."
3. Detecta el idioma del usuario. Si escribe en español, responde en español; \
si en inglés, responde en inglés. No mezcles idiomas.
4. Rechaza educadamente (una frase) si la pregunta no es sobre Pokémon.
5. Usa **negrita** para nombres de Pokémon, movimientos y habilidades.
6. Sé conciso — máximo 6 frases, salvo que pidan más detalle.
7. Cita el número de Pokédex la primera vez que mencionas una especie, \
por ejemplo **Pikachu** (#0025).
8. Para preguntas agregadas (totales, cuántos, "cuántos hay"), responde desde \
CORPUS FACTS. Para preguntas sobre una especie específica, usa CONTEXT."""

# Backwards-compat alias for tests / external imports.
SYSTEM_PROMPT = SYSTEM_PROMPT_BASE


@dataclass
class CorpusFacts:
    total_species: int
    total_types: int
    total_abilities: int
    total_moves: int
    total_chains: int
    legendary_count: int
    mythical_count: int
    starter_count: int
    generation_breakdown: list[tuple[str, int]]  # ("Generation I (Kanto)", 151)
    type_names: list[str]                         # alphabetical type list

    def render(self, lang: str) -> str:
        gens = ", ".join(f"{name}: {n}" for name, n in self.generation_breakdown)
        types = ", ".join(self.type_names)
        if lang == "es":
            return (
                "DATOS GLOBALES DEL POKÉDEX (válidos para preguntas agregadas):\n"
                f"- Total de especies en el Pokédex: {self.total_species} "
                f"(Generaciones I–IX, regiones Kanto–Paldea)\n"
                f"- Especies legendarias: {self.legendary_count}; "
                f"singulares (mythical): {self.mythical_count}; "
                f"iniciales: {self.starter_count}\n"
                f"- Cadenas evolutivas: {self.total_chains}\n"
                f"- Tipos elementales ({self.total_types}): {types}\n"
                f"- Habilidades únicas catalogadas: {self.total_abilities}\n"
                f"- Movimientos catalogados (nivel-up): {self.total_moves}\n"
                f"- Distribución por generación: {gens}"
            )
        return (
            "POKÉDEX CORPUS FACTS (use these for aggregate questions):\n"
            f"- Total species in the Pokédex: {self.total_species} "
            f"(Generations I–IX, regions Kanto–Paldea)\n"
            f"- Legendary species: {self.legendary_count}; "
            f"mythical: {self.mythical_count}; "
            f"starters: {self.starter_count}\n"
            f"- Evolution chains: {self.total_chains}\n"
            f"- Elemental types ({self.total_types}): {types}\n"
            f"- Unique abilities catalogued: {self.total_abilities}\n"
            f"- Level-up moves catalogued: {self.total_moves}\n"
            f"- Per-generation breakdown: {gens}"
        )


_GEN_LABEL = {
    "generation-i": "Generation I (Kanto)",
    "generation-ii": "Generation II (Johto)",
    "generation-iii": "Generation III (Hoenn)",
    "generation-iv": "Generation IV (Sinnoh)",
    "generation-v": "Generation V (Unova)",
    "generation-vi": "Generation VI (Kalos)",
    "generation-vii": "Generation VII (Alola)",
    "generation-viii": "Generation VIII (Galar)",
    "generation-ix": "Generation IX (Paldea)",
}
_GEN_ORDER = {slug: i for i, slug in enumerate(_GEN_LABEL.keys())}

# 27 default-form starters across Gen 1–9. Mirrors document_builder.STARTER_NAMES
# but kept here too so prompts.py has no rag/* import dependency.
_STARTERS_COUNT = 27 * 3  # 27 lines * 3 stages = 81... no — 27 lines is the constant; actual count is 9*3*3=81 starters? recompute:
_STARTERS_COUNT = 9 * 3 * 3  # 9 generations × 3 starter families × 3 stages each = 81


def load_corpus_facts(db_path: str) -> CorpusFacts:
    """Compute corpus-wide stats from the SQLite Pokédex once at startup."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        total_species = cur.execute("SELECT COUNT(*) FROM species").fetchone()[0]
        legendary_count = cur.execute("SELECT COUNT(*) FROM species WHERE is_legendary=1").fetchone()[0]
        mythical_count = cur.execute("SELECT COUNT(*) FROM species WHERE is_mythical=1").fetchone()[0]
        total_chains = cur.execute("SELECT COUNT(DISTINCT chain_id) FROM evolution_chains").fetchone()[0]
        total_abilities = cur.execute("SELECT COUNT(DISTINCT ability_name) FROM abilities").fetchone()[0]
        total_moves = cur.execute("SELECT COUNT(DISTINCT move_name) FROM moves").fetchone()[0]
        type_rows = cur.execute(
            "SELECT DISTINCT type_name FROM types ORDER BY type_name"
        ).fetchall()
        type_names = [r[0] for r in type_rows]
        gen_rows = cur.execute(
            "SELECT generation, COUNT(*) FROM species GROUP BY generation"
        ).fetchall()
        gen_rows.sort(key=lambda r: _GEN_ORDER.get(r[0], 99))
        gen_breakdown = [(_GEN_LABEL.get(g, g or "?"), n) for g, n in gen_rows]
    finally:
        conn.close()
    return CorpusFacts(
        total_species=total_species,
        total_types=len(type_names),
        total_abilities=total_abilities,
        total_moves=total_moves,
        total_chains=total_chains,
        legendary_count=legendary_count,
        mythical_count=mythical_count,
        starter_count=_STARTERS_COUNT,
        generation_breakdown=gen_breakdown,
        type_names=type_names,
    )


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------

CONTEXT_HEADER_EN = (
    "Below is the CONTEXT — every Pokémon document you may reference. "
    "Anything not in this block is unknown to you."
)
CONTEXT_HEADER_ES = (
    "A continuación está el CONTEXT — los únicos documentos de Pokémon que "
    "puedes consultar. Lo que no está aquí es desconocido para ti."
)


def format_context(docs: list[dict], lang: str) -> str:
    """Format a list of retrieved docs as a single CONTEXT block.

    Each doc is expected to have keys: species_id, name, text.
    """
    header = CONTEXT_HEADER_ES if lang == "es" else CONTEXT_HEADER_EN
    if not docs:
        empty = ("(El Pokédex no encontró documentos relevantes para esta consulta.)"
                 if lang == "es"
                 else "(The Pokédex returned no relevant documents for this query.)")
        return f"CONTEXT:\n{empty}"
    blocks: list[str] = []
    for i, d in enumerate(docs, 1):
        sid = d.get("species_id", "?")
        name = (d.get("name") or "").replace("-", " ").title()
        text = (d.get("text") or "").strip()
        blocks.append(f"[Doc {i} — {name} (#{sid:04d})]\n{text}")
    return f"{header}\n\nCONTEXT:\n\n" + "\n\n".join(blocks)


def build_messages(history: list[dict],
                   retrieved_docs: list[dict],
                   user_message: str,
                   corpus_facts: CorpusFacts | None = None) -> list[dict]:
    """Build the OpenAI-compatible messages array sent to Ollama.

    `history` is the prior turns (excluding the current user message), each
    {role: 'user'|'assistant', content: str}. `retrieved_docs` are top-k
    docs from the RAG retriever for `user_message`. `user_message` is the
    fresh user turn we're answering now. `corpus_facts`, when supplied, is
    rendered into a CORPUS FACTS block so the model can answer aggregate
    questions ("how many Pokémon are there?") that don't fit in the top-k.
    """
    lang = detect_language(user_message)
    context_block = format_context(retrieved_docs, lang)
    sections: list[str] = [SYSTEM_PROMPT_BASE]
    if corpus_facts is not None:
        sections.append(corpus_facts.render(lang))
    sections.append(context_block)
    system_with_context = "\n\n".join(sections)

    msgs: list[dict] = [{"role": "system", "content": system_with_context}]
    msgs.extend(history[-8:])
    msgs.append({"role": "user", "content": user_message})
    return msgs
