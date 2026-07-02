"""Download the full Pokémon roster (all forms) and their default + shiny sprites.

Resumable: existing files are skipped, known-missing URLs are remembered in
data/missing.json so re-runs don't re-hit 404s.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .common import (
    LIST_URL, MISSING_JSON, POKEMON_LIST_JSON, SHINY_URL, SPRITE_URL,
    SPRITES_DEFAULT, SPRITES_SHINY, id_from_url, load_json, save_json,
)

UA = {"User-Agent": "pokemon-color-mosaic/1.0 (art project; contact: local)"}
WORKERS = 16
RETRIES = 3


def http_get(url: str, timeout: int = 30) -> bytes:
    last_err: Exception | None = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            last_err = e
        except Exception as e:  # noqa: BLE001 - retry on transient network errors
            last_err = e
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"failed after {RETRIES} tries: {url}") from last_err


def fetch_pokemon_list() -> list[dict]:
    if POKEMON_LIST_JSON.exists():
        return load_json(POKEMON_LIST_JSON)
    print("Fetching Pokémon roster from PokeAPI ...")
    raw = json.loads(http_get(LIST_URL))
    entries = [{"name": r["name"], "id": id_from_url(r["url"])} for r in raw["results"]]
    entries.sort(key=lambda e: e["id"])
    save_json(POKEMON_LIST_JSON, entries)
    print(f"  {len(entries)} Pokémon entries (species + forms)")
    return entries


def _download_one(url: str, dest: Path, missing: set[str]) -> str:
    if dest.exists():
        return "cached"
    if url in missing:
        return "missing"
    try:
        data = http_get(url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            missing.add(url)
            return "missing"
        raise
    if len(data) < 100:  # not a real PNG
        missing.add(url)
        return "missing"
    tmp = dest.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.rename(dest)
    return "downloaded"


def fetch_sprites(entries: list[dict]) -> None:
    SPRITES_DEFAULT.mkdir(parents=True, exist_ok=True)
    SPRITES_SHINY.mkdir(parents=True, exist_ok=True)
    missing: set[str] = set(load_json(MISSING_JSON)) if MISSING_JSON.exists() else set()

    jobs: list[tuple[str, Path]] = []
    for e in entries:
        pid = e["id"]
        jobs.append((SPRITE_URL.format(id=pid), SPRITES_DEFAULT / f"{pid}.png"))
        jobs.append((SHINY_URL.format(id=pid), SPRITES_SHINY / f"{pid}.png"))

    counts = {"downloaded": 0, "cached": 0, "missing": 0}
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(_download_one, url, dest, missing): url for url, dest in jobs}
        for fut in as_completed(futures):
            counts[fut.result()] += 1
            done += 1
            if done % 200 == 0:
                print(f"  {done}/{len(jobs)} "
                      f"(new {counts['downloaded']}, cached {counts['cached']}, "
                      f"missing {counts['missing']})", flush=True)

    save_json(MISSING_JSON, sorted(missing))
    print(f"Sprites: {counts['downloaded']} downloaded, {counts['cached']} cached, "
          f"{counts['missing']} missing/404")


def main() -> int:
    entries = fetch_pokemon_list()
    fetch_sprites(entries)
    n_def = len(list(SPRITES_DEFAULT.glob("*.png")))
    n_shiny = len(list(SPRITES_SHINY.glob("*.png")))
    print(f"On disk: {n_def} default + {n_shiny} shiny = {n_def + n_shiny} sprites")
    return 0


if __name__ == "__main__":
    sys.exit(main())
