"""Gradient-preserving silhouette packing.

The invariants that make the poster read cleanly:
  1. x position is monotonic in hue (pink → red → orange → yellow → green →
     blue → purple), so sweeping horizontally moves through the spectrum.
  2. Sprites are grouped into equal-load vertical hue columns; within a column
     everything shares a hue family and is sorted light → dark top-to-bottom.
     A sprite may only nudge sideways within its column (± a small overhang),
     so vertical slices never drift into a neighboring color.
  3. Grayscale Pokémon get their own band on the far left, sweeping black →
     white so it hands off seamlessly into the light pinks — no gutter, the
     two bands interlock like any neighboring columns.

Packing is pixel-perfect gravity: each sprite tries a fan of x offsets and
rises to the smallest y where its (1px-dilated) mask doesn't collide with
anything already placed — so silhouettes tuck into concavities and interlock
like a jigsaw. A skyline gives a guaranteed upper bound so the search is
cheap. A second pass paces each column toward a shared target height, so the
poster ends as a clean rectangle with the slack spread invisibly.
"""
from __future__ import annotations

import sys

import numpy as np

from .common import (
    ANALYSIS_JSON, LAYOUT_JSON, SPRITES_DEFAULT, SPRITES_SHINY,
    load_json, save_json,
)
from .analyze import crop_to_mask, load_sprite

HUE_ANCHOR = 335.0  # OKLab hue where the sweep starts (pinks, next to white);
                    # the wheel is cut between magenta and pink so the right
                    # edge ends purple → magenta, staying wheel-continuous
ASPECT = 2.35       # target W/H of the poster
FILL_EST = 0.60     # estimated silhouette fill, used to size the canvas
COL_W = 120         # nominal hue-column width (sprites are ≤96 wide)
OVERHANG = 34       # how far a sprite may lean into neighboring columns
X_STEP = 3          # candidate x-offset granularity
REBALANCE_ITERS = 5 # measuring passes before the final justified pack
DAMPING = 0.75      # rebalance feedback exponent (avoids oscillation)
GUTTER = 0          # bands abut directly; sprites interlock across the seam
PAD = 1             # dilation of masks -> min gap between sprites
ORDER_SLACK = 0.35  # a sprite may rise this fraction of its height above the
                    # previous one before lightness order would visibly break
TIE_PX = 4          # candidates within this many px of the best y compete on snugness


def dilate(mask: np.ndarray, r: int = 1) -> np.ndarray:
    out = mask.copy()
    for _ in range(r):
        p = np.pad(out, 1)
        out = (p[1:-1, 1:-1] | p[:-2, 1:-1] | p[2:, 1:-1]
               | p[1:-1, :-2] | p[1:-1, 2:])
    return out


def profiles(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-x-column top offset, bottom offset (exclusive), and opacity flag."""
    h = mask.shape[0]
    any_col = mask.any(axis=0)
    top = np.where(any_col, mask.argmax(axis=0), h)
    bot = np.where(any_col, h - mask[::-1].argmax(axis=0), 0)
    return top.astype(np.int32), bot.astype(np.int32), any_col


def load_mask(rec: dict) -> np.ndarray:
    folder = SPRITES_SHINY if rec["shiny"] else SPRITES_DEFAULT
    rgba = load_sprite(folder / f"{rec['id']}.png")
    cropped = crop_to_mask(rgba)
    assert cropped is not None
    _, mask = cropped
    assert mask.shape == (rec["h"], rec["w"]), f"mask mismatch for {rec['label']}"
    return mask


def load_key(r: dict) -> float:
    """Predictor of vertical space a sprite consumes when packed."""
    return r.get("_adj") or float(np.sqrt(r["area"] * r["w"] * r["h"]))


def partition_equal_load(recs: list[dict], n_cols: int) -> list[list[dict]]:
    """Split an ordered list into n contiguous groups of ~equal packing load."""
    total = sum(load_key(r) for r in recs)
    cols: list[list[dict]] = [[] for _ in range(n_cols)]
    acc = 0.0
    for r in recs:
        i = min(n_cols - 1, int(acc * n_cols / total))
        cols[i].append(r)
        acc += load_key(r)
    return [c for c in cols if c]


def rebalance(cols: list[list[dict]], heights: list[int]) -> None:
    """Reweight sprites by how efficiently their pass-1 column actually packed,
    so the next partition gives inefficient (tall) columns less to carry."""
    effs = [h / sum(load_key(r) for r in col) for col, h in zip(cols, heights)]
    mean_eff = float(np.mean(effs))
    for col, eff in zip(cols, effs):
        for r in col:
            r["_adj"] = load_key(r) * (eff / mean_eff) ** DAMPING


class Packer:
    def __init__(self, width: int, height_hint: int):
        self.width = width
        self.occ = np.zeros((height_hint, width), dtype=bool)
        self.bottom = np.zeros(width, dtype=np.int32)

    def _ensure(self, rows: int) -> None:
        if rows > self.occ.shape[0]:
            extra = np.zeros((rows - self.occ.shape[0] + 256, self.width), dtype=bool)
            self.occ = np.vstack([self.occ, extra])

    def _min_free_y(self, mask: np.ndarray, x: int, y_lo: int, y_sky: int) -> int:
        """Smallest y in [y_lo, y_sky] where mask fits; y_sky is always free."""
        h, w = mask.shape
        for y in range(y_lo, y_sky):
            if not np.any(self.occ[y:y + h, x:x + w] & mask):
                return y
        return y_sky

    def place(self, sprite: dict, x_lo: int, x_hi: int, y_floor: int) -> tuple[int, int]:
        mask, contact_mask = sprite["_mask"], sprite["_contact"]
        top, bot, opaque = sprite["_prof"]
        h, w = mask.shape
        y_floor = max(0, y_floor)
        xs = list(range(x_lo, x_hi + 1, X_STEP)) if x_hi >= x_lo else [x_lo]

        found: list[tuple[int, int]] = []
        for x in xs:
            seg = self.bottom[x:x + w]
            # Resting-on-skyline y for this x; if the floor is below it, the
            # sprite floats at the floor (that's how columns get justified —
            # everything below the skyline in this x-range is empty air).
            y_sky = max(int(np.max((seg - top)[opaque])), y_floor) if opaque.any() else y_floor
            self._ensure(y_sky + h + 2)
            y = self._min_free_y(mask, x, y_floor, y_sky)
            found.append((y, x))

        y_min = min(y for y, _ in found)
        best_x, best_y, best_contact = None, None, -1
        for y, x in found:
            if y > y_min + TIE_PX:
                continue
            contact = int(np.count_nonzero(self.occ[y:y + h, x:x + w] & contact_mask))
            if contact > best_contact:
                best_x, best_y, best_contact = x, y, contact

        self._ensure(best_y + h + 1)
        self.occ[best_y:best_y + h, best_x:best_x + w] |= mask
        seg = self.bottom[best_x:best_x + w]
        np.maximum(seg, np.where(opaque, best_y + bot, 0), out=seg)
        return best_x, best_y


def pack_band(recs_cols: list[list[dict]], packer: Packer, x_offset: int,
              col_w: float, band_lo: int, band_hi: int,
              target_h: int | None) -> list[dict]:
    """Pack columns of sprites left to right; returns per-column metadata."""
    col_meta = []
    for k, col in enumerate(recs_cols):
        cx0 = x_offset + int(round(k * col_w))
        cx1 = x_offset + int(round((k + 1) * col_w))
        col_load = sum(load_key(r) for r in col)
        mean_h = int(np.mean([r["h"] for r in col]))
        acc = 0.0
        prev_top = -(10 ** 9)
        for r in col:
            w = r["w"]
            x_lo = max(band_lo, cx0 - OVERHANG)
            x_hi = min(band_hi - w, cx1 - w + OVERHANG)
            if x_hi < x_lo:
                x_lo = x_hi = max(band_lo, min(band_hi - w, (cx0 + cx1 - w) // 2))
            floor = prev_top - int(r["h"] * ORDER_SLACK)
            if target_h is not None:
                pace = int(acc / col_load * max(0, target_h - mean_h))
                floor = max(floor, pace)
            x, y = packer.place(r, x_lo, x_hi, floor)
            r["x"], r["y"] = int(x), int(y)
            prev_top = y
            acc += load_key(r)
        # column swatch: area-weighted mean of representative colors
        rgbs = np.array([[int(r["hex"][i:i + 2], 16) for i in (1, 3, 5)] for r in col])
        wts = np.array([r["area"] for r in col], dtype=float)
        mean_rgb = (rgbs * wts[:, None]).sum(0) / wts.sum()
        col_meta.append({
            "x0": cx0, "x1": cx1,
            "hex": "#{:02x}{:02x}{:02x}".format(*(int(round(v)) for v in mean_rgb)),
            "n": len(col),
        })
    return col_meta


def run_pass(neutral_cols, colored_cols, w_neutral: int, width: int, height_hint: int,
             ncol_w: float, col_w: float, target_h: int | None):
    packer = Packer(width, height_hint)
    meta_n = pack_band(neutral_cols, packer, 0, ncol_w, 0, width, target_h)
    meta_c = pack_band(colored_cols, packer, w_neutral + GUTTER, col_w,
                       0, width, target_h)
    heights = [max(r["y"] + r["h"] for r in col) for col in neutral_cols + colored_cols]
    return meta_n, meta_c, heights


def main() -> int:
    records = load_json(ANALYSIS_JSON)
    colored = [r for r in records if not r["neutral"]]
    neutral = [r for r in records if r["neutral"]]

    colored.sort(key=lambda r: ((r["hue"] - HUE_ANCHOR) % 360.0, -r["sortL"]))
    neutral.sort(key=lambda r: r["sortL"])  # black → white, left → right

    print(f"Loading {len(records)} masks ...")
    for r in records:
        mask = dilate(load_mask(r), PAD)
        r["_mask"] = mask
        r["_contact"] = dilate(mask, 2)
        r["_prof"] = profiles(mask)

    load_c = sum(load_key(r) for r in colored)
    load_n = sum(load_key(r) for r in neutral)
    total = load_c + load_n
    height = int(np.sqrt(total / (FILL_EST * ASPECT)))
    w_color = int(load_c / (FILL_EST * height))
    w_neutral = int(load_n / (FILL_EST * height))
    width = w_neutral + GUTTER + w_color

    n_cols = max(1, round(w_color / COL_W))
    n_ncols = max(1, round(w_neutral / COL_W))
    col_w = w_color / n_cols
    ncol_w = w_neutral / n_ncols
    print(f"Canvas ≈ {width}×{height}, {n_cols} hue columns + {n_ncols} neutral")

    def make_columns():
        ncols = partition_equal_load(neutral, n_ncols)
        for c in ncols:
            c.sort(key=lambda r: -r["sortL"])  # keep light → dark within a column
        return ncols, partition_equal_load(colored, n_cols)

    neutral_cols, colored_cols = make_columns()

    # Measuring passes: pack, observe each hue slice's real packing
    # efficiency, and rebalance the partition so natural heights converge.
    for it in range(REBALANCE_ITERS):
        _, _, heights = run_pass(neutral_cols, colored_cols, w_neutral, width,
                                 height + 512, ncol_w, col_w, None)
        print(f"Measure pass {it + 1}: column heights {min(heights)}–{max(heights)}"
              f" (median {int(np.median(heights))})")
        rebalance(neutral_cols + colored_cols, heights)
        neutral_cols, colored_cols = make_columns()

    # Final pass: pace every column toward the shared target height so the
    # poster ends as a clean rectangle. Post-rebalance spread is small, so
    # the injected slack stays invisible (a few px between sprites).
    target_h = int(np.percentile(heights, 90))
    print(f"Target height {target_h}")
    meta_n, meta_c, heights = run_pass(neutral_cols, colored_cols, w_neutral,
                                       width, target_h + 256, ncol_w, col_w, target_h)

    final_h = max(heights)
    mask_area = sum(r["area"] for r in records)
    fill = mask_area / (width * final_h)
    print(f"Final canvas {width}×{final_h}, silhouette fill {fill:.1%}, "
          f"column heights {min(heights)}–{max(heights)}")

    order = 0
    sprites = []
    for col in neutral_cols + colored_cols:
        for r in col:
            sprites.append({
                "id": r["id"], "shiny": r["shiny"], "label": r["label"],
                "name": r["name"], "form": r["form"], "aka": r["aka"],
                "hex": r["hex"], "neutral": r["neutral"],
                "x": r["x"], "y": r["y"], "w": r["w"], "h": r["h"],
                "o": order,
            })
            order += 1

    save_json(LAYOUT_JSON, {
        "meta": {
            "width": width, "height": final_h,
            "wNeutral": w_neutral, "gutter": GUTTER,
            "count": len(sprites),
            "columns": [dict(m, neutral=True) for m in meta_n] + meta_c,
        },
        "sprites": sprites,
    }, compact=True)
    print(f"Wrote {LAYOUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
