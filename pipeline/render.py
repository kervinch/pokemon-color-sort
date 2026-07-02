"""Render viewer assets from the layout:

  viewer/assets/mosaic.png   — the finished poster (transparent background)
  viewer/assets/atlas.png    — every sprite in a grid, powers the live
                               assembly animation / search highlights / tooltips
  viewer/assets/masks.bin    — packed 1-bit silhouette masks (row-padded to
                               bytes, sprite order), for pixel-exact hover
  viewer/assets/layout.json  — updated with atlas grid info
"""
from __future__ import annotations

import math
import sys
import time

import numpy as np
from PIL import Image

from .common import CELL, LAYOUT_JSON, OUT, SPRITES_DEFAULT, SPRITES_SHINY, load_json, save_json
from .analyze import LANCZOS, crop_to_mask, load_sprite


def sprite_image(s: dict) -> tuple[Image.Image, np.ndarray]:
    folder = SPRITES_SHINY if s["shiny"] else SPRITES_DEFAULT
    rgba = load_sprite(folder / f"{s['id']}.png")
    cropped = crop_to_mask(rgba)
    assert cropped is not None
    rgba_c, mask = cropped
    img = Image.fromarray((rgba_c * 255).round().astype(np.uint8), "RGBA")
    return img, mask


def main() -> int:
    doc = load_json(LAYOUT_JSON)
    meta, sprites = doc["meta"], doc["sprites"]
    sprites.sort(key=lambda s: s["o"])

    W, H = meta["width"], meta["height"]
    mosaic = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    acols = math.ceil(math.sqrt(len(sprites)))
    arows = math.ceil(len(sprites) / acols)
    atlas = Image.new("RGBA", (acols * CELL, arows * CELL), (0, 0, 0, 0))

    mask_bytes = bytearray()
    for i, s in enumerate(sprites):
        if i % 500 == 0:
            print(f"  compositing {i}/{len(sprites)}", flush=True)
        img, mask = sprite_image(s)
        mosaic.paste(img, (s["x"], s["y"]), img)
        ax, ay = (i % acols) * CELL, (i // acols) * CELL
        atlas.paste(img, (ax + (CELL - s["w"]) // 2, ay + (CELL - s["h"]) // 2), img)
        mask_bytes.extend(np.packbits(mask, axis=1).tobytes())

    OUT.mkdir(parents=True, exist_ok=True)
    mosaic.save(OUT / "mosaic.png", optimize=True)
    atlas.save(OUT / "atlas.png", optimize=True)
    (OUT / "masks.bin").write_bytes(bytes(mask_bytes))

    meta["atlasCols"] = acols
    meta["cell"] = CELL
    meta["builtAt"] = int(time.time())  # cache-buster for viewer assets
    save_json(LAYOUT_JSON, doc, compact=True)

    for name in ("mosaic.png", "atlas.png", "masks.bin", "layout.json"):
        print(f"  {name}: {(OUT / name).stat().st_size / 1e6:.1f} MB")

    # Downscaled preview on dark background, for quick eyeballing
    prev = Image.new("RGBA", (W, H), (13, 15, 18, 255))
    prev.alpha_composite(mosaic)
    pw = 1800
    prev = prev.resize((pw, round(H * pw / W)), LANCZOS).convert("RGB")
    prev.save(OUT.parent.parent / "data" / "preview.png")
    print("Wrote preview to data/preview.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
