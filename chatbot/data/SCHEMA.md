# `pokedex.sqlite` — Schema

Single SQLite database produced by `ingest/fetch_pokeapi.py`. All data sourced from [PokéAPI](https://pokeapi.co/) v2 (RESTful, public, free for non-commercial use).

> Built by Phase 0 of the Pokédex chatbot. See `.planning/phase-2/ROADMAP.md`.

---

## Conventions

- **`PRAGMA foreign_keys = ON`**: foreign keys are enforced.
- **Naming**: lowercase + snake_case, matching PokéAPI conventions where possible.
- **Units**: PokéAPI's native units kept (no conversions). `height` is decimetres (`dm`); `weight` is hectograms (`hg`). Convert at presentation time (1 dm = 0.1 m, 1 hg = 0.1 kg).
- **Bilingual fields**: `_en` / `_es` suffixes. English is primary; Spanish present where PokéAPI provides it (most Gen 1-7 species; coverage thinner for newer species).
- **Booleans**: stored as `INTEGER` 0/1.
- **Sentinel for "no flavor text"**: `NULL`, never `""`.

---

## Tables

### `species` — one row per Pokémon species

The "species" is the canonical Pokédex entry (e.g. *Charizard* is one species; its Mega and Gigantamax variants are separate `pokemon` rows linked to the same species).

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | National Pokédex number (1–1025 for Gen 1-9). |
| `name` | TEXT UNIQUE | Slug-form English name (e.g. `bulbasaur`). |
| `generation` | TEXT | Generation slug (e.g. `generation-i`). |
| `pokedex_number` | INTEGER | Same as `id` for the National Pokédex. Kept for clarity in joins. |
| `flavor_text_en` | TEXT NULL | Representative English Pokédex entry. |
| `flavor_text_es` | TEXT NULL | Representative Spanish Pokédex entry. |
| `genus_en` / `genus_es` | TEXT NULL | E.g. "Seed Pokémon" / "Pokémon Semilla". |
| `habitat` | TEXT NULL | E.g. `forest`, `mountain`. NULL for many newer species. |
| `is_legendary` | INTEGER | 0/1. |
| `is_mythical` | INTEGER | 0/1. |
| `color` | TEXT NULL | Pokédex color tag (e.g. `green`). |
| `shape` | TEXT NULL | Pokédex shape tag (e.g. `quadruped`). |
| `evolves_from_id` | INTEGER NULL FK→species(id) | Direct prior stage; NULL if base form. |
| `chain_id` | INTEGER | Evolution chain identifier; join with `evolution_chains`. |

### `pokemon` — one row per *playable form* of a species

PokéAPI distinguishes a "Pokémon" (specific form) from a "species" (the franchise concept). Phase 0 stores **only the default form** to keep the corpus bounded; alternate forms can be added later if needed for evaluation questions.

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | PokéAPI pokemon id. |
| `species_id` | INTEGER FK→species(id) | Owning species. |
| `name` | TEXT | Form name (`bulbasaur`). |
| `height_dm` | INTEGER | Height in decimetres. |
| `weight_hg` | INTEGER | Weight in hectograms. |
| `base_experience` | INTEGER | XP yielded on defeat. |
| `is_default` | INTEGER | 1 for the default form (always 1 in Phase 0). |

### `stats` — base stats per Pokémon form

| Column | Type | Description |
|---|---|---|
| `pokemon_id` | INTEGER PK FK→pokemon(id) | One row per pokemon. |
| `hp` | INTEGER | Base HP. |
| `attack`, `defense`, `sp_attack`, `sp_defense`, `speed` | INTEGER | Base stat values 0–255. |

### `types` — typings (1 or 2 per Pokémon)

| Column | Type | Description |
|---|---|---|
| `pokemon_id` | INTEGER FK→pokemon(id) | |
| `slot` | INTEGER | 1 = primary, 2 = secondary. |
| `type_name` | TEXT | E.g. `grass`, `poison`, `fire`. |
| **PK** | (`pokemon_id`, `slot`) | |

### `abilities` — abilities a Pokémon can have, with their effect text

| Column | Type | Description |
|---|---|---|
| `pokemon_id` | INTEGER FK→pokemon(id) | |
| `ability_name` | TEXT | E.g. `overgrow`, `chlorophyll`. |
| `is_hidden` | INTEGER | 0 = regular, 1 = hidden ability. |
| `description_en` | TEXT NULL | Short effect text in English (from PokéAPI's `effect_entries`). |
| **PK** | (`pokemon_id`, `ability_name`) | |

Ability descriptions are deduplicated: each ability is fetched at most once per ingest run.

### `moves` — representative moveset per Pokémon

Capped at **25 moves per Pokémon** (config: `MOVES_PER_POKEMON_LIMIT`), prioritizing level-up moves first (lowest level), then TM/HM, then egg, then tutor. Stored to keep the corpus bounded; the Pokédex chatbot is not a competitive battle simulator.

| Column | Type | Description |
|---|---|---|
| `pokemon_id` | INTEGER FK→pokemon(id) | |
| `move_name` | TEXT | E.g. `tackle`. |
| `learn_method` | TEXT | One of `level-up`, `machine`, `egg`, `tutor`, ... |
| `level_learned` | INTEGER NULL | Level at which the move is learned (NULL for non-level-up methods). |
| **PK** | (`pokemon_id`, `move_name`, `learn_method`) | |

### `evolution_chains` — flattened evolution graph edges

PokéAPI exposes evolution chains as nested JSON. We flatten them into edges so they're SQL-queryable.

| Column | Type | Description |
|---|---|---|
| `chain_id` | INTEGER | PokéAPI evolution-chain id. |
| `from_species` | TEXT NULL | Predecessor species name; NULL for the base of the chain. |
| `to_species` | TEXT | Successor species name. |
| `trigger` | TEXT NULL | E.g. `level-up`, `use-item`, `trade`, `base` (for the root marker row). |
| `conditions_json` | TEXT | JSON object with the original `evolution_details` keys (level, item, time-of-day, location, etc.) minus `trigger`. |
| **PK** | (`chain_id`, `to_species`) | |

The base-of-chain marker rows (`trigger='base'`, `from_species` NULL) are kept so a chain can be reconstructed from a single SQL query without ambiguity.

### `ingest_log` — bookkeeping for resumability

| Column | Type | Description |
|---|---|---|
| `species_id` | INTEGER PK | Species id that was ingested successfully. |
| `completed_at` | TEXT | UTC timestamp from `datetime('now')`. |
| `pokeapi_url` | TEXT | The species URL fetched. |

Re-running the script skips ids already in `ingest_log`.

---

## Indexes

```
idx_pokemon_species   (species_id)
idx_types_pokemon     (pokemon_id)
idx_abilities_pokemon (pokemon_id)
idx_moves_pokemon     (pokemon_id)
```

The `species(name)` UNIQUE constraint and the various PKs cover the rest of the lookup paths Phase 1 (RAG document builder) needs.

---

## Row counts after a full ingest (`--start 1 --stop 1025`)

Measured on a clean run completed 2026-05-05 against PokéAPI v2:

| Table | Count | Notes |
|---|---|---|
| `species` | 1025 | National Pokédex Gen 1-9 |
| `pokemon` | 1025 | default-form-only Phase 0 policy |
| `stats` | 1025 | one row per Pokémon (wide format) |
| `types` | 1551 | most species have 2 types, some single-type |
| `abilities` | 2411 | many species lack a hidden ability |
| `moves` | 25 162 | cap-bounded at 25 representative moves/species |
| `evolution_chains` | 1025 rows / 541 distinct chains | (chain_id, to_species) deduped across game versions |
| `ingest_log` | 1025 | one row per successfully ingested species |

These are the canonical Phase 0 done-criteria.

---

## Caveats / data fidelity notes

- **PokéAPI completeness drift**: very recent species (Pal Park / DLC) sometimes have empty `flavor_text_entries` or `habitat`. Documents in Phase 1 should handle NULLs gracefully.
- **Spanish flavor text gaps**: some Gen 8-9 species lack a Spanish entry. The bilingual chatbot must fall back to "no Spanish flavor text available" → translate from English at LLM time.
- **Evolution conditions are heterogeneous**: `conditions_json` may include `min_level`, `held_item`, `known_move_type`, `gender`, `time_of_day`, `location`, etc. Phase 1's document builder should render them in human-readable form.
- **Move-learning is generation-dependent**: we collapse all generations into a single representative `learn_method` per (pokemon, move). For battle-mechanics questions this is lossy; for chat-style QA it's adequate.
- **Cached raw JSON** lives under `data/raw_cache/` (gitignored). Deleting it forces a re-fetch; the SQLite DB is the canonical artifact.
