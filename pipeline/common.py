"""Shared paths, config, and Pokémon name helpers."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SPRITES_DEFAULT = DATA / "sprites" / "default"
SPRITES_SHINY = DATA / "sprites" / "shiny"
OUT = ROOT / "viewer" / "assets"

POKEMON_LIST_JSON = DATA / "pokemon_list.json"
MISSING_JSON = DATA / "missing.json"
ANALYSIS_JSON = DATA / "analysis.json"
LAYOUT_JSON = OUT / "layout.json"

LIST_URL = "https://pokeapi.co/api/v2/pokemon?limit=100000"
SPRITE_URL = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{id}.png"
SHINY_URL = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/shiny/{id}.png"

# Species whose slug is the full name (id <= MAX_SPECIES_ID); above that are forms.
MAX_SPECIES_ID = 10000

CELL = 96  # native sprite box size

NAME_EXCEPTIONS = {
    "nidoran-f": "Nidoran♀",
    "nidoran-m": "Nidoran♂",
    "farfetchd": "Farfetch'd",
    "sirfetchd": "Sirfetch'd",
    "mr-mime": "Mr. Mime",
    "mr-rime": "Mr. Rime",
    "mime-jr": "Mime Jr.",
    "type-null": "Type: Null",
    "ho-oh": "Ho-Oh",
    "porygon-z": "Porygon-Z",
    "jangmo-o": "Jangmo-o",
    "hakamo-o": "Hakamo-o",
    "kommo-o": "Kommo-o",
    "flabebe": "Flabébé",
}


def load_json(path: Path):
    with open(path) as f:
        return json.load(f)


def save_json(path: Path, obj, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        if compact:
            json.dump(obj, f, separators=(",", ":"))
        else:
            json.dump(obj, f, indent=2)


def id_from_url(url: str) -> int:
    return int(url.rstrip("/").rsplit("/", 1)[-1])


def _title(slug: str) -> str:
    if slug in NAME_EXCEPTIONS:
        return NAME_EXCEPTIONS[slug]
    return " ".join(w.capitalize() for w in slug.split("-"))


def pretty_name(slug: str, poke_id: int, species_slugs: list[str]) -> tuple[str, str]:
    """Return (species_name, form_label). species_slugs must be sorted longest-first."""
    if poke_id < MAX_SPECIES_ID:
        return _title(slug), ""
    for sp in species_slugs:
        if slug == sp or slug.startswith(sp + "-"):
            form = slug[len(sp):].lstrip("-")
            return _title(sp), _title(form) if form else ""
    # Fallback: treat last token as form
    parts = slug.rsplit("-", 1)
    if len(parts) == 2:
        return _title(parts[0]), _title(parts[1])
    return _title(slug), ""


def sorted_species_slugs(entries: list[dict]) -> list[str]:
    slugs = [e["name"] for e in entries if e["id"] < MAX_SPECIES_ID]
    return sorted(slugs, key=len, reverse=True)


_slug_re = re.compile(r"[^a-z0-9-]")


def check_slug(s: str) -> str:
    assert not _slug_re.search(s), f"unexpected slug: {s}"
    return s
