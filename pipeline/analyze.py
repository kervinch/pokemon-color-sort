"""Per-sprite analysis: silhouette mask + perceived dominant color in OKLab.

The "main color" is what the eye actually sees:
- only opaque pixels count (background ignored)
- near-black outline pixels are excluded from the body
- pixels vote for a hue weighted by chroma (saturated areas dominate), the
  winning hue neighborhood defines the representative color — so a Pokémon
  with orange body + teal wings reads orange, not muddy gray-average
- low overall chroma → classified neutral (grayscale family)
"""
from __future__ import annotations

import hashlib
import sys

import numpy as np
from PIL import Image

LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS")

from .common import (
    ANALYSIS_JSON, CELL, POKEMON_LIST_JSON, SPRITES_DEFAULT, SPRITES_SHINY,
    load_json, pretty_name, save_json, sorted_species_slugs,
)

ALPHA_T = 0.5          # opacity threshold for silhouette
OUTLINE_L = 0.23       # OKLab L below this = outline candidate
HUE_BINS = 48
HUE_WINDOW = 40.0      # degrees around peak hue counted as "dominant"
NEUTRAL_CHROMA = 0.042 # mean body chroma below this = grayscale Pokémon
DOMINANT_MIN_C = 0.055 # dominant set must be at least this chromatic


def srgb_to_oklab(rgb: np.ndarray) -> np.ndarray:
    """rgb in [0,1], shape (...,3) -> OKLab (...,3)."""
    c = rgb.astype(np.float64)
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m1 = np.array([
        [0.4122214708, 0.5363325363, 0.0514459929],
        [0.2119034982, 0.6806995451, 0.1073969566],
        [0.0883024619, 0.2817188376, 0.6299787005],
    ])
    lms = lin @ m1.T
    lms_ = np.cbrt(lms)
    m2 = np.array([
        [0.2104542553, 0.7936177850, -0.0040720468],
        [1.9779984951, -2.4285922050, 0.4505937099],
        [0.0259040371, 0.7827717662, -0.8086757660],
    ])
    return lms_ @ m2.T


def oklab_l_to_gray(L: float) -> tuple[int, int, int]:
    """Invert OKLab L to an sRGB gray level."""
    lin = L ** 3
    s = np.clip(np.where(lin <= 0.0031308, lin * 12.92,
                         1.055 * lin ** (1 / 2.4) - 0.055), 0, 1)
    v = int(round(float(s) * 255))
    return (v, v, v)


def load_sprite(path) -> np.ndarray:
    """Load a sprite as float RGBA (H,W,4) in [0,1], fit into CELL box if larger."""
    img = Image.open(path).convert("RGBA")
    if img.width > CELL or img.height > CELL:
        scale = min(CELL / img.width, CELL / img.height)
        img = img.resize((max(1, round(img.width * scale)),
                          max(1, round(img.height * scale))), LANCZOS)
    return np.asarray(img, dtype=np.float64) / 255.0


def crop_to_mask(rgba: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """Return (cropped rgba, cropped bool mask) or None if empty."""
    mask = rgba[..., 3] > ALPHA_T
    if not mask.any():
        return None
    ys, xs = np.where(mask)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    return rgba[y0:y1, x0:x1], mask[y0:y1, x0:x1]


def analyze_colors(rgba: np.ndarray, mask: np.ndarray) -> dict:
    rgb = rgba[..., :3][mask]
    lab = srgb_to_oklab(rgb)
    L, a, b = lab[:, 0], lab[:, 1], lab[:, 2]
    C = np.hypot(a, b)

    # Body = silhouette minus dark outline (unless the Pokémon *is* dark)
    body = L > OUTLINE_L
    if body.mean() < 0.25:
        body = np.ones_like(body)
    Lb, Cb = L[body], C[body]
    ab, bb = a[body], b[body]
    rgb_b = rgb[body]

    sort_l = float(Lb.mean())
    mean_c = float(Cb.mean())

    # Chroma-weighted hue vote
    w = Cb ** 1.5
    hue = np.degrees(np.arctan2(bb, ab)) % 360.0
    result = {"sortL": round(sort_l, 4)}

    total_w = float(w.sum())
    if mean_c < NEUTRAL_CHROMA or total_w <= 1e-9:
        return _neutral(result, sort_l)

    bins = (hue / (360.0 / HUE_BINS)).astype(int) % HUE_BINS
    hist = np.bincount(bins, weights=w, minlength=HUE_BINS)
    kernel = np.array([1.0, 2.0, 3.0, 2.0, 1.0])
    smoothed = np.convolve(np.tile(hist, 3), kernel, mode="same")[HUE_BINS:2 * HUE_BINS]
    peak_center = (int(np.argmax(smoothed)) + 0.5) * (360.0 / HUE_BINS)

    diff = np.abs((hue - peak_center + 180.0) % 360.0 - 180.0)
    dom = (diff <= HUE_WINDOW) & (Cb > 0.03)
    if not dom.any() or float(C[body][dom].mean()) < DOMINANT_MIN_C:
        return _neutral(result, sort_l)

    wd = w[dom]
    # Circular weighted mean hue of the dominant set
    sin_m = float(np.average(np.sin(np.radians(hue[dom])), weights=wd))
    cos_m = float(np.average(np.cos(np.radians(hue[dom])), weights=wd))
    dom_hue = float(np.degrees(np.arctan2(sin_m, cos_m)) % 360.0)

    rep = np.average(rgb_b[dom], axis=0, weights=wd)
    rep255 = tuple(int(round(float(v) * 255)) for v in np.clip(rep, 0, 1))

    result.update({
        "neutral": False,
        "hue": round(dom_hue, 2),
        "chroma": round(float(C[body][dom].mean()), 4),
        "hex": "#{:02x}{:02x}{:02x}".format(*rep255),
    })
    return result


def _neutral(result: dict, sort_l: float) -> dict:
    g = oklab_l_to_gray(sort_l)
    result.update({
        "neutral": True,
        "hue": 0.0,
        "chroma": 0.0,
        "hex": "#{:02x}{:02x}{:02x}".format(*g),
    })
    return result


def main() -> int:
    entries = load_json(POKEMON_LIST_JSON)
    species_slugs = sorted_species_slugs(entries)
    by_id = {e["id"]: e["name"] for e in entries}

    records = []
    seen_md5: dict[str, dict] = {}
    skipped_dupes = 0

    files = []
    for e in entries:
        pid = e["id"]
        for shiny, folder in ((False, SPRITES_DEFAULT), (True, SPRITES_SHINY)):
            p = folder / f"{pid}.png"
            if p.exists():
                files.append((pid, shiny, p))

    for i, (pid, shiny, path) in enumerate(files):
        if i % 400 == 0:
            print(f"  analyzing {i}/{len(files)}", flush=True)
        digest = hashlib.md5(path.read_bytes()).hexdigest()
        dup = seen_md5.get(digest)
        slug = by_id[pid]
        species, form = pretty_name(slug, pid, species_slugs)
        label = species + (f" ({form})" if form else "") + (" ✨" if shiny else "")
        if dup is not None:
            dup["aka"].append(label)
            skipped_dupes += 1
            continue

        rgba = load_sprite(path)
        cropped = crop_to_mask(rgba)
        if cropped is None:
            continue
        rgba_c, mask = cropped
        rec = analyze_colors(rgba_c, mask)
        rec.update({
            "id": pid,
            "shiny": shiny,
            "slug": slug,
            "name": species,
            "form": form,
            "label": label,
            "aka": [],
            "w": int(mask.shape[1]),
            "h": int(mask.shape[0]),
            "area": int(mask.sum()),
        })
        seen_md5[digest] = rec
        records.append(rec)

    save_json(ANALYSIS_JSON, records, compact=True)
    n_neutral = sum(1 for r in records if r["neutral"])
    print(f"Analyzed {len(records)} unique sprites "
          f"({skipped_dupes} exact duplicates merged, {n_neutral} neutral/grayscale)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
