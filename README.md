# Pokémon Spectrum

Every Pokémon — every form, every mega, every regional variant, and every
shiny (~2,600 sprites) — packed into one continuous, color-sorted mosaic.

**▶ Live demo: <https://kervinch.github.io/pokemon-color-sort/>**

Sweep left to right and the poster moves from black through white, then
through the spectrum: pinks → reds → oranges → yellows → greens → blues →
purples. Any vertical slice is a single color family, shading light at the
top to dark at the bottom. Grayscale Pokémon form the opening band on the
left, handing off from white into the light pinks with no seam. Silhouettes
are packed pixel-tight, so shapes nest into each other like a jigsaw.

## Quick start

```bash
./run.sh
```

First run builds everything (downloads ~2,700 sprites from PokeAPI, analyzes
colors, packs the layout, renders assets — roughly 15 minutes), then serves
the viewer at <http://localhost:8123/viewer/> and opens your browser. Later
runs start instantly from cache.

Requires Python 3.10+ with `Pillow` and `numpy` (run.sh installs them if
missing). No other dependencies — the viewer is plain HTML/JS.

## The viewer

- **Pan / zoom** — drag and scroll (pinch works too); `0` fits, `1` is 100%
- **Hover** any Pokémon to identify it: name, form, shiny, dominant color
- **Search** (`/`) — try `charizard`, `mega`, `alola`, `shiny`; Enter cycles
  through matches, Esc clears
- **Spectrum bar** — click a color under the header to jump there
- **Export PNG** — 1×/2×/3×, optional transparent background
- **Replay** — watch the mosaic assemble itself sprite by sprite
- **◐** — toggle dark / light background

The finished poster is also written to `viewer/assets/mosaic.png`.

## How it works

```text
pipeline/fetch.py    Roster from PokeAPI (/pokemon, all forms), then default
                     + shiny sprites from the PokeAPI sprites repo. Cached,
                     resumable; byte-identical duplicates merged later.
pipeline/analyze.py  Per sprite: silhouette mask and perceived dominant color
                     in OKLab. Only opaque pixels count, dark outlines are
                     excluded, and pixels vote for a hue weighted by chroma —
                     so an orange Pokémon with teal wings reads orange, not
                     gray mush. Low overall chroma ⇒ grayscale class.
pipeline/layout.py   The gradient packing. Grayscale Pokémon open the poster
                     in a black → white band; colored sprites then sort by
                     OKLab hue into equal-load vertical columns (x = hue,
                     strictly monotonic); within a column they sort
                     light → dark.
                     Packing is pixel-mask gravity: each sprite tries a fan
                     of x offsets inside its column and settles at the
                     highest collision-free spot, nesting into concavities.
                     Measuring passes rebalance the columns until natural
                     heights converge, then a final pass paces every column
                     to one shared height, so the poster is a clean rectangle.
pipeline/render.py   Composites mosaic.png, a sprite atlas, packed 1-bit
                     silhouette masks (pixel-exact hover), and layout.json.
viewer/              Static canvas app: pan/zoom over a full-res offscreen
                     world canvas, spatial-hash + bitmask hit-testing,
                     search highlighting, assembly animation, PNG export.
```

Rebuild after changing pipeline code: `python3 -m pipeline.build --force`
(stages are also skipped/rerun automatically based on file freshness).

## Credits

Sprite art via [PokeAPI/sprites](https://github.com/PokeAPI/sprites).

## Copyright & disclaimer

This is an **unofficial, non-commercial fan project**. It is **not affiliated
with, sponsored by, or endorsed by** Nintendo, Creatures Inc., GAME FREAK inc.,
The Pokémon Company, or any of their affiliates.

**Pokémon © Nintendo, Creatures Inc., and GAME FREAK inc.** "Pokémon,"
Pokémon character names, and all related characters, sprite artwork, and
designs are trademarks and/or copyrighted works of their respective owners.
All rights in that material are reserved by those owners.

The Pokémon sprite artwork shown here — including the pre-rendered assets in
[`viewer/assets/`](viewer/assets/) (`mosaic.png`, `atlas.png`, `masks.bin`)
and any sprites downloaded at build time — is used here only to create a
transformative, non-commercial visualization for artistic and educational
purposes. No ownership of that artwork is claimed, and it is **not** covered
by this project's license.

If you are a rights holder and would like this content changed or removed,
please open an issue on the repository and it will be taken down promptly.

## License

The **original source code** of this project — everything under
[`pipeline/`](pipeline/), the viewer app (`viewer/app.js`, `viewer/style.css`,
`viewer/index.html`, `index.html`), and the build/config files — is released
under the [MIT License](LICENSE).

The MIT license does **not** extend to any Pokémon sprite artwork, names, or
other Pokémon assets (see **Copyright & disclaimer** above); those remain the
property of their respective owners.
