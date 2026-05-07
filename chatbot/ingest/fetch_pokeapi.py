"""Fetch the National Pokédex (Gen 1-9, ~1025 species) from PokéAPI into SQLite.

Idempotent (INSERT OR REPLACE), resumable (skips species already fully ingested),
rate-limited, and caches raw JSON responses on disk for reproducibility.

Usage:
    python -m ingest.fetch_pokeapi --db data/pokedex.sqlite

Tables produced (see data/SCHEMA.md):
    species, pokemon, stats, types, abilities, moves, evolution_chains,
    ingest_log
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import requests
from tqdm import tqdm

POKEAPI = "https://pokeapi.co/api/v2"
SPECIES_TARGET = 1025  # Gen 1 through Gen 9
RATE_LIMIT_SLEEP = 1.2  # seconds between requests (~50 req/min, polite)
TIMEOUT = 30
MOVES_PER_POKEMON_LIMIT = 25  # cap to stay focused: level-up + signature

log = logging.getLogger("ingest")


# ---------------------------------------------------------------------------
# HTTP layer with disk cache
# ---------------------------------------------------------------------------

class CachedFetcher:
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "ml1-pokedex-chatbot/0.1 (educational; CINF104)"
        self.last_request_at = 0.0
        self.fetched_count = 0

    def _cache_path(self, url: str) -> Path:
        rel = url.replace(POKEAPI + "/", "").rstrip("/").replace("/", "__")
        return self.cache_dir / f"{rel}.json"

    def get(self, url: str) -> dict[str, Any]:
        cp = self._cache_path(url)
        if cp.exists():
            return json.loads(cp.read_text(encoding="utf-8"))

        # Rate limit
        elapsed = time.monotonic() - self.last_request_at
        if elapsed < RATE_LIMIT_SLEEP:
            time.sleep(RATE_LIMIT_SLEEP - elapsed)

        for attempt in range(4):
            try:
                resp = self.session.get(url, timeout=TIMEOUT)
                self.last_request_at = time.monotonic()
                if resp.status_code == 429:
                    sleep_for = 2 ** (attempt + 2)
                    log.warning("429 rate-limited on %s, sleeping %ss", url, sleep_for)
                    time.sleep(sleep_for)
                    continue
                resp.raise_for_status()
                data = resp.json()
                cp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                self.fetched_count += 1
                return data
            except (requests.RequestException, ValueError) as exc:
                log.warning("fetch attempt %d failed for %s: %s", attempt + 1, url, exc)
                time.sleep(2 ** attempt)
        raise RuntimeError(f"failed to fetch {url} after retries")


# ---------------------------------------------------------------------------
# SQLite schema
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS species (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    generation      TEXT,
    pokedex_number  INTEGER,
    flavor_text_en  TEXT,
    flavor_text_es  TEXT,
    genus_en        TEXT,
    genus_es        TEXT,
    habitat         TEXT,
    is_legendary    INTEGER NOT NULL DEFAULT 0,
    is_mythical     INTEGER NOT NULL DEFAULT 0,
    color           TEXT,
    shape           TEXT,
    evolves_from_id INTEGER,  -- NOT a FK: predecessors may be ingested later in id order (baby Pokémon have higher ids than their evolutions)
    chain_id        INTEGER
);

CREATE TABLE IF NOT EXISTS pokemon (
    id              INTEGER PRIMARY KEY,
    species_id      INTEGER NOT NULL REFERENCES species(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    height_dm       INTEGER,
    weight_hg       INTEGER,
    base_experience INTEGER,
    is_default      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS stats (
    pokemon_id    INTEGER PRIMARY KEY REFERENCES pokemon(id) ON DELETE CASCADE,
    hp            INTEGER NOT NULL,
    attack        INTEGER NOT NULL,
    defense       INTEGER NOT NULL,
    sp_attack     INTEGER NOT NULL,
    sp_defense    INTEGER NOT NULL,
    speed         INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS types (
    pokemon_id  INTEGER NOT NULL REFERENCES pokemon(id) ON DELETE CASCADE,
    slot        INTEGER NOT NULL,
    type_name   TEXT NOT NULL,
    PRIMARY KEY (pokemon_id, slot)
);

CREATE TABLE IF NOT EXISTS abilities (
    pokemon_id      INTEGER NOT NULL REFERENCES pokemon(id) ON DELETE CASCADE,
    ability_name    TEXT NOT NULL,
    is_hidden       INTEGER NOT NULL DEFAULT 0,
    description_en  TEXT,
    PRIMARY KEY (pokemon_id, ability_name)
);

CREATE TABLE IF NOT EXISTS moves (
    pokemon_id    INTEGER NOT NULL REFERENCES pokemon(id) ON DELETE CASCADE,
    move_name     TEXT NOT NULL,
    learn_method  TEXT NOT NULL,
    level_learned INTEGER,
    PRIMARY KEY (pokemon_id, move_name, learn_method)
);

CREATE TABLE IF NOT EXISTS evolution_chains (
    chain_id        INTEGER NOT NULL,
    from_species    TEXT,
    to_species      TEXT NOT NULL,
    trigger         TEXT,
    conditions_json TEXT,
    PRIMARY KEY (chain_id, to_species)
);

CREATE TABLE IF NOT EXISTS ingest_log (
    species_id     INTEGER PRIMARY KEY,
    completed_at   TEXT NOT NULL,
    pokeapi_url    TEXT
);

CREATE INDEX IF NOT EXISTS idx_pokemon_species ON pokemon(species_id);
CREATE INDEX IF NOT EXISTS idx_types_pokemon ON types(pokemon_id);
CREATE INDEX IF NOT EXISTS idx_abilities_pokemon ON abilities(pokemon_id);
CREATE INDEX IF NOT EXISTS idx_moves_pokemon ON moves(pokemon_id);
"""


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Parsers (PokéAPI → row dicts)
# ---------------------------------------------------------------------------

def _pick_lang(entries: list[dict], field: str, lang: str) -> str | None:
    for e in entries:
        if e.get("language", {}).get("name") == lang:
            return e.get(field)
    return None


def _flavor_text(entries: list[dict], lang: str) -> str | None:
    """Pick a representative flavor text in the requested language.

    PokéAPI returns the same text repeated per game version. We pick the
    most recent (longest) entry in the chosen language.
    """
    cands = [e for e in entries if e.get("language", {}).get("name") == lang]
    if not cands:
        return None
    text = max((e.get("flavor_text", "") for e in cands), key=len)
    # Old games encoded line breaks with form-feed; PokéAPI keeps that.
    return text.replace("\f", " ").replace("\n", " ").strip()


def parse_species(species_json: dict) -> dict:
    return {
        "id": species_json["id"],
        "name": species_json["name"],
        "generation": (species_json.get("generation") or {}).get("name"),
        "pokedex_number": species_json["id"],
        "flavor_text_en": _flavor_text(species_json.get("flavor_text_entries", []), "en"),
        "flavor_text_es": _flavor_text(species_json.get("flavor_text_entries", []), "es"),
        "genus_en": _pick_lang(species_json.get("genera", []), "genus", "en"),
        "genus_es": _pick_lang(species_json.get("genera", []), "genus", "es"),
        "habitat": (species_json.get("habitat") or {}).get("name"),
        "is_legendary": int(bool(species_json.get("is_legendary"))),
        "is_mythical": int(bool(species_json.get("is_mythical"))),
        "color": (species_json.get("color") or {}).get("name"),
        "shape": (species_json.get("shape") or {}).get("name"),
        "evolves_from_id": _url_id(((species_json.get("evolves_from_species") or {}) or {}).get("url")),
        "chain_id": _url_id((species_json.get("evolution_chain") or {}).get("url")),
    }


def _url_id(url: str | None) -> int | None:
    if not url:
        return None
    parts = [p for p in url.split("/") if p]
    try:
        return int(parts[-1])
    except (ValueError, IndexError):
        return None


def parse_pokemon(pokemon_json: dict, species_id: int) -> tuple[dict, dict, list, list]:
    p = {
        "id": pokemon_json["id"],
        "species_id": species_id,
        "name": pokemon_json["name"],
        "height_dm": pokemon_json.get("height"),
        "weight_hg": pokemon_json.get("weight"),
        "base_experience": pokemon_json.get("base_experience"),
        "is_default": int(bool(pokemon_json.get("is_default", True))),
    }
    stats_by_name = {s["stat"]["name"]: s["base_stat"] for s in pokemon_json.get("stats", [])}
    stats = {
        "pokemon_id": pokemon_json["id"],
        "hp": stats_by_name.get("hp", 0),
        "attack": stats_by_name.get("attack", 0),
        "defense": stats_by_name.get("defense", 0),
        "sp_attack": stats_by_name.get("special-attack", 0),
        "sp_defense": stats_by_name.get("special-defense", 0),
        "speed": stats_by_name.get("speed", 0),
    }
    types = [
        {
            "pokemon_id": pokemon_json["id"],
            "slot": t["slot"],
            "type_name": t["type"]["name"],
        }
        for t in pokemon_json.get("types", [])
    ]
    abilities = [
        {
            "pokemon_id": pokemon_json["id"],
            "ability_name": a["ability"]["name"],
            "ability_url": a["ability"]["url"],
            "is_hidden": int(bool(a.get("is_hidden"))),
        }
        for a in pokemon_json.get("abilities", [])
    ]
    return p, stats, types, abilities


def parse_moves(pokemon_json: dict, limit: int) -> list[dict]:
    """Pick representative moves: prioritize level-up (lowest level first)
    and machine moves; cap at `limit`.
    """
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    candidates: list[tuple[int, dict, str, int | None]] = []
    for m in pokemon_json.get("moves", []):
        move_name = m["move"]["name"]
        for vd in m.get("version_group_details", []):
            method = vd["move_learn_method"]["name"]
            level = vd.get("level_learned_at") or None
            priority = {"level-up": 0, "machine": 1, "egg": 2, "tutor": 3}.get(method, 9)
            candidates.append((priority, m, method, level))
            break  # one entry per move is enough
    candidates.sort(key=lambda c: (c[0], (c[3] or 999)))
    for _, m, method, level in candidates:
        key = (m["move"]["name"], method)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "pokemon_id": pokemon_json["id"],
                "move_name": m["move"]["name"],
                "learn_method": method,
                "level_learned": level,
            }
        )
        if len(rows) >= limit:
            break
    return rows


def parse_ability_description(ability_json: dict) -> str | None:
    """Prefer the short flavor in English from a recent generation's effect entry."""
    for e in ability_json.get("effect_entries", []):
        if e.get("language", {}).get("name") == "en":
            return (e.get("short_effect") or e.get("effect") or "").strip() or None
    return None


def walk_evolution_chain(chain_json: dict, chain_id: int) -> list[dict]:
    """Flatten PokéAPI's nested chain into edges.

    PokéAPI returns one `evolution_details` per game version for the same edge
    (same from→to species). We collapse them: pick the first non-empty entry
    for `trigger`, and merge all unique condition keys into `conditions_json`.
    This satisfies the (chain_id, to_species) primary key.
    """
    rows: list[dict] = []

    def _walk(node: dict, parent: str | None):
        species_name = node["species"]["name"]
        if parent is not None:
            details = node.get("evolution_details") or [{}]
            trigger = None
            merged_conditions: dict[str, Any] = {}
            for d in details:
                t = (d.get("trigger") or {}).get("name")
                if trigger is None and t:
                    trigger = t
                for k, v in d.items():
                    if k == "trigger" or v in (None, "", 0):
                        continue
                    # later entries overwrite — that's fine; they tend to repeat.
                    merged_conditions[k] = v
            rows.append(
                {
                    "chain_id": chain_id,
                    "from_species": parent,
                    "to_species": species_name,
                    "trigger": trigger,
                    "conditions_json": json.dumps(merged_conditions, ensure_ascii=False),
                }
            )
        else:
            # Root of the chain — record as a self-edge so we can reconstruct chains.
            rows.append(
                {
                    "chain_id": chain_id,
                    "from_species": None,
                    "to_species": species_name,
                    "trigger": "base",
                    "conditions_json": "{}",
                }
            )
        for child in node.get("evolves_to", []):
            _walk(child, species_name)

    _walk(chain_json["chain"], None)
    return rows


# ---------------------------------------------------------------------------
# DB writers
# ---------------------------------------------------------------------------

UPSERT_SPECIES = """
INSERT OR REPLACE INTO species
    (id, name, generation, pokedex_number, flavor_text_en, flavor_text_es,
     genus_en, genus_es, habitat, is_legendary, is_mythical, color, shape,
     evolves_from_id, chain_id)
VALUES
    (:id, :name, :generation, :pokedex_number, :flavor_text_en, :flavor_text_es,
     :genus_en, :genus_es, :habitat, :is_legendary, :is_mythical, :color, :shape,
     :evolves_from_id, :chain_id);
"""

UPSERT_POKEMON = """
INSERT OR REPLACE INTO pokemon
    (id, species_id, name, height_dm, weight_hg, base_experience, is_default)
VALUES (:id, :species_id, :name, :height_dm, :weight_hg, :base_experience, :is_default);
"""

UPSERT_STATS = """
INSERT OR REPLACE INTO stats
    (pokemon_id, hp, attack, defense, sp_attack, sp_defense, speed)
VALUES (:pokemon_id, :hp, :attack, :defense, :sp_attack, :sp_defense, :speed);
"""


def upsert_many(conn: sqlite3.Connection, sql: str, rows: list[dict]) -> None:
    if not rows:
        return
    conn.executemany(sql, rows)


def insert_types(conn: sqlite3.Connection, pokemon_id: int, rows: list[dict]) -> None:
    conn.execute("DELETE FROM types WHERE pokemon_id = ?", (pokemon_id,))
    conn.executemany(
        "INSERT INTO types (pokemon_id, slot, type_name) VALUES (:pokemon_id, :slot, :type_name)",
        rows,
    )


def insert_abilities(
    conn: sqlite3.Connection, pokemon_id: int, rows: list[dict]
) -> None:
    conn.execute("DELETE FROM abilities WHERE pokemon_id = ?", (pokemon_id,))
    conn.executemany(
        """INSERT INTO abilities (pokemon_id, ability_name, is_hidden, description_en)
           VALUES (:pokemon_id, :ability_name, :is_hidden, :description_en)""",
        rows,
    )


def insert_moves(conn: sqlite3.Connection, pokemon_id: int, rows: list[dict]) -> None:
    conn.execute("DELETE FROM moves WHERE pokemon_id = ?", (pokemon_id,))
    conn.executemany(
        """INSERT INTO moves (pokemon_id, move_name, learn_method, level_learned)
           VALUES (:pokemon_id, :move_name, :learn_method, :level_learned)""",
        rows,
    )


def upsert_chain(conn: sqlite3.Connection, chain_id: int, rows: list[dict]) -> None:
    conn.execute("DELETE FROM evolution_chains WHERE chain_id = ?", (chain_id,))
    conn.executemany(
        """INSERT INTO evolution_chains (chain_id, from_species, to_species, trigger, conditions_json)
           VALUES (:chain_id, :from_species, :to_species, :trigger, :conditions_json)""",
        rows,
    )


def already_done(conn: sqlite3.Connection, species_id: int) -> bool:
    row = conn.execute("SELECT 1 FROM ingest_log WHERE species_id = ?", (species_id,)).fetchone()
    return row is not None


def mark_done(conn: sqlite3.Connection, species_id: int, url: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO ingest_log (species_id, completed_at, pokeapi_url) VALUES (?, datetime('now'), ?)",
        (species_id, url),
    )


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def ingest_species(
    conn: sqlite3.Connection,
    fetcher: CachedFetcher,
    species_id: int,
    seen_chains: set[int],
    seen_abilities: dict[str, str | None],
) -> None:
    species_url = f"{POKEAPI}/pokemon-species/{species_id}/"
    species_json = fetcher.get(species_url)
    species_row = parse_species(species_json)
    upsert_many(conn, UPSERT_SPECIES, [species_row])

    # Default variety only — keeps scope manageable.
    default = next((v for v in species_json.get("varieties", []) if v.get("is_default")), None)
    if default is None and species_json.get("varieties"):
        default = species_json["varieties"][0]
    if default:
        pokemon_url = default["pokemon"]["url"]
        pokemon_json = fetcher.get(pokemon_url)
        p_row, stats_row, types_rows, abilities_rows = parse_pokemon(pokemon_json, species_id)
        upsert_many(conn, UPSERT_POKEMON, [p_row])
        upsert_many(conn, UPSERT_STATS, [stats_row])
        insert_types(conn, p_row["id"], types_rows)

        # Resolve ability descriptions, cached.
        for a in abilities_rows:
            url = a.pop("ability_url")
            name = a["ability_name"]
            if name not in seen_abilities:
                try:
                    ability_json = fetcher.get(url)
                    seen_abilities[name] = parse_ability_description(ability_json)
                except Exception as exc:
                    log.warning("ability fetch failed for %s: %s", name, exc)
                    seen_abilities[name] = None
            a["description_en"] = seen_abilities[name]
        insert_abilities(conn, p_row["id"], abilities_rows)

        moves_rows = parse_moves(pokemon_json, MOVES_PER_POKEMON_LIMIT)
        insert_moves(conn, p_row["id"], moves_rows)

    # Evolution chain — fetch once per chain.
    chain_id = species_row["chain_id"]
    if chain_id is not None and chain_id not in seen_chains:
        try:
            chain_json = fetcher.get(f"{POKEAPI}/evolution-chain/{chain_id}/")
            chain_rows = walk_evolution_chain(chain_json, chain_id)
            upsert_chain(conn, chain_id, chain_rows)
        except Exception as exc:
            log.warning("chain fetch failed for chain %s: %s", chain_id, exc)
        seen_chains.add(chain_id)

    mark_done(conn, species_id, species_url)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--db", type=Path, default=Path("data/pokedex.sqlite"))
    p.add_argument("--cache", type=Path, default=Path("data/raw_cache"))
    p.add_argument("--start", type=int, default=1)
    p.add_argument("--stop", type=int, default=SPECIES_TARGET, help="inclusive upper bound")
    p.add_argument("--commit-every", type=int, default=10)
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    conn = init_db(args.db)
    fetcher = CachedFetcher(args.cache)

    seen_chains: set[int] = {
        row[0] for row in conn.execute("SELECT DISTINCT chain_id FROM evolution_chains")
    }
    seen_abilities: dict[str, str | None] = {
        row[0]: row[1] for row in conn.execute(
            "SELECT DISTINCT ability_name, description_en FROM abilities WHERE description_en IS NOT NULL"
        )
    }

    todo = [sid for sid in range(args.start, args.stop + 1) if not already_done(conn, sid)]
    log.info("ingesting %d species (skipping %d already done)",
             len(todo), (args.stop - args.start + 1) - len(todo))

    failed: list[int] = []
    pbar = tqdm(todo, desc="species", unit="sp")
    for i, sid in enumerate(pbar, 1):
        try:
            ingest_species(conn, fetcher, sid, seen_chains, seen_abilities)
        except Exception as exc:
            log.error("species %s failed: %s", sid, exc)
            failed.append(sid)
        if i % args.commit_every == 0:
            conn.commit()
        pbar.set_postfix(http=fetcher.fetched_count, fail=len(failed))
    conn.commit()

    counts = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("species", "pokemon", "stats", "types", "abilities", "moves", "evolution_chains")
    }
    log.info("done. counts=%s http_calls=%d failed=%d", counts, fetcher.fetched_count, len(failed))
    if failed:
        log.warning("retry failed ids: %s", failed)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
