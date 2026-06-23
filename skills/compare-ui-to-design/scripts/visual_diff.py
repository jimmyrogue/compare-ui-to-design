#!/usr/bin/env python3
"""Compare two UI screenshots and mark UI/UX visual-difference regions."""

from __future__ import annotations

import argparse
import json
import math
from collections import deque
from pathlib import Path
from typing import Iterable, NamedTuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont


class Region(NamedTuple):
    region_id: int
    x: int
    y: int
    width: int
    height: int
    area: int
    mean_delta: float
    max_delta: float
    category_hint: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare actual UI and expected design screenshots for UI/UX fidelity."
    )
    parser.add_argument("--actual", required=True, help="Path to actual UI screenshot.")
    parser.add_argument("--expected", required=True, help="Path to expected design image.")
    parser.add_argument("--out-dir", required=True, help="Directory for generated report files.")
    parser.add_argument(
        "--threshold",
        type=float,
        default=12.0,
        help="Per-pixel RGB distance threshold. Lower is stricter. Default: 12.",
    )
    parser.add_argument(
        "--min-area",
        type=int,
        default=16,
        help="Minimum connected changed-pixel area to report. Default: 16.",
    )
    parser.add_argument(
        "--merge-gap",
        type=int,
        default=4,
        help="Merge boxes separated by this many pixels or less. Default: 4.",
    )
    parser.add_argument(
        "--max-regions",
        type=int,
        default=80,
        help="Maximum regions to include before truncating smallest regions. Default: 80.",
    )
    return parser.parse_args()


def load_rgb(path: Path) -> tuple[Image.Image, np.ndarray]:
    image = Image.open(path).convert("RGB")
    return image, np.asarray(image, dtype=np.float32)


def build_difference_mask(
    actual: np.ndarray,
    expected: np.ndarray,
    threshold: float,
) -> tuple[np.ndarray, np.ndarray]:
    delta = np.linalg.norm(actual - expected, axis=2)
    mask = delta >= threshold
    return mask, delta


def denoise_mask(mask: np.ndarray) -> np.ndarray:
    """Remove isolated changed pixels while keeping small coherent UI changes."""
    height, width = mask.shape
    padded = np.pad(mask.astype(np.uint8), 1, mode="constant")
    neighbor_count = np.zeros_like(mask, dtype=np.uint8)

    for dy in range(3):
        for dx in range(3):
            if dx == 1 and dy == 1:
                continue
            neighbor_count += padded[dy : dy + height, dx : dx + width]

    return mask & (neighbor_count >= 2)


def connected_components(mask: np.ndarray, min_area: int) -> list[tuple[int, int, int, int, int, list[tuple[int, int]]]]:
    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    components: list[tuple[int, int, int, int, int, list[tuple[int, int]]]] = []

    for start_y in range(height):
        for start_x in range(width):
            if visited[start_y, start_x] or not mask[start_y, start_x]:
                continue

            queue: deque[tuple[int, int]] = deque([(start_x, start_y)])
            visited[start_y, start_x] = True
            pixels: list[tuple[int, int]] = []
            min_x = max_x = start_x
            min_y = max_y = start_y

            while queue:
                x, y = queue.popleft()
                pixels.append((x, y))
                min_x = min(min_x, x)
                max_x = max(max_x, x)
                min_y = min(min_y, y)
                max_y = max(max_y, y)

                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if nx < 0 or ny < 0 or nx >= width or ny >= height:
                        continue
                    if visited[ny, nx] or not mask[ny, nx]:
                        continue
                    visited[ny, nx] = True
                    queue.append((nx, ny))

            if len(pixels) >= min_area:
                components.append((min_x, min_y, max_x + 1, max_y + 1, len(pixels), pixels))

    return components


def boxes_touch_or_overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int], gap: int) -> bool:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    return not (
        ax2 + gap < bx1
        or bx2 + gap < ax1
        or ay2 + gap < by1
        or by2 + gap < ay1
    )


def merge_components(
    components: list[tuple[int, int, int, int, int, list[tuple[int, int]]]],
    merge_gap: int,
) -> list[tuple[int, int, int, int, int, list[tuple[int, int]]]]:
    merged: list[tuple[int, int, int, int, int, list[tuple[int, int]]]] = []

    for component in components:
        cx1, cy1, cx2, cy2, area, pixels = component
        current_box = (cx1, cy1, cx2, cy2)
        current_pixels = pixels[:]
        current_area = area

        changed = True
        while changed:
            changed = False
            next_merged: list[tuple[int, int, int, int, int, list[tuple[int, int]]]] = []
            for existing in merged:
                ex1, ey1, ex2, ey2, existing_area, existing_pixels = existing
                existing_box = (ex1, ey1, ex2, ey2)
                if boxes_touch_or_overlap(current_box, existing_box, merge_gap):
                    current_box = (
                        min(current_box[0], ex1),
                        min(current_box[1], ey1),
                        max(current_box[2], ex2),
                        max(current_box[3], ey2),
                    )
                    current_pixels.extend(existing_pixels)
                    current_area += existing_area
                    changed = True
                else:
                    next_merged.append(existing)
            merged = next_merged

        merged.append((*current_box, current_area, current_pixels))

    return merged


def category_hint(width: int, height: int, area: int, mean_delta: float) -> str:
    aspect = width / max(height, 1)
    fill_ratio = area / max(width * height, 1)

    if height <= 3 and width >= 12:
        return "border/divider position or color"
    if width <= 3 and height >= 12:
        return "border/divider position or alignment"
    if fill_ratio < 0.18 and (aspect > 4 or aspect < 0.25):
        return "typography/icon edge or alignment"
    if area >= 400 and mean_delta < 28:
        return "background color/shadow/gradient"
    if area >= 400:
        return "module layout/size/visual state"
    if width <= 24 and height <= 24:
        return "typography/icon/image detail"
    return "ui visual difference"


def make_regions(
    components: Iterable[tuple[int, int, int, int, int, list[tuple[int, int]]]],
    delta: np.ndarray,
    max_regions: int,
) -> list[Region]:
    scored = []
    for x1, y1, x2, y2, area, pixels in components:
        pixel_deltas = np.array([delta[y, x] for x, y in pixels], dtype=np.float32)
        mean_delta = float(pixel_deltas.mean()) if len(pixel_deltas) else 0.0
        max_delta = float(pixel_deltas.max()) if len(pixel_deltas) else 0.0
        score = area * math.log(max(mean_delta, 1.0) + 1)
        scored.append((score, x1, y1, x2, y2, area, mean_delta, max_delta))

    scored.sort(reverse=True)
    selected = scored[:max_regions]
    selected.sort(key=lambda item: (item[2], item[1]))

    regions: list[Region] = []
    for idx, (_, x1, y1, x2, y2, area, mean_delta, max_delta) in enumerate(selected, start=1):
        width = x2 - x1
        height = y2 - y1
        regions.append(
            Region(
                region_id=idx,
                x=x1,
                y=y1,
                width=width,
                height=height,
                area=area,
                mean_delta=round(mean_delta, 2),
                max_delta=round(max_delta, 2),
                category_hint=category_hint(width, height, area, mean_delta),
            )
        )

    return regions


def draw_annotations(actual: Image.Image, regions: list[Region]) -> Image.Image:
    annotated = actual.copy().convert("RGB")
    draw = ImageDraw.Draw(annotated)
    font = ImageFont.load_default()

    for region in regions:
        x1 = region.x
        y1 = region.y
        x2 = region.x + region.width
        y2 = region.y + region.height
        label = str(region.region_id)

        draw.rectangle((x1, y1, x2, y2), outline=(255, 36, 36), width=2)
        text_bbox = draw.textbbox((0, 0), label, font=font)
        label_w = text_bbox[2] - text_bbox[0] + 6
        label_h = text_bbox[3] - text_bbox[1] + 4
        label_x = max(0, min(x1, annotated.width - label_w))
        label_y = max(0, y1 - label_h)
        draw.rectangle(
            (label_x, label_y, label_x + label_w, label_y + label_h),
            fill=(255, 36, 36),
        )
        draw.text((label_x + 3, label_y + 2), label, fill=(255, 255, 255), font=font)

    return annotated


def draw_heatmap(delta: np.ndarray) -> Image.Image:
    clipped = np.clip(delta, 0, 96)
    normalized = (clipped / 96.0 * 255).astype(np.uint8)
    heatmap = np.zeros((delta.shape[0], delta.shape[1], 3), dtype=np.uint8)
    heatmap[..., 0] = normalized
    heatmap[..., 1] = (normalized * 0.18).astype(np.uint8)
    heatmap[..., 2] = 255 - normalized
    return Image.fromarray(heatmap)


def save_regions(
    out_dir: Path,
    actual_path: Path,
    expected_path: Path,
    actual_size: tuple[int, int],
    expected_size: tuple[int, int],
    threshold: float,
    min_area: int,
    merge_gap: int,
    regions: list[Region],
) -> None:
    payload = {
        "actual": str(actual_path),
        "expected": str(expected_path),
        "audit_focus": (
            "UI/UX structure and visual fidelity: module position, size, border, "
            "background, color, gradient, spacing, margin, padding, typography metrics, "
            "icon/image size, alignment, and visual state."
        ),
        "ignored_by_default": [
            "copy-only text differences",
            "dynamic data differences",
            "timestamps and counters",
            "fetched labels or names",
            "rasterization-only noise",
        ],
        "actual_size": {"width": actual_size[0], "height": actual_size[1]},
        "expected_size": {"width": expected_size[0], "height": expected_size[1]},
        "parameters": {
            "threshold": threshold,
            "min_area": min_area,
            "merge_gap": merge_gap,
        },
        "regions": [
            {
                "id": region.region_id,
                "x": region.x,
                "y": region.y,
                "width": region.width,
                "height": region.height,
                "area": region.area,
                "mean_delta": region.mean_delta,
                "max_delta": region.max_delta,
                "category_hint": region.category_hint,
            }
            for region in regions
        ],
    }
    (out_dir / "regions.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    actual_path = Path(args.actual).expanduser().resolve()
    expected_path = Path(args.expected).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    actual_image, actual_array = load_rgb(actual_path)
    expected_image, expected_array = load_rgb(expected_path)

    if actual_image.size != expected_image.size:
        raise SystemExit(
            "actual and expected images must have the same pixel size; "
            f"got actual={actual_image.size} expected={expected_image.size}"
        )

    mask, delta = build_difference_mask(actual_array, expected_array, args.threshold)
    mask = denoise_mask(mask)
    components = connected_components(mask, args.min_area)
    merged = merge_components(components, args.merge_gap)
    regions = make_regions(merged, delta, args.max_regions)

    annotated = draw_annotations(actual_image, regions)
    heatmap = draw_heatmap(delta)

    annotated.save(out_dir / "annotated_actual.png")
    heatmap.save(out_dir / "diff_heatmap.png")
    save_regions(
        out_dir=out_dir,
        actual_path=actual_path,
        expected_path=expected_path,
        actual_size=actual_image.size,
        expected_size=expected_image.size,
        threshold=args.threshold,
        min_area=args.min_area,
        merge_gap=args.merge_gap,
        regions=regions,
    )

    print(f"Wrote {len(regions)} region(s) to {out_dir}")
    print(f"- {out_dir / 'annotated_actual.png'}")
    print(f"- {out_dir / 'diff_heatmap.png'}")
    print(f"- {out_dir / 'regions.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
