"""Run the full pipeline: fetch → analyze → layout → render.

Usage:
    python3 -m pipeline.build [--force]

Stages are skipped when their outputs already exist and are newer than their
inputs; --force reruns everything (downloads stay cached regardless).
"""
from __future__ import annotations

import sys

from . import analyze, fetch, layout, render
from .common import ANALYSIS_JSON, LAYOUT_JSON, OUT, POKEMON_LIST_JSON


def stale(output, *inputs) -> bool:
    if not output.exists():
        return True
    out_m = output.stat().st_mtime
    return any(i.exists() and i.stat().st_mtime > out_m for i in inputs)


def main() -> int:
    force = "--force" in sys.argv

    print("── stage 1/4: fetch ─────────────────────────")
    fetch.main()

    print("── stage 2/4: analyze ───────────────────────")
    if force or stale(ANALYSIS_JSON, POKEMON_LIST_JSON):
        analyze.main()
    else:
        print("analysis.json up to date, skipping (use --force to redo)")

    print("── stage 3/4: layout ────────────────────────")
    if force or stale(LAYOUT_JSON, ANALYSIS_JSON):
        layout.main()
    else:
        print("layout.json up to date, skipping (use --force to redo)")

    print("── stage 4/4: render ────────────────────────")
    if force or stale(OUT / "mosaic.png", LAYOUT_JSON):
        render.main()
    else:
        print("mosaic.png up to date, skipping (use --force to redo)")

    print("\nDone. Open the viewer:  ./run.sh   (or: python3 -m http.server "
          "8123, then http://localhost:8123/viewer/)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
