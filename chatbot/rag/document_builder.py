"""Build one plain-text document per Pokémon species from the SQLite Pokédex.

The output of `build_documents()` is the corpus that gets embedded by
`build_index.py` and retrieved by `retriever.py` to ground LLM answers.

Document structure (intentional, not free-form): a heading line + structured
sections joined by blank lines. The structure helps small retrieval models
match queries like "fire-type starter" or "Pokémon legendario eléctrico" by
keeping discriminating tokens (type names, region, legendary status,
flavor-text noun phrases) close together.

Each doc targets ~200-500 tokens. For Pokémon with very short flavor text we
land around 150 tokens; for legendaries with long lore + many moves we cap at
~600. Both ends are fine — the embedding model truncates at 256 tokens
internally anyway.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass


@dataclass
class Doc:
    """One species's retrieval document."""
    species_id: int
    name: str
    text: str


def _fetch_species_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("""
        SELECT s.id, s.name, s.generation, s.genus_en, s.genus_es, s.habitat,
               s.color, s.shape, s.is_legendary, s.is_mythical,
               s.flavor_text_en, s.flavor_text_es, s.chain_id, s.evolves_from_id,
               p.id AS pokemon_id, p.height_dm, p.weight_hg
        FROM species s
        JOIN pokemon p ON p.species_id = s.id AND p.is_default = 1
        ORDER BY s.id
    """))


def _types_by_pokemon(conn: sqlite3.Connection) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for pid, slot, t in conn.execute("SELECT pokemon_id, slot, type_name FROM types ORDER BY pokemon_id, slot"):
        out.setdefault(pid, []).append(t)
    return out


def _stats_by_pokemon(conn: sqlite3.Connection) -> dict[int, dict[str, int]]:
    out: dict[int, dict[str, int]] = {}
    for pid, hp, atk, df, spa, spd, spe in conn.execute(
        "SELECT pokemon_id, hp, attack, defense, sp_attack, sp_defense, speed FROM stats"
    ):
        out[pid] = {"hp": hp, "attack": atk, "defense": df,
                    "sp_attack": spa, "sp_defense": spd, "speed": spe}
    return out


def _abilities_by_pokemon(conn: sqlite3.Connection) -> dict[int, list[tuple[str, bool, str | None]]]:
    out: dict[int, list[tuple[str, bool, str | None]]] = {}
    for pid, name, hidden, desc in conn.execute(
        "SELECT pokemon_id, ability_name, is_hidden, description_en FROM abilities ORDER BY pokemon_id, is_hidden, ability_name"
    ):
        out.setdefault(pid, []).append((name, bool(hidden), desc))
    return out


def _moves_by_pokemon(conn: sqlite3.Connection, signature_limit: int = 12) -> dict[int, list[str]]:
    """A small selection of representative moves per pokemon.

    We don't try to embed every move — the chatbot is not a battle simulator.
    We pick up to `signature_limit` distinct level-up moves (lowest level
    first) to give the embedder type-correlated tokens (e.g. "thunderbolt",
    "ember") that improve retrieval.
    """
    out: dict[int, list[str]] = {}
    for pid, name, method, lvl in conn.execute(
        "SELECT pokemon_id, move_name, learn_method, level_learned FROM moves "
        "WHERE learn_method = 'level-up' "
        "ORDER BY pokemon_id, COALESCE(level_learned, 999), move_name"
    ):
        bucket = out.setdefault(pid, [])
        if len(bucket) < signature_limit:
            bucket.append(name)
    return out


@dataclass
class EvolutionStep:
    species: str
    from_species: str | None      # None for the base form
    trigger: str | None           # e.g. "level-up", "use-item", "trade"
    conditions: dict              # parsed JSON


def _format_step(step: EvolutionStep) -> str:
    pretty = step.species.replace("-", " ").title()
    if step.from_species is None:
        return pretty
    bits: list[str] = []
    trig = (step.trigger or "").replace("-", " ")
    if trig and trig not in ("level up", "level-up"):
        bits.append(trig)
    cond = step.conditions or {}
    if "min_level" in cond:
        bits.append(f"level {cond['min_level']}")
    if "min_happiness" in cond:
        bits.append("high friendship")
    if "item" in cond and isinstance(cond["item"], dict):
        item_name = cond["item"].get("name", "").replace("-", " ")
        if item_name:
            bits.append(f"using {item_name}")
    if "held_item" in cond and isinstance(cond["held_item"], dict):
        bits.append(f"holding {cond['held_item'].get('name', '').replace('-', ' ')}")
    if "time_of_day" in cond and cond["time_of_day"]:
        bits.append(f"at {cond['time_of_day']}")
    if "known_move" in cond and isinstance(cond["known_move"], dict):
        bits.append(f"knowing {cond['known_move'].get('name', '').replace('-', ' ')}")
    if "location" in cond and isinstance(cond["location"], dict):
        bits.append(f"at {cond['location'].get('name', '').replace('-', ' ')}")
    if "gender" in cond and cond["gender"]:
        bits.append(f"if {'female' if cond['gender'] == 1 else 'male'}")
    if "trade_species" in cond and isinstance(cond["trade_species"], dict):
        bits.append(f"traded for {cond['trade_species'].get('name', '').replace('-', ' ')}")
    detail = ", ".join(b for b in bits if b)
    return f"{pretty} ({detail})" if detail else pretty


def _evolution_lookup(conn: sqlite3.Connection) -> dict[int, list[EvolutionStep]]:
    """For each chain_id, return all evolution edges with conditions.

    The list keeps every row from `evolution_chains` (one base step plus one
    edge per child). A chain may branch — Eevee has eight children — so
    callers must treat this as a multi-edge graph, not a linear walk.
    Edges are ordered: base first, then children in BFS order from the base.
    """
    chains: dict[int, list[EvolutionStep]] = {}
    for chain_id, frm, to, trigger, cond_json in conn.execute(
        "SELECT chain_id, from_species, to_species, trigger, conditions_json FROM evolution_chains"
    ):
        try:
            cond = json.loads(cond_json) if cond_json else {}
        except json.JSONDecodeError:
            cond = {}
        chains.setdefault(chain_id, []).append(
            EvolutionStep(species=to, from_species=frm, trigger=trigger, conditions=cond)
        )

    out: dict[int, list[EvolutionStep]] = {}
    for chain_id, edges in chains.items():
        children: dict[str, list[EvolutionStep]] = {}
        for e in edges:
            if e.from_species is not None:
                children.setdefault(e.from_species, []).append(e)
        bases = [e for e in edges if e.from_species is None] or [edges[0]]
        ordered: list[EvolutionStep] = []
        seen: set[str] = set()
        queue: list[EvolutionStep] = list(bases)
        while queue:
            cur = queue.pop(0)
            if cur.species in seen:
                continue
            seen.add(cur.species)
            ordered.append(cur)
            queue.extend(children.get(cur.species, []))
        out[chain_id] = ordered
    return out


def _format_height_weight(height_dm: int | None, weight_hg: int | None) -> str:
    parts = []
    if height_dm:
        parts.append(f"{height_dm / 10:.1f} m tall")
    if weight_hg:
        parts.append(f"{weight_hg / 10:.1f} kg")
    return ", ".join(parts) if parts else "—"


def _format_stats(stats: dict[str, int]) -> str:
    return (f"HP {stats['hp']}, Attack {stats['attack']}, Defense {stats['defense']}, "
            f"Sp. Attack {stats['sp_attack']}, Sp. Defense {stats['sp_defense']}, "
            f"Speed {stats['speed']}")


def _format_abilities(abilities: list[tuple[str, bool, str | None]]) -> str:
    parts: list[str] = []
    for name, hidden, desc in abilities:
        tag = " (hidden)" if hidden else ""
        descstr = f" — {desc}" if desc else ""
        parts.append(f"{name}{tag}{descstr}")
    return "; ".join(parts) if parts else "—"


def _flag_text(is_legendary: bool, is_mythical: bool) -> str:
    if is_mythical:
        return "Mythical Pokémon."
    if is_legendary:
        return "Legendary Pokémon."
    return ""


GENERATION_TO_REGION: dict[str, str] = {
    "generation-i": "Kanto",
    "generation-ii": "Johto",
    "generation-iii": "Hoenn",
    "generation-iv": "Sinnoh",
    "generation-v": "Unova",
    "generation-vi": "Kalos",
    "generation-vii": "Alola",
    "generation-viii": "Galar",
    "generation-ix": "Paldea",
}


TYPE_ES: dict[str, str] = {
    "normal": "normal", "fire": "fuego", "water": "agua", "electric": "eléctrico",
    "grass": "planta", "ice": "hielo", "fighting": "lucha", "poison": "veneno",
    "ground": "tierra", "flying": "volador", "psychic": "psíquico", "bug": "bicho",
    "rock": "roca", "ghost": "fantasma", "dragon": "dragón", "dark": "siniestro",
    "steel": "acero", "fairy": "hada",
}


# The 27 canonical starters across Gen 1-9 (default-form names).
STARTER_NAMES: frozenset[str] = frozenset({
    "bulbasaur", "ivysaur", "venusaur",
    "charmander", "charmeleon", "charizard",
    "squirtle", "wartortle", "blastoise",
    "chikorita", "bayleef", "meganium",
    "cyndaquil", "quilava", "typhlosion",
    "totodile", "croconaw", "feraligatr",
    "treecko", "grovyle", "sceptile",
    "torchic", "combusken", "blaziken",
    "mudkip", "marshtomp", "swampert",
    "turtwig", "grotle", "torterra",
    "chimchar", "monferno", "infernape",
    "piplup", "prinplup", "empoleon",
    "snivy", "servine", "serperior",
    "tepig", "pignite", "emboar",
    "oshawott", "dewott", "samurott",
    "chespin", "quilladin", "chesnaught",
    "fennekin", "braixen", "delphox",
    "froakie", "frogadier", "greninja",
    "rowlet", "dartrix", "decidueye",
    "litten", "torracat", "incineroar",
    "popplio", "brionne", "primarina",
    "grookey", "thwackey", "rillaboom",
    "scorbunny", "raboot", "cinderace",
    "sobble", "drizzile", "inteleon",
    "sprigatito", "floragato", "meowscarada",
    "fuecoco", "crocalor", "skeledirge",
    "quaxly", "quaxwell", "quaquaval",
})


def _gen_and_region(gen_slug: str | None) -> str:
    if not gen_slug:
        return "—"
    pretty_gen = gen_slug.replace("generation-", "Generation ").title()
    region = GENERATION_TO_REGION.get(gen_slug)
    return f"{pretty_gen} ({region} region)" if region else pretty_gen


def build_document(row: sqlite3.Row,
                   types: list[str],
                   stats: dict[str, int],
                   abilities: list[tuple[str, bool, str | None]],
                   moves: list[str],
                   evolution_chain: list[EvolutionStep]) -> Doc:
    name = row["name"]
    pretty_name = name.replace("-", " ").title()
    types_str = " / ".join(types).title() if types else "Unknown"
    flavor = row["flavor_text_en"] or row["flavor_text_es"] or "No Pokédex flavor text available."
    flavor_es = row["flavor_text_es"]
    genus_en = row["genus_en"] or ""
    genus_es = row["genus_es"] or ""
    genus = " / ".join(g for g in [genus_en, genus_es] if g) or "—"
    habitat = row["habitat"] or "unknown habitat"
    flags = _flag_text(bool(row["is_legendary"]), bool(row["is_mythical"]))
    gen = _gen_and_region(row["generation"])
    color_shape = ", ".join(filter(None, [row["color"], row["shape"]])) or "—"
    hw = _format_height_weight(row["height_dm"], row["weight_hg"])

    own_step = next((s for s in evolution_chain if s.species == name), None)
    own_evolution_line = ""
    if own_step and own_step.from_species:
        prev_pretty = own_step.from_species.replace("-", " ").title()
        method_bits: list[str] = []
        cond = own_step.conditions or {}
        if "min_level" in cond:
            method_bits.append(f"at level {cond['min_level']}")
        if "min_happiness" in cond:
            method_bits.append("with high friendship")
        if "item" in cond and isinstance(cond["item"], dict):
            iname = cond["item"].get("name", "").replace("-", " ")
            if iname:
                method_bits.append(f"using a {iname}")
        if "held_item" in cond and isinstance(cond["held_item"], dict):
            method_bits.append(f"holding {cond['held_item'].get('name', '').replace('-', ' ')}")
        if "time_of_day" in cond and cond["time_of_day"]:
            method_bits.append(f"at {cond['time_of_day']}")
        if "known_move" in cond and isinstance(cond["known_move"], dict):
            method_bits.append(f"after learning {cond['known_move'].get('name', '').replace('-', ' ')}")
        if (own_step.trigger or "") == "trade":
            method_bits.append("by trade")
        method_str = " ".join(method_bits) if method_bits else (own_step.trigger or "level-up").replace("-", " ")
        own_evolution_line = f"{pretty_name} evolves from {prev_pretty} {method_str}.".replace("  ", " ")

    # Render the (possibly branching) chain as bullets — one line per edge.
    # This format keeps every species name in the document so the embedder can
    # match queries like "evoluciones de Eevee" against the Eevee doc, and so
    # the LLM can list all branches without hallucinating.
    evolution_str: str
    if evolution_chain and len(evolution_chain) > 1:
        base = next((s for s in evolution_chain if s.from_species is None), evolution_chain[0])
        edges = [s for s in evolution_chain if s.from_species is not None]
        # Count distinct evolved forms (not edges) — equals chain size minus the base.
        evolved_count = len({s.species for s in edges})
        bullets = [
            f"- {s.from_species.replace('-', ' ').title()} → {_format_step(s)}"
            for s in edges
        ]
        evolution_str = (
            f"\nBase form: {base.species.replace('-', ' ').title()}. "
            f"This chain has {evolved_count} evolved form"
            f"{'s' if evolved_count != 1 else ''} "
            f"(not counting the base form):\n" + "\n".join(bullets)
        )
    elif evolution_chain and len(evolution_chain) == 1 and evolution_chain[0].species == name:
        evolution_str = f"{pretty_name} does not evolve."
    else:
        evolution_str = "Evolution information not available."

    moves_str = ", ".join(moves) if moves else "—"

    types_es = " / ".join(TYPE_ES.get(t.lower(), t) for t in types).title() if types else "Desconocido"
    region = GENERATION_TO_REGION.get(row["generation"] or "")
    is_starter = name in STARTER_NAMES
    tag_bits: list[str] = []
    if types:
        tag_bits.append(f"Types: {' '.join(t.title() for t in types)} / Tipos: {' '.join(TYPE_ES.get(t.lower(), t) for t in types)}")
    if region:
        tag_bits.append(f"Region: {region}")
    if row["is_legendary"]:
        tag_bits.append("Legendary / Legendario")
    if row["is_mythical"]:
        tag_bits.append("Mythical / Singular")
    if is_starter:
        tag_bits.append("Starter Pokémon / Pokémon inicial")
    tags_line = ". ".join(tag_bits) + "." if tag_bits else ""

    sections = [
        f"# {pretty_name} (Pokédex #{row['id']:04d})",
        f"Type: {types_str} / Tipo: {types_es}. {flags}".strip(),
        tags_line,
        f"Genus: {genus or '—'}. {gen}. Habitat: {habitat}. Appearance: {color_shape}. Size: {hw}.",
        f"Base stats — {_format_stats(stats)}.",
        f"Abilities: {_format_abilities(abilities)}.",
    ]
    if own_evolution_line:
        sections.append(own_evolution_line)
    sections += [
        f"Evolution chain: {evolution_str}",
        f"Signature level-up moves: {moves_str}.",
        f"Pokédex entry (English): {flavor}",
    ]
    if flavor_es and flavor_es != flavor:
        sections.append(f"Entrada Pokédex (Español): {flavor_es}")

    text = "\n\n".join(s for s in sections if s.strip())
    return Doc(species_id=int(row["id"]), name=name, text=text)


def build_documents(db_path: str) -> list[Doc]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        types_idx = _types_by_pokemon(conn)
        stats_idx = _stats_by_pokemon(conn)
        abilities_idx = _abilities_by_pokemon(conn)
        moves_idx = _moves_by_pokemon(conn)
        evo_lookup = _evolution_lookup(conn)

        docs: list[Doc] = []
        for row in _fetch_species_rows(conn):
            pid = int(row["pokemon_id"])
            chain_id = row["chain_id"]
            fallback = [EvolutionStep(species=row["name"], from_species=None,
                                      trigger="base", conditions={})]
            chain = evo_lookup.get(int(chain_id), fallback) if chain_id is not None else fallback
            doc = build_document(
                row=row,
                types=types_idx.get(pid, []),
                stats=stats_idx.get(pid, {"hp": 0, "attack": 0, "defense": 0,
                                          "sp_attack": 0, "sp_defense": 0, "speed": 0}),
                abilities=abilities_idx.get(pid, []),
                moves=moves_idx.get(pid, []),
                evolution_chain=chain,
            )
            docs.append(doc)
        return docs
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--db", default="data/pokedex.sqlite")
    p.add_argument("--show", type=int, help="print this many sample docs and exit")
    args = p.parse_args()

    docs = build_documents(args.db)
    if args.show:
        for d in docs[:args.show]:
            print("=" * 70)
            print(d.text)
            print()
        print(f"# total: {len(docs)} docs")
    else:
        print(f"built {len(docs)} documents (use --show N to preview)")
