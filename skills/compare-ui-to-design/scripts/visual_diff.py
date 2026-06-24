#!/usr/bin/env python3
"""Compare two UI screenshots and mark UI/UX visual-difference regions."""

from __future__ import annotations

import argparse
import json
import math
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageDraw, ImageFont


REPORT_MODE_DEPTHS = {
    "structure": 1,
    "module": 3,
    "detail": 5,
    "raw": 9,
}

Component = tuple[int, int, int, int, int, list[tuple[int, int]]]


@dataclass
class Region:
    region_id: int
    x: int
    y: int
    width: int
    height: int
    area: int
    mean_delta: float
    max_delta: float
    category_hint: str
    level: int = 3
    parent_id: int | None = None
    priority: float = 0.0
    display_depth: int = 9
    suppressed_by: int | None = None
    report_group: str = ""
    report_id: int | None = None
    source_region_ids: tuple[int, ...] = field(default_factory=tuple)
    element_kind: str = "ui visual region"
    dominant_signal: str = "rgb"
    signal_counts: dict[str, int] = field(default_factory=dict)
    signal_strengths: dict[str, float] = field(default_factory=dict)
    severity_score: float = 0.0
    confidence_score: float = 0.0
    confidence_level: str = "medium"
    severity_factors: list[str] = field(default_factory=list)
    priority_category: str = "ui visual difference"
    priority_tier: int = 9

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def bbox_area(self) -> int:
        return self.width * self.height


@dataclass
class DiffSignals:
    rgb_delta: np.ndarray
    color_delta: np.ndarray
    structure_delta: np.ndarray
    edge_delta: np.ndarray
    rgb_mask: np.ndarray
    color_mask: np.ndarray
    structure_mask: np.ndarray
    edge_mask: np.ndarray
    combined_mask: np.ndarray
    thresholds: dict[str, float]


def parse_args() -> argparse.Namespace:
    def hierarchy_depth(value: str) -> int:
        depth = int(value)
        if depth < 1 or depth > 9:
            raise argparse.ArgumentTypeError("hierarchy-depth must be between 1 and 9")
        return depth

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
    parser.add_argument(
        "--hierarchy-depth",
        type=hierarchy_depth,
        default=None,
        help=(
            "Maximum public hierarchy depth to report, from 1 (page/edge) to "
            "9 (all raw/debug regions). Default preserves top-down compatibility."
        ),
    )
    parser.add_argument(
        "--report-mode",
        choices=tuple(REPORT_MODE_DEPTHS),
        default=None,
        help=(
            "Named hierarchy preset: structure=1, module=3, detail=5, raw=9. "
            "--hierarchy-depth overrides this preset when both are provided."
        ),
    )
    return parser.parse_args()


def load_rgb(path: Path) -> tuple[Image.Image, np.ndarray]:
    image = Image.open(path).convert("RGB")
    return image, np.asarray(image, dtype=np.float32)


def image_size_payload(size: tuple[int, int]) -> dict[str, int]:
    return {"width": size[0], "height": size[1]}


def resize_filter() -> int:
    try:
        return Image.Resampling.LANCZOS
    except AttributeError:
        return Image.LANCZOS


def padding_color(image: Image.Image) -> tuple[int, int, int]:
    width, height = image.size
    corners = [
        image.getpixel((0, 0)),
        image.getpixel((width - 1, 0)),
        image.getpixel((0, height - 1)),
        image.getpixel((width - 1, height - 1)),
    ]
    return tuple(int(round(sum(pixel[index] for pixel in corners) / len(corners))) for index in range(3))


def normalize_expected_to_actual(
    expected: Image.Image,
    actual_size: tuple[int, int],
) -> tuple[Image.Image, dict[str, object]]:
    expected_size = expected.size
    if expected_size == actual_size:
        return expected, {
            "mode": "none",
            "cropped": False,
            "padded": False,
            "scale": 1.0,
            "offset": {"x": 0, "y": 0},
            "original_expected_size": image_size_payload(expected_size),
            "scaled_expected_content_size": image_size_payload(expected_size),
            "normalized_expected_size": image_size_payload(actual_size),
            "comparison_size": image_size_payload(actual_size),
        }

    actual_width, actual_height = actual_size
    expected_width, expected_height = expected_size
    scale = min(actual_width / expected_width, actual_height / expected_height)
    scaled_width = max(1, round(expected_width * scale))
    scaled_height = max(1, round(expected_height * scale))
    offset_x = (actual_width - scaled_width) // 2
    offset_y = (actual_height - scaled_height) // 2

    resized = expected.resize((scaled_width, scaled_height), resize_filter())
    normalized = Image.new("RGB", actual_size, padding_color(expected))
    normalized.paste(resized, (offset_x, offset_y))
    return normalized, {
        "mode": "proportional-fit",
        "cropped": False,
        "padded": offset_x > 0 or offset_y > 0,
        "scale": round(scale, 6),
        "offset": {"x": offset_x, "y": offset_y},
        "original_expected_size": image_size_payload(expected_size),
        "scaled_expected_content_size": image_size_payload((scaled_width, scaled_height)),
        "normalized_expected_size": image_size_payload(actual_size),
        "comparison_size": image_size_payload(actual_size),
    }


def luminance(rgb: np.ndarray) -> np.ndarray:
    return (
        rgb[..., 0] * 0.2126
        + rgb[..., 1] * 0.7152
        + rgb[..., 2] * 0.0722
    ).astype(np.float32)


def box_mean(values: np.ndarray, radius: int) -> np.ndarray:
    if radius <= 0:
        return values.astype(np.float32)

    window = radius * 2 + 1
    padded = np.pad(values.astype(np.float64), radius, mode="reflect")
    integral = np.pad(padded, ((1, 0), (1, 0)), mode="constant").cumsum(axis=0).cumsum(axis=1)
    height, width = values.shape
    summed = (
        integral[window : window + height, window : window + width]
        - integral[:height, window : window + width]
        - integral[window : window + height, :width]
        + integral[:height, :width]
    )
    return (summed / float(window * window)).astype(np.float32)


def structural_dissimilarity(actual: np.ndarray, expected: np.ndarray) -> np.ndarray:
    actual_gray = luminance(actual)
    expected_gray = luminance(expected)
    radius = 3
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2

    actual_mean = box_mean(actual_gray, radius)
    expected_mean = box_mean(expected_gray, radius)
    actual_var = box_mean(actual_gray * actual_gray, radius) - actual_mean * actual_mean
    expected_var = box_mean(expected_gray * expected_gray, radius) - expected_mean * expected_mean
    covariance = box_mean(actual_gray * expected_gray, radius) - actual_mean * expected_mean

    numerator = (2 * actual_mean * expected_mean + c1) * (2 * covariance + c2)
    denominator = (actual_mean * actual_mean + expected_mean * expected_mean + c1) * (
        actual_var + expected_var + c2
    )
    similarity = numerator / np.maximum(denominator, 1e-6)
    return np.clip(1.0 - similarity, 0.0, 1.0).astype(np.float32)


def sobel_magnitude(values: np.ndarray) -> np.ndarray:
    padded = np.pad(values.astype(np.float32), 1, mode="reflect")
    left = padded[:-2, :-2] + 2 * padded[1:-1, :-2] + padded[2:, :-2]
    right = padded[:-2, 2:] + 2 * padded[1:-1, 2:] + padded[2:, 2:]
    top = padded[:-2, :-2] + 2 * padded[:-2, 1:-1] + padded[:-2, 2:]
    bottom = padded[2:, :-2] + 2 * padded[2:, 1:-1] + padded[2:, 2:]
    gx = right - left
    gy = bottom - top
    return np.sqrt(gx * gx + gy * gy).astype(np.float32)


def edge_delta(actual: np.ndarray, expected: np.ndarray) -> np.ndarray:
    return np.abs(sobel_magnitude(luminance(actual)) - sobel_magnitude(luminance(expected)))


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    srgb = np.clip(rgb / 255.0, 0.0, 1.0)
    linear = np.where(
        srgb > 0.04045,
        ((srgb + 0.055) / 1.055) ** 2.4,
        srgb / 12.92,
    )
    matrix = np.array(
        [
            [0.4124564, 0.3575761, 0.1804375],
            [0.2126729, 0.7151522, 0.0721750],
            [0.0193339, 0.1191920, 0.9503041],
        ],
        dtype=np.float32,
    )
    xyz = np.tensordot(linear, matrix.T, axes=1)
    xyz = xyz / np.array([0.95047, 1.0, 1.08883], dtype=np.float32)
    epsilon = 216 / 24389
    kappa = 24389 / 27
    f = np.where(xyz > epsilon, np.cbrt(xyz), (kappa * xyz + 16) / 116)
    lab = np.empty_like(xyz, dtype=np.float32)
    lab[..., 0] = 116 * f[..., 1] - 16
    lab[..., 1] = 500 * (f[..., 0] - f[..., 1])
    lab[..., 2] = 200 * (f[..., 1] - f[..., 2])
    return lab


def perceptual_color_delta(actual: np.ndarray, expected: np.ndarray) -> np.ndarray:
    return np.linalg.norm(rgb_to_lab(actual) - rgb_to_lab(expected), axis=2).astype(np.float32)


def expand_mask(mask: np.ndarray, radius: int) -> np.ndarray:
    if radius <= 0:
        return mask.copy()

    expanded = np.zeros_like(mask, dtype=bool)
    height, width = mask.shape
    padded = np.pad(mask, radius, mode="constant")
    diameter = radius * 2 + 1
    for dy in range(diameter):
        for dx in range(diameter):
            expanded |= padded[dy : dy + height, dx : dx + width]
    return expanded


def build_difference_signals(
    actual: np.ndarray,
    expected: np.ndarray,
    threshold: float,
) -> DiffSignals:
    rgb_delta = np.linalg.norm(actual - expected, axis=2).astype(np.float32)
    color_delta = perceptual_color_delta(actual, expected)
    structure_delta = structural_dissimilarity(actual, expected)
    edges = edge_delta(actual, expected)

    color_threshold = max(2.0, threshold * 0.16)
    structure_threshold = max(0.045, min(0.12, threshold / 255.0))
    edge_threshold = max(18.0, threshold * 1.5)

    rgb_mask = rgb_delta >= threshold
    color_mask = color_delta >= color_threshold
    soft_mask = (rgb_delta >= threshold * 0.5) | (color_delta >= color_threshold * 0.75)
    coherent_support = expand_mask(denoise_mask(soft_mask), 1)
    structure_mask = (structure_delta >= structure_threshold) & coherent_support
    edge_mask = (edges >= edge_threshold) & coherent_support
    combined_mask = denoise_mask(rgb_mask | color_mask | structure_mask | edge_mask)

    return DiffSignals(
        rgb_delta=rgb_delta,
        color_delta=color_delta,
        structure_delta=structure_delta,
        edge_delta=edges,
        rgb_mask=rgb_mask,
        color_mask=color_mask,
        structure_mask=structure_mask,
        edge_mask=edge_mask,
        combined_mask=combined_mask,
        thresholds={
            "rgb": round(threshold, 4),
            "color_delta_e": round(color_threshold, 4),
            "structure_dissimilarity": round(structure_threshold, 4),
            "edge_delta": round(edge_threshold, 4),
        },
    )


def build_difference_mask(
    actual: np.ndarray,
    expected: np.ndarray,
    threshold: float,
) -> tuple[np.ndarray, np.ndarray]:
    signals = build_difference_signals(actual, expected, threshold)
    return signals.combined_mask, signals.rgb_delta


def draw_scaled_graymap(values: np.ndarray, upper: float) -> Image.Image:
    normalized = (np.clip(values, 0, upper) / upper * 255).astype(np.uint8)
    return Image.fromarray(normalized)


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


def connected_components(mask: np.ndarray, min_area: int) -> list[Component]:
    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    components: list[Component] = []

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
    components: list[Component],
    merge_gap: int,
) -> list[Component]:
    merged: list[Component] = []

    for component in components:
        cx1, cy1, cx2, cy2, area, pixels = component
        current_box = (cx1, cy1, cx2, cy2)
        current_pixels = pixels[:]
        current_area = area

        changed = True
        while changed:
            changed = False
            next_merged: list[Component] = []
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


def dedupe_components(
    components: Iterable[Component],
) -> list[Component]:
    deduped: dict[tuple[int, int, int, int], Component] = {}
    for component in components:
        x1, y1, x2, y2, area, _ = component
        key = (x1, y1, x2, y2)
        if key not in deduped or area > deduped[key][4]:
            deduped[key] = component
    return list(deduped.values())


def component_bbox_area(component: Component) -> int:
    x1, y1, x2, y2, _, _ = component
    return max(0, x2 - x1) * max(0, y2 - y1)


def component_overlap_ratio(a: Component, b: Component) -> float:
    ax1, ay1, ax2, ay2, _, _ = a
    bx1, by1, bx2, by2, _, _ = b
    overlap = max(0, min(ax2, bx2) - max(ax1, bx1)) * max(0, min(ay2, by2) - max(ay1, by1))
    return overlap / max(1, min(component_bbox_area(a), component_bbox_area(b)))


def is_object_detail_component(
    component: Component,
    image_size: tuple[int, int],
    min_area: int,
) -> bool:
    image_width, image_height = image_size
    image_area = image_width * image_height
    x1, y1, x2, y2, area, _ = component
    width = x2 - x1
    height = y2 - y1
    if width < 4 or height < 4 or area < max(min_area, 12):
        return False

    bbox_area = max(1, width * height)
    bbox_ratio = bbox_area / max(1, image_area)
    width_ratio = width / max(1, image_width)
    height_ratio = height / max(1, image_height)
    fill_ratio = area / bbox_area
    aspect = width / max(1, height)
    min_dimension = max(1, min(image_width, image_height))
    max_allowed_dimension = max(128, round(min_dimension * 0.28))

    if bbox_ratio > 0.08 or width_ratio > 0.34 or height_ratio > 0.32:
        return False
    if max(width, height) > max_allowed_dimension:
        return False
    if aspect > 5.5 or aspect < 0.18:
        return False
    if fill_ratio < 0.035:
        return False
    if width <= 3 or height <= 3:
        return False
    return True


def dedupe_detail_components(components: Iterable[Component]) -> list[Component]:
    ordered = sorted(
        dedupe_components(components),
        key=lambda component: (component[4], component_bbox_area(component)),
        reverse=True,
    )
    selected: list[Component] = []
    for component in ordered:
        if any(component_overlap_ratio(component, existing) >= 0.84 for existing in selected):
            continue
        selected.append(component)
    return selected


def detail_proposal_components(
    signals: DiffSignals,
    min_area: int,
    image_size: tuple[int, int],
) -> list[Component]:
    """Split object-like detail candidates out of broad color/layout regions."""
    rgb_threshold = max(signals.thresholds["rgb"] * 3.0, 36.0)
    color_threshold = max(signals.thresholds["color_delta_e"] * 3.0, 8.0)
    structure_threshold = max(signals.thresholds["structure_dissimilarity"] * 2.5, 0.12)
    edge_threshold = max(signals.thresholds["edge_delta"] * 2.75, 50.0)

    strong_rgb = signals.rgb_delta >= rgb_threshold
    strong_color = signals.color_delta >= color_threshold
    strong_structure = signals.structure_mask & (signals.structure_delta >= structure_threshold)
    strong_edge = signals.edge_delta >= edge_threshold

    masks = [
        denoise_mask(signals.edge_mask),
        denoise_mask(signals.edge_mask & strong_edge),
        denoise_mask(strong_rgb | strong_color),
        denoise_mask(strong_structure),
        denoise_mask(strong_rgb | strong_color | (signals.edge_mask & strong_edge) | strong_structure),
    ]

    detail_components: list[Component] = []
    detail_min_area = max(8, min_area)
    for detail_mask in masks:
        components = connected_components(detail_mask, detail_min_area)
        detail_components.extend(
            component
            for component in components
            if is_object_detail_component(component, image_size, detail_min_area)
        )

    return dedupe_detail_components(detail_components)


def category_hint(width: int, height: int, area: int, mean_delta: float) -> str:
    aspect = width / max(height, 1)
    fill_ratio = area / max(width * height, 1)

    if height <= 3 and width >= 12:
        return "border/divider position or color"
    if width <= 3 and height >= 12:
        return "border/divider position or alignment"
    if fill_ratio < 0.18 and (aspect > 4 or aspect < 0.25):
        return "typography/icon edge or alignment"
    if width <= 96 and height <= 96 and area <= 6000:
        return "typography/icon/image detail"
    if area >= 400 and mean_delta < 28:
        return "background color/shadow/gradient"
    if area >= 400:
        return "module layout/size/visual state"
    if width <= 24 and height <= 24:
        return "typography/icon/image detail"
    return "ui visual difference"


def signal_metrics_for_pixels(
    pixels: list[tuple[int, int]],
    signals: DiffSignals,
) -> tuple[dict[str, int], dict[str, float], str]:
    if not pixels:
        return {}, {}, "rgb"

    xs = np.array([x for x, _ in pixels], dtype=np.intp)
    ys = np.array([y for _, y in pixels], dtype=np.intp)
    masks = {
        "rgb": signals.rgb_mask,
        "color": signals.color_mask,
        "structure": signals.structure_mask,
        "edge": signals.edge_mask,
    }
    values = {
        "rgb": signals.rgb_delta,
        "color_delta_e": signals.color_delta,
        "structure_dissimilarity": signals.structure_delta,
        "edge": signals.edge_delta,
    }
    counts = {name: int(mask[ys, xs].sum()) for name, mask in masks.items()}
    strengths = {
        name: round(float(value[ys, xs].mean()), 4)
        for name, value in values.items()
    }
    strength_keys = {
        "rgb": "rgb",
        "color": "color_delta_e",
        "structure": "structure_dissimilarity",
        "edge": "edge",
    }
    dominant = max(
        counts,
        key=lambda name: (counts[name], strengths[strength_keys[name]]),
    )
    return counts, strengths, dominant


def infer_element_kind(region: Region, image_size: tuple[int, int]) -> str:
    image_width, image_height = image_size
    image_area = image_width * image_height
    bbox_ratio = region.bbox_area / max(1, image_area)
    fill_ratio = region.area / max(1, region.bbox_area)
    aspect = region.width / max(1, region.height)
    hint = region.category_hint.lower()
    edge = touches_screen_edge(region, image_size)
    color_count = region.signal_counts.get("color", 0)
    structure_count = region.signal_counts.get("structure", 0)
    edge_count = region.signal_counts.get("edge", 0)
    rgb_count = region.signal_counts.get("rgb", 0)
    object_detail_max_dimension = max(128, round(min(image_width, image_height) * 0.28))

    if edge and (
        region.width / max(1, image_width) >= 0.24
        or region.height / max(1, image_height) >= 0.16
    ):
        return "screen-edge/safe-area"
    if (
        color_count >= max(structure_count + edge_count, rgb_count // 2)
        and structure_count <= color_count * 0.35
        and edge_count <= color_count * 0.35
        and region.area >= 240
    ):
        return "background/color fill"
    if (
        fill_ratio >= 0.70
        and color_count > structure_count
        and color_count > edge_count
        and region.area >= 240
    ):
        return "background/color fill"
    if "typography/icon" in hint and max(region.width, region.height) <= max(
        96,
        round(min(image_width, image_height) * 0.24),
    ):
        return "icon/image detail"
    if (
        bbox_ratio < 0.08
        and max(region.width, region.height) <= object_detail_max_dimension
        and 0.18 <= aspect <= 5.5
        and fill_ratio >= 0.035
        and (edge_count > 0 or structure_count > 0)
        and not is_thin_horizontal(region)
        and not is_thin_vertical(region)
    ):
        return "icon/image detail"
    if is_thin_horizontal(region) or is_thin_vertical(region):
        return "border/divider"
    if bbox_ratio >= 0.035 or "layout" in hint:
        return "module/container"
    if "typography" in hint and fill_ratio < 0.35:
        return "typography/text metrics"
    if region.width <= 96 and region.height <= 96 and (edge_count or structure_count or "icon" in hint):
        return "icon/image detail"
    if fill_ratio < 0.22:
        return "typography/icon stroke"
    return "ui visual region"


def priority_category_for_region(region: Region, image_size: tuple[int, int]) -> tuple[str, int]:
    image_width, image_height = image_size
    bbox_ratio = region.bbox_area / max(1, image_width * image_height)
    fill_ratio = region.area / max(1, region.bbox_area)
    hint = region.category_hint.lower()
    color_count = region.signal_counts.get("color", 0)
    structure_count = region.signal_counts.get("structure", 0)
    edge_count = region.signal_counts.get("edge", 0)
    non_color_count = structure_count + edge_count
    color_only = color_count > 0 and non_color_count <= max(2, color_count * 0.20)

    if color_only and region.element_kind in {"screen-edge/safe-area", "background/color fill", "module/container"}:
        return "background color", 7
    if region.element_kind == "icon/image detail":
        return "image / icon consistency", 4
    if region.element_kind in {"typography/text metrics", "typography/icon stroke"}:
        return "font metrics / typography", 5
    if "module layout/spacing group" in hint:
        return "relative relationship / spacing", 3
    if "layout" in hint or region.element_kind == "module/container":
        if bbox_ratio >= 0.035 and non_color_count >= color_count * 0.25:
            return "size / layout dimensions", 1
        return "position / alignment", 2
    if touches_screen_edge(region, image_size) and not color_only:
        return "position / alignment", 2
    if region.element_kind == "screen-edge/safe-area":
        return "background color", 7
    if "border" in hint or "divider" in hint:
        return "position / alignment", 2
    if color_only and region.element_kind != "background/color fill" and fill_ratio < 0.45:
        return "foreground color", 6
    if "gradient" in hint:
        return "gradient", 8
    if "shadow" in hint:
        return "shadow / effect", 9
    if region.element_kind == "background/color fill" or color_only:
        return "background color", 7
    if non_color_count > color_count:
        return "position / alignment", 2
    return "shadow / effect", 9


def score_region_importance(region: Region, image_size: tuple[int, int], base_priority: float) -> None:
    image_width, image_height = image_size
    image_area = image_width * image_height
    bbox_ratio = region.bbox_area / max(1, image_area)
    changed_ratio = region.area / max(1, image_area)
    density = region.area / max(1, region.bbox_area)
    signal_count = sum(1 for value in region.signal_counts.values() if value > 0)
    structure_strength = region.signal_strengths.get("structure_dissimilarity", 0.0)
    color_strength = region.signal_strengths.get("color_delta_e", 0.0)
    edge_strength = region.signal_strengths.get("edge", 0.0)
    edge = touches_screen_edge(region, image_size)
    priority_category, priority_tier = priority_category_for_region(region, image_size)

    kind_weights = {
        "screen-edge/safe-area": 0.72,
        "module/container": 1.22,
        "typography/text metrics": 1.08,
        "icon/image detail": 1.14,
        "border/divider": 1.12,
        "typography/icon stroke": 1.04,
        "background/color fill": 0.54,
        "ui visual region": 1.0,
    }
    tier_weights = {
        1: 1.40,
        2: 1.28,
        3: 1.20,
        4: 1.12,
        5: 1.04,
        6: 0.78,
        7: 0.52,
        8: 0.42,
        9: 0.34,
    }
    kind_weight = kind_weights.get(region.element_kind, 1.0)
    first_screen_weight = 1.12 if region.y < image_height * 0.42 else 1.0
    multi_signal_weight = 1.0 + min(0.18, max(0, signal_count - 1) * 0.06)
    edge_weight = 1.10 if edge and priority_tier <= 3 else 1.0

    visual_strength = min(1.0, region.mean_delta / 80.0)
    color_strength_norm = min(1.0, color_strength / 20.0)
    structure_strength_norm = min(1.0, structure_strength / 0.24)
    edge_strength_norm = min(1.0, edge_strength / 140.0)
    geometry_strength = max(structure_strength_norm, edge_strength_norm)
    style_strength = max(visual_strength, color_strength_norm)
    coverage_score = min(1.0, bbox_ratio / 0.10) * 0.24 + min(1.0, changed_ratio / 0.025) * 0.20
    if priority_tier <= 5:
        detail_score = max(geometry_strength, style_strength * 0.45) * 0.40
    else:
        detail_score = max(style_strength * 0.35, geometry_strength * 0.18) * 0.28
    density_score = min(1.0, density / 0.65) * 0.08

    severity = (
        coverage_score
        + detail_score
        + density_score
    ) * kind_weight * tier_weights[priority_tier] * first_screen_weight * multi_signal_weight * edge_weight
    severity = max(1.0, min(100.0, severity * 100.0))

    factors: list[str] = []
    factors.append(f"priority tier {priority_tier}: {priority_category}")
    if edge and priority_tier <= 3:
        factors.append("screen-edge proximity")
    if signal_count >= 2:
        factors.append(f"{signal_count} diff signal channels")
    if bbox_ratio >= 0.035:
        factors.append("module-scale coverage")
    if density >= 0.55:
        factors.append("dense changed pixels")
    if structure_strength_norm >= 0.35:
        factors.append("structural shape change")
    if color_strength_norm >= 0.35:
        factors.append("perceptual color shift")
    if edge_strength_norm >= 0.35:
        factors.append("edge/stroke movement")
    if region.y < image_height * 0.42:
        factors.append("first-screen placement")

    confidence = 0.42 + min(0.24, density * 0.26) + min(0.18, signal_count * 0.06)
    if region.area >= 48:
        confidence += 0.08
    if bbox_ratio >= 0.008:
        confidence += 0.06
    if region.dominant_signal == "structure" and signal_count == 1:
        confidence -= 0.10
    confidence = max(0.1, min(0.99, confidence))

    region.severity_score = round(severity, 2)
    region.confidence_score = round(confidence, 3)
    region.confidence_level = "high" if confidence >= 0.72 else "medium" if confidence >= 0.5 else "low"
    region.severity_factors = factors
    region.priority_category = priority_category
    region.priority_tier = priority_tier
    tier_rank = (10 - priority_tier) * 1_000_000.0
    region.priority = round(tier_rank + region.severity_score * 1000.0 + base_priority * 0.02, 2)


def make_regions(
    components: Iterable[Component],
    signals: DiffSignals,
    max_regions: int,
) -> list[Region]:
    scored = []
    for x1, y1, x2, y2, area, pixels in components:
        pixel_deltas = np.array([signals.rgb_delta[y, x] for x, y in pixels], dtype=np.float32)
        mean_delta = float(pixel_deltas.mean()) if len(pixel_deltas) else 0.0
        max_delta = float(pixel_deltas.max()) if len(pixel_deltas) else 0.0
        signal_counts, signal_strengths, dominant_signal = signal_metrics_for_pixels(pixels, signals)
        signal_bonus = 1.0 + min(0.35, sum(1 for value in signal_counts.values() if value > 0) * 0.08)
        structure_bonus = 1.0 + min(0.30, signal_strengths.get("structure_dissimilarity", 0.0) * 1.6)
        edge_bonus = 1.0 + min(0.25, signal_strengths.get("edge", 0.0) / 180.0)
        score = area * math.log(max(mean_delta, 1.0) + 1) * signal_bonus * structure_bonus * edge_bonus
        scored.append(
            (
                score,
                x1,
                y1,
                x2,
                y2,
                area,
                mean_delta,
                max_delta,
                signal_counts,
                signal_strengths,
                dominant_signal,
            )
        )

    scored.sort(reverse=True)
    selected = scored[:max_regions]
    selected.sort(key=lambda item: (item[2], item[1]))

    regions: list[Region] = []
    for idx, (_, x1, y1, x2, y2, area, mean_delta, max_delta, signal_counts, signal_strengths, dominant_signal) in enumerate(selected, start=1):
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
                source_region_ids=(idx,),
                dominant_signal=dominant_signal,
                signal_counts=signal_counts,
                signal_strengths=signal_strengths,
            )
        )

    return regions


def touches_screen_edge(region: Region, image_size: tuple[int, int]) -> bool:
    image_width, image_height = image_size
    edge_margin = max(2, round(min(image_width, image_height) * 0.015))
    return (
        region.x <= edge_margin
        or region.y <= edge_margin
        or image_width - region.right <= edge_margin
        or image_height - region.bottom <= edge_margin
    )


def overlap_amount(a1: int, a2: int, b1: int, b2: int) -> int:
    return max(0, min(a2, b2) - max(a1, b1))


def overlap_ratio(a: Region, b: Region, axis: str) -> float:
    if axis == "x":
        overlap = overlap_amount(a.x, a.right, b.x, b.right)
        return overlap / max(1, min(a.width, b.width))
    if axis == "y":
        overlap = overlap_amount(a.y, a.bottom, b.y, b.bottom)
        return overlap / max(1, min(a.height, b.height))
    raise ValueError(f"unknown axis: {axis}")


def contains_region(parent: Region, child: Region, padding: int = 0) -> bool:
    return (
        parent.x - padding <= child.x
        and parent.y - padding <= child.y
        and parent.right + padding >= child.right
        and parent.bottom + padding >= child.bottom
    )


def is_thin_vertical(region: Region) -> bool:
    return region.height >= 12 and region.width <= max(4, round(region.height * 0.25))


def is_thin_horizontal(region: Region) -> bool:
    return region.width >= 12 and region.height <= max(4, round(region.width * 0.25))


def classify_hierarchy_level(region: Region, image_size: tuple[int, int]) -> tuple[int, float, str]:
    image_width, image_height = image_size
    image_area = image_width * image_height
    bbox_ratio = region.bbox_area / max(1, image_area)
    width_ratio = region.width / max(1, image_width)
    height_ratio = region.height / max(1, image_height)
    edge = touches_screen_edge(region, image_size)
    hint = region.category_hint

    if edge and (width_ratio >= 0.24 or height_ratio >= 0.16 or bbox_ratio >= 0.015):
        level = 0
        hint = "edge/safe-area layout or background"
    elif bbox_ratio >= 0.12 or width_ratio >= 0.72 or height_ratio >= 0.55:
        level = 0
    elif bbox_ratio >= 0.035 or width_ratio >= 0.34 or height_ratio >= 0.22:
        level = 1
    elif bbox_ratio >= 0.008 or width_ratio >= 0.14 or height_ratio >= 0.10:
        level = 2
    else:
        level = 3

    priority = (
        region.bbox_area * 0.35
        + region.area * 1.8
        + region.mean_delta * 4.0
        + width_ratio * 200.0
        + height_ratio * 200.0
    )
    if edge:
        priority += 1200.0
    if "background" in hint or "layout" in hint or "safe-area" in hint:
        priority += 400.0
    if "typography/icon/image detail" in hint and level < 3 and bbox_ratio < 0.025:
        level = 3

    return level, round(priority, 2), hint


def display_depth_for_region(region: Region, image_size: tuple[int, int]) -> int:
    image_width, image_height = image_size
    min_dimension = max(1, min(image_width, image_height))
    max_dimension = max(region.width, region.height)
    bbox_ratio = region.bbox_area / max(1, image_width * image_height)
    hint = region.category_hint.lower()
    edge = touches_screen_edge(region, image_size)

    if region.priority_tier >= 6:
        return min(9, region.priority_tier)
    if region.priority_tier == 1:
        return 2 if region.level <= 1 else 3
    if region.priority_tier in {2, 3}:
        return 3
    if region.priority_tier in {4, 5}:
        return 5
    if region.level == 0 or (edge and bbox_ratio >= 0.01):
        return 1
    if region.level == 1:
        return 2
    if "border" in hint or "divider" in hint or "shadow" in hint:
        return 7
    if "typography/icon edge" in hint:
        return 5
    if "typography/icon/image detail" in hint:
        return 5
    if "background" in hint or "gradient" in hint:
        return 7 if region.level >= 2 else 2
    if region.level == 2:
        return 3
    if max_dimension <= max(24, round(min_dimension * 0.06)):
        return 5
    if max_dimension <= max(48, round(min_dimension * 0.10)):
        return 6
    if max_dimension <= max(72, round(min_dimension * 0.14)):
        return 8
    return 9


def should_link_for_group(a: Region, b: Region, image_size: tuple[int, int]) -> bool:
    image_width, image_height = image_size
    max_gap_x = max(12, round(image_width * 0.35))
    max_gap_y = max(12, round(image_height * 0.18))

    if min(a.priority_tier, b.priority_tier) <= 5 and max(a.priority_tier, b.priority_tier) >= 6:
        return False

    same_y_band = overlap_ratio(a, b, "y") >= 0.72
    same_x_band = overlap_ratio(a, b, "x") >= 0.72
    horizontal_gap = max(0, max(a.x, b.x) - min(a.right, b.right))
    vertical_gap = max(0, max(a.y, b.y) - min(a.bottom, b.bottom))

    if same_y_band and horizontal_gap <= max_gap_x:
        return is_thin_vertical(a) or is_thin_vertical(b) or a.height >= 18 or b.height >= 18
    if same_x_band and vertical_gap <= max_gap_y:
        return is_thin_horizontal(a) or is_thin_horizontal(b) or a.width >= 18 or b.width >= 18
    return False


def grouped_regions(raw_regions: list[Region], image_size: tuple[int, int]) -> list[Region]:
    if len(raw_regions) < 2:
        return []

    parent = list(range(len(raw_regions)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for i, first in enumerate(raw_regions):
        for j in range(i + 1, len(raw_regions)):
            if should_link_for_group(first, raw_regions[j], image_size):
                union(i, j)

    groups: dict[int, list[Region]] = {}
    for index, region in enumerate(raw_regions):
        groups.setdefault(find(index), []).append(region)

    synthetic: list[Region] = []
    next_id = len(raw_regions) + 1
    image_area = image_size[0] * image_size[1]

    for source_regions in groups.values():
        if len(source_regions) < 2:
            continue

        x1 = min(region.x for region in source_regions)
        y1 = min(region.y for region in source_regions)
        x2 = max(region.right for region in source_regions)
        y2 = max(region.bottom for region in source_regions)
        width = x2 - x1
        height = y2 - y1
        bbox_area = width * height
        if bbox_area / max(1, image_area) < 0.012:
            continue

        area = sum(region.area for region in source_regions)
        mean_delta = round(
            sum(region.mean_delta * region.area for region in source_regions) / max(area, 1),
            2,
        )
        max_delta = max(region.max_delta for region in source_regions)
        signal_counts = {
            name: sum(region.signal_counts.get(name, 0) for region in source_regions)
            for name in ("rgb", "color", "structure", "edge")
        }
        signal_strengths = {}
        for name in ("rgb", "color_delta_e", "structure_dissimilarity", "edge"):
            signal_strengths[name] = round(
                sum(region.signal_strengths.get(name, 0.0) * region.area for region in source_regions)
                / max(area, 1),
                4,
            )
        dominant_signal = max(signal_counts, key=lambda name: signal_counts[name])
        source_ids = tuple(region.region_id for region in source_regions)
        candidate = Region(
            region_id=next_id,
            x=x1,
            y=y1,
            width=width,
            height=height,
            area=area,
            mean_delta=mean_delta,
            max_delta=max_delta,
            category_hint="module layout/spacing group",
            report_group=f"group-{next_id}",
            source_region_ids=source_ids,
            dominant_signal=dominant_signal,
            signal_counts=signal_counts,
            signal_strengths=signal_strengths,
        )
        candidate.level, candidate.priority, candidate.category_hint = classify_hierarchy_level(
            candidate,
            image_size,
        )
        candidate.element_kind = infer_element_kind(candidate, image_size)
        score_region_importance(candidate, image_size, candidate.priority)
        candidate.display_depth = display_depth_for_region(candidate, image_size)
        if candidate.level <= 2:
            synthetic.append(candidate)
            next_id += 1

    return synthetic


def is_parent_level(region: Region) -> bool:
    hint = region.category_hint.lower()
    return (
        region.level <= 1
        or "layout" in hint
        or "spacing" in hint
        or "background" in hint
        or "safe-area" in hint
        or "gradient" in hint
    )


def reset_reporting(regions: Iterable[Region]) -> None:
    for region in regions:
        region.parent_id = None
        region.suppressed_by = None
        region.report_id = None


def assign_parent_links(
    raw_regions: list[Region],
    parent_candidates: list[Region],
) -> None:
    for region in raw_regions:
        for parent in parent_candidates:
            if parent.region_id == region.region_id:
                continue
            if parent.level >= region.level:
                continue
            if parent.priority_tier > region.priority_tier:
                continue
            if not contains_region(parent, region, padding=4):
                continue
            if is_parent_level(parent):
                region.parent_id = parent.region_id
                region.report_group = parent.report_group or f"region-{parent.region_id}"
                break


def apply_hierarchy(
    raw_regions: list[Region],
    image_size: tuple[int, int],
    hierarchy_depth: int | None = None,
) -> tuple[list[Region], list[Region], list[Region]]:
    reset_reporting(raw_regions)
    for region in raw_regions:
        region.level, region.priority, region.category_hint = classify_hierarchy_level(
            region,
            image_size,
        )
        region.element_kind = infer_element_kind(region, image_size)
        score_region_importance(region, image_size, region.priority)
        region.display_depth = display_depth_for_region(region, image_size)
        region.report_group = f"region-{region.region_id}"

    synthetic_groups = grouped_regions(raw_regions, image_size)
    parent_candidates = sorted(
        [*synthetic_groups, *[region for region in raw_regions if is_parent_level(region)]],
        key=lambda region: (region.priority_tier, region.level, -region.priority, region.y, region.x),
    )

    if hierarchy_depth is not None:
        reset_reporting([*raw_regions, *synthetic_groups])
        assign_parent_links(raw_regions, parent_candidates)
        candidates = [*synthetic_groups, *raw_regions]
        reported = [
            region
            for region in candidates
            if region.display_depth <= hierarchy_depth
        ]
        reported.sort(
            key=lambda region: (
                region.priority_tier,
                region.display_depth,
                region.level,
                -region.priority,
                region.y,
                region.x,
            )
        )
        for report_id, region in enumerate(reported, start=1):
            region.report_id = report_id
        return raw_regions, reported, []

    reported: list[Region] = []
    for group in synthetic_groups:
        reported.append(group)
        for region in raw_regions:
            if region.region_id in group.source_region_ids:
                region.parent_id = group.region_id
                region.suppressed_by = group.region_id
                region.report_group = group.report_group

    for region in raw_regions:
        if region.suppressed_by is not None:
            continue

        for parent in parent_candidates:
            if parent.region_id == region.region_id:
                continue
            if parent.level >= region.level:
                continue
            if parent.priority_tier > region.priority_tier:
                continue
            if not contains_region(parent, region, padding=4):
                continue
            if is_parent_level(parent):
                region.parent_id = parent.region_id
                region.suppressed_by = parent.region_id
                region.report_group = parent.report_group or f"region-{parent.region_id}"
                break

        if region.suppressed_by is None:
            reported.append(region)

    reported.sort(key=lambda region: (region.priority_tier, region.level, -region.priority, region.y, region.x))
    for report_id, region in enumerate(reported, start=1):
        region.report_id = report_id

    suppressed = [region for region in raw_regions if region.suppressed_by is not None]
    suppressed.sort(key=lambda region: (region.suppressed_by or 0, region.y, region.x))

    return raw_regions, reported, suppressed


def edge_evidence(region: Region, image_size: tuple[int, int]) -> dict[str, object]:
    image_width, image_height = image_size
    margins = {
        "left": region.x,
        "top": region.y,
        "right": image_width - region.right,
        "bottom": image_height - region.bottom,
    }
    edge_threshold = max(2, round(min(image_width, image_height) * 0.02))
    touches = [edge for edge, margin in margins.items() if margin <= edge_threshold]
    return {
        "margins": margins,
        "touches": touches,
        "edge_threshold": edge_threshold,
    }


def region_finding_text(
    region: Region,
    image_size: tuple[int, int],
    child_count: int,
) -> tuple[str, list[str]]:
    image_width, image_height = image_size
    width_ratio = region.width / max(1, image_width)
    height_ratio = region.height / max(1, image_height)
    evidence = edge_evidence(region, image_size)
    touches = evidence["touches"]

    reasons: list[str] = []
    if region.level == 0:
        reasons.append("high-level page/module finding")
    elif region.level == 1:
        reasons.append("top-level module finding")
    elif region.level == 2:
        reasons.append("nested module finding")
    else:
        reasons.append("detail-level finding")

    reasons.append(f"priority tier {region.priority_tier}: {region.priority_category}")
    reasons.append(f"{region.element_kind} candidate")
    reasons.append(f"dominant signal: {region.dominant_signal}")
    reasons.append(f"severity {region.severity_score:.1f}/100, {region.confidence_level} confidence")
    if width_ratio >= 0.70 or height_ratio >= 0.55:
        reasons.append(
            f"large coverage ({region.width}x{region.height}, "
            f"{width_ratio:.0%} width, {height_ratio:.0%} height)"
        )
    if touches:
        margin_text = ", ".join(
            f"{edge}={evidence['margins'][edge]}px" for edge in touches
        )
        reasons.append(f"touches screen edge ({margin_text})")
    if child_count:
        reasons.append(f"explains {child_count} suppressed child diff region(s)")
    if region.source_region_ids and len(region.source_region_ids) > 1:
        reasons.append(f"groups raw regions {list(region.source_region_ids)}")
    if region.severity_factors:
        reasons.append("importance factors: " + ", ".join(region.severity_factors))

    guidance = [
        "Treat this reported region as the primary UI/UX finding, not as a false positive.",
        "Compare the actual screenshot against the design at this parent/module level before inspecting child details.",
        "Use the region crop pair and diff-channel evidence to verify the exact visual property before reporting.",
    ]
    if touches:
        guidance.append(
            "Check screen-edge spacing, safe-area handling, and clipping around the touched edge(s)."
        )
    if child_count:
        guidance.append(
            "Do not expand suppressed child regions unless an independent child-level issue remains after the parent layout issue is addressed."
        )

    summary = f"{region.category_hint}: " + "; ".join(reasons) + "."
    return summary, guidance


def draw_annotations(actual: Image.Image, regions: list[Region]) -> Image.Image:
    annotated = actual.copy().convert("RGB")
    draw = ImageDraw.Draw(annotated)
    font = ImageFont.load_default()

    for region in regions:
        x1 = region.x
        y1 = region.y
        x2 = region.x + region.width
        y2 = region.y + region.height
        label = str(region.report_id or region.region_id)

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


def evidence_mask_for_regions(mask: np.ndarray, regions: list[Region]) -> np.ndarray:
    evidence = np.zeros_like(mask, dtype=bool)
    for region in regions:
        evidence[region.y : region.bottom, region.x : region.right] |= mask[
            region.y : region.bottom,
            region.x : region.right,
        ]
    return evidence


def draw_evidence_overlay(base: Image.Image, evidence_mask: np.ndarray, regions: list[Region]) -> Image.Image:
    base_array = np.asarray(base.convert("RGB"), dtype=np.float32).copy()
    highlight = np.array([255.0, 214.0, 0.0], dtype=np.float32)
    alpha = 0.48
    base_array[evidence_mask] = base_array[evidence_mask] * (1.0 - alpha) + highlight * alpha
    overlay = Image.fromarray(np.clip(base_array, 0, 255).astype(np.uint8))
    return draw_annotations(overlay, regions)


def draw_heatmap(delta: np.ndarray) -> Image.Image:
    clipped = np.clip(delta, 0, 96)
    normalized = (clipped / 96.0 * 255).astype(np.uint8)
    heatmap = np.zeros((delta.shape[0], delta.shape[1], 3), dtype=np.uint8)
    heatmap[..., 0] = normalized
    heatmap[..., 1] = (normalized * 0.18).astype(np.uint8)
    heatmap[..., 2] = 255 - normalized
    return Image.fromarray(heatmap)


def draw_graymap(delta: np.ndarray) -> Image.Image:
    clipped = np.clip(delta, 0, 96)
    normalized = (clipped / 96.0 * 255).astype(np.uint8)
    return Image.fromarray(normalized)


def padded_bbox(region: Region, image_size: tuple[int, int], padding: int = 12) -> tuple[int, int, int, int]:
    image_width, image_height = image_size
    return (
        max(0, region.x - padding),
        max(0, region.y - padding),
        min(image_width, region.right + padding),
        min(image_height, region.bottom + padding),
    )


def crop_mask(mask: np.ndarray, bbox: tuple[int, int, int, int]) -> np.ndarray:
    x1, y1, x2, y2 = bbox
    return mask[y1:y2, x1:x2]


def save_region_crops(
    out_dir: Path,
    actual_image: Image.Image,
    expected_image: Image.Image,
    signals: DiffSignals,
    evidence_mask: np.ndarray,
    regions: list[Region],
) -> dict[int, dict[str, object]]:
    crop_dir = out_dir / "region_crops"
    crop_dir.mkdir(parents=True, exist_ok=True)
    crop_paths: dict[int, dict[str, object]] = {}

    for region in regions:
        label = f"{region.report_id or region.region_id:02d}"
        bbox = padded_bbox(region, actual_image.size)
        x1, y1, x2, y2 = bbox
        actual_crop = actual_image.crop(bbox)
        expected_crop = expected_image.crop(bbox)
        rgb_crop = signals.rgb_delta[y1:y2, x1:x2]
        evidence_crop_mask = crop_mask(evidence_mask, bbox)

        actual_path = crop_dir / f"{label}_actual.png"
        expected_path = crop_dir / f"{label}_expected.png"
        diff_path = crop_dir / f"{label}_diff_heatmap.png"
        evidence_path = crop_dir / f"{label}_evidence_overlay.png"

        actual_crop.save(actual_path)
        expected_crop.save(expected_path)
        draw_heatmap(rgb_crop).save(diff_path)
        draw_evidence_overlay(actual_crop, evidence_crop_mask, []).save(evidence_path)
        crop_paths[region.region_id] = {
            "actual": str(actual_path),
            "expected": str(expected_path),
            "diff_heatmap": str(diff_path),
            "evidence_overlay": str(evidence_path),
            "bbox": {
                "x": x1,
                "y": y1,
                "width": x2 - x1,
                "height": y2 - y1,
            },
        }

    return crop_paths


def diff_pixel_evidence(region: Region, mask: np.ndarray) -> tuple[int, dict[str, int] | None]:
    region_mask = mask[region.y : region.bottom, region.x : region.right]
    ys, xs = np.nonzero(region_mask)
    if len(xs) == 0:
        return 0, None

    x1 = int(region.x + xs.min())
    y1 = int(region.y + ys.min())
    x2 = int(region.x + xs.max() + 1)
    y2 = int(region.y + ys.max() + 1)
    return int(len(xs)), {
        "x": x1,
        "y": y1,
        "width": x2 - x1,
        "height": y2 - y1,
    }


def hierarchy_policy_text(
    hierarchy_depth: int | None,
    report_mode: str | None,
    effective_depth: int | None,
) -> str:
    if effective_depth is None:
        return (
            "Report page, edge, and parent-module differences before child elements. "
            "Suppress child regions when a parent layout/spacing/background/edge issue explains them."
        )
    source = f"report-mode {report_mode!r}" if hierarchy_depth is None and report_mode else "hierarchy-depth"
    return (
        f"Report regions up to hierarchy-depth {effective_depth} from {source} in top-down order. "
        "Parent regions stay visible for context but do not hide eligible child detail regions."
    )


def effective_hierarchy_depth(
    hierarchy_depth: int | None,
    report_mode: str | None,
) -> int | None:
    if hierarchy_depth is not None:
        return hierarchy_depth
    if report_mode is not None:
        return REPORT_MODE_DEPTHS[report_mode]
    return None


def focus_regions_for_depth(
    reported_regions: list[Region],
    effective_depth: int | None,
) -> list[Region]:
    if effective_depth is None or effective_depth <= 3:
        return reported_regions

    focus_regions = [
        region
        for region in reported_regions
        if 4 <= region.display_depth <= effective_depth
    ]
    return focus_regions or reported_regions


def save_regions(
    out_dir: Path,
    actual_path: Path,
    expected_path: Path,
    actual_size: tuple[int, int],
    expected_original_size: tuple[int, int],
    expected_normalized_size: tuple[int, int],
    normalization: dict[str, object],
    threshold: float,
    min_area: int,
    merge_gap: int,
    hierarchy_depth: int | None,
    report_mode: str | None,
    effective_depth: int | None,
    mask: np.ndarray,
    signals: DiffSignals,
    crop_artifacts: dict[int, dict[str, object]],
    regions: list[Region],
    reported_regions: list[Region],
    suppressed_regions: list[Region],
) -> None:
    artifacts = {
        "annotated_actual": str(out_dir / "annotated_actual.png"),
        "annotated_expected": str(out_dir / "annotated_expected.png"),
        "evidence_overlay_actual": str(out_dir / "evidence_overlay_actual.png"),
        "evidence_overlay_expected": str(out_dir / "evidence_overlay_expected.png"),
        "diff_heatmap": str(out_dir / "diff_heatmap.png"),
        "diff_graymap": str(out_dir / "diff_graymap.png"),
        "diff_color_delta": str(out_dir / "diff_color_delta.png"),
        "diff_structure": str(out_dir / "diff_structure.png"),
        "diff_edges": str(out_dir / "diff_edges.png"),
        "region_crops": str(out_dir / "region_crops"),
        "annotated_raw_actual": str(out_dir / "annotated_raw_actual.png"),
        "annotated_raw_expected": str(out_dir / "annotated_raw_expected.png"),
        "annotated_depth_actual": str(out_dir / "annotated_depth_actual.png"),
        "annotated_depth_expected": str(out_dir / "annotated_depth_expected.png"),
        "regions": str(out_dir / "regions.json"),
    }
    child_counts: dict[int, int] = {}
    for suppressed_region in suppressed_regions:
        if suppressed_region.suppressed_by is not None:
            child_counts[suppressed_region.suppressed_by] = (
                child_counts.get(suppressed_region.suppressed_by, 0) + 1
            )

    def region_payload(region: Region) -> dict[str, object]:
        child_count = child_counts.get(region.region_id, 0)
        finding_summary, review_guidance = region_finding_text(
            region,
            actual_size,
            child_count,
        )
        diff_pixel_count, diff_pixel_bbox = diff_pixel_evidence(region, mask)
        return {
            "id": region.region_id,
            "report_id": region.report_id,
            "x": region.x,
            "y": region.y,
            "width": region.width,
            "height": region.height,
            "area": region.area,
            "mean_delta": region.mean_delta,
            "max_delta": region.max_delta,
            "category_hint": region.category_hint,
            "element_kind": region.element_kind,
            "level": region.level,
            "display_depth": region.display_depth,
            "parent_id": region.parent_id,
            "priority": region.priority,
            "priority_category": region.priority_category,
            "priority_tier": region.priority_tier,
            "severity_score": region.severity_score,
            "severity_factors": region.severity_factors,
            "confidence": {
                "level": region.confidence_level,
                "score": region.confidence_score,
            },
            "dominant_signal": region.dominant_signal,
            "diff_signals": {
                "counts": region.signal_counts,
                "mean_strengths": region.signal_strengths,
            },
            "suppressed_by": region.suppressed_by,
            "report_group": region.report_group,
            "source_region_ids": list(region.source_region_ids),
            "suppressed_child_count": child_count,
            "edge_evidence": edge_evidence(region, actual_size),
            "finding_summary": finding_summary,
            "review_guidance": review_guidance,
            "visual_evidence": {
                "same_coordinate_on_expected": True,
                "coordinate_space": "actual_and_normalized_expected",
                "evidence_overlay": True,
                "uses_suppressed_children": child_count > 0,
                "diff_pixel_count": diff_pixel_count,
                "diff_pixel_bbox": diff_pixel_bbox,
                "region_crops": crop_artifacts.get(region.region_id),
            },
        }

    payload = {
        "actual": str(actual_path),
        "expected": str(expected_path),
        "artifacts": artifacts,
        "audit_order": "top-down",
        "audit_focus": (
            "UI/UX structure and visual fidelity: module position, size, border, "
            "background, color, gradient, spacing, margin, padding, typography metrics, "
            "icon/image size, alignment, screen edges, safe areas, and visual state."
        ),
        "ignored_by_default": [
            "copy-only text differences",
            "dynamic data differences",
            "timestamps and counters",
            "fetched labels or names",
            "device/system UI chrome",
            "rasterization-only noise",
        ],
        "diff_engine": {
            "mode": "multi-signal",
            "signals": [
                "rgb pixel distance",
                "CIE Lab perceptual color distance",
                "local structural dissimilarity",
                "Sobel edge/stroke delta",
            ],
            "thresholds": signals.thresholds,
            "priority_order": [
                "1 size / layout dimensions",
                "2 position / alignment",
                "3 relative relationship / spacing",
                "4 image / icon consistency",
                "5 font metrics / typography",
                "6 foreground color",
                "7 background color",
                "8 gradient",
                "9 shadow / effect",
            ],
            "ranking": (
                "Regions are ranked first by priority_tier, then hierarchy, then severity_score. "
                "Geometry and relationship issues outrank color and decorative effects."
            ),
        },
        "hierarchy_policy": hierarchy_policy_text(hierarchy_depth, report_mode, effective_depth),
        "normalization_policy": (
            "The actual screenshot is the coordinate baseline. If the design image size differs, "
            "the expected design is proportionally fit into the actual screenshot canvas without "
            "cropping before diffing and annotation."
        ),
        "actual_size": image_size_payload(actual_size),
        "expected_size": image_size_payload(expected_original_size),
        "expected_normalized_size": image_size_payload(expected_normalized_size),
        "comparison_size": image_size_payload(actual_size),
        "normalization": normalization,
        "parameters": {
            "threshold": threshold,
            "min_area": min_area,
            "merge_gap": merge_gap,
            "hierarchy_depth": hierarchy_depth,
            "report_mode": report_mode,
            "effective_hierarchy_depth": effective_depth,
            "signal_thresholds": signals.thresholds,
        },
        "regions": [region_payload(region) for region in regions],
        "reported_regions": [region_payload(region) for region in reported_regions],
        "suppressed_regions": [region_payload(region) for region in suppressed_regions],
        "depth_regions": [
            region_payload(region)
            for region in reported_regions
            if effective_depth is not None
        ],
        "focus_regions": [
            region_payload(region)
            for region in focus_regions_for_depth(reported_regions, effective_depth)
        ],
        "parent_regions": [
            region_payload(region)
            for region in reported_regions
            if region.display_depth <= 3
        ],
        "detail_regions": [
            region_payload(region)
            for region in reported_regions
            if 4 <= region.display_depth <= 8
        ],
        "raw_regions": [region_payload(region) for region in regions],
    }
    (out_dir / "regions.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    effective_depth = effective_hierarchy_depth(args.hierarchy_depth, args.report_mode)
    actual_path = Path(args.actual).expanduser().resolve()
    expected_path = Path(args.expected).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    actual_image, actual_array = load_rgb(actual_path)
    expected_original_image, _ = load_rgb(expected_path)
    expected_image, normalization = normalize_expected_to_actual(
        expected_original_image,
        actual_image.size,
    )
    expected_array = np.asarray(expected_image, dtype=np.float32)

    signals = build_difference_signals(actual_array, expected_array, args.threshold)
    mask = signals.combined_mask
    delta = signals.rgb_delta
    components = connected_components(mask, args.min_area)
    priority_mask = denoise_mask(signals.structure_mask | signals.edge_mask)
    priority_components = connected_components(priority_mask, args.min_area)
    detail_components = detail_proposal_components(signals, args.min_area, actual_image.size)
    merged = dedupe_components(
        [
            *merge_components(components, args.merge_gap),
            *merge_components(priority_components, args.merge_gap),
            *detail_components,
        ]
    )
    regions = make_regions(merged, signals, args.max_regions)
    regions, reported_regions, suppressed_regions = apply_hierarchy(
        regions,
        actual_image.size,
        effective_depth,
    )

    evidence_mask = evidence_mask_for_regions(mask, reported_regions)
    crop_artifacts = save_region_crops(
        out_dir,
        actual_image,
        expected_image,
        signals,
        evidence_mask,
        reported_regions,
    )
    annotated = draw_annotations(actual_image, reported_regions)
    annotated_expected = draw_annotations(expected_image, reported_regions)
    annotated_raw = draw_annotations(actual_image, regions)
    annotated_raw_expected = draw_annotations(expected_image, regions)
    focus_regions = focus_regions_for_depth(reported_regions, effective_depth)
    annotated_depth = draw_annotations(actual_image, focus_regions)
    annotated_depth_expected = draw_annotations(expected_image, focus_regions)
    evidence_overlay_actual = draw_evidence_overlay(actual_image, evidence_mask, reported_regions)
    evidence_overlay_expected = draw_evidence_overlay(expected_image, evidence_mask, reported_regions)
    heatmap = draw_heatmap(delta)
    graymap = draw_graymap(delta)
    color_map = draw_scaled_graymap(signals.color_delta, 32.0)
    structure_map = draw_scaled_graymap(signals.structure_delta, 0.35)
    edge_map = draw_scaled_graymap(signals.edge_delta, 192.0)

    annotated.save(out_dir / "annotated_actual.png")
    annotated_expected.save(out_dir / "annotated_expected.png")
    annotated_raw.save(out_dir / "annotated_raw_actual.png")
    annotated_raw_expected.save(out_dir / "annotated_raw_expected.png")
    annotated_depth.save(out_dir / "annotated_depth_actual.png")
    annotated_depth_expected.save(out_dir / "annotated_depth_expected.png")
    evidence_overlay_actual.save(out_dir / "evidence_overlay_actual.png")
    evidence_overlay_expected.save(out_dir / "evidence_overlay_expected.png")
    heatmap.save(out_dir / "diff_heatmap.png")
    graymap.save(out_dir / "diff_graymap.png")
    color_map.save(out_dir / "diff_color_delta.png")
    structure_map.save(out_dir / "diff_structure.png")
    edge_map.save(out_dir / "diff_edges.png")
    save_regions(
        out_dir=out_dir,
        actual_path=actual_path,
        expected_path=expected_path,
        actual_size=actual_image.size,
        expected_original_size=expected_original_image.size,
        expected_normalized_size=expected_image.size,
        normalization=normalization,
        threshold=args.threshold,
        min_area=args.min_area,
        merge_gap=args.merge_gap,
        hierarchy_depth=args.hierarchy_depth,
        report_mode=args.report_mode,
        effective_depth=effective_depth,
        mask=mask,
        signals=signals,
        crop_artifacts=crop_artifacts,
        regions=regions,
        reported_regions=reported_regions,
        suppressed_regions=suppressed_regions,
    )

    print(
        f"Wrote {len(reported_regions)} reported region(s), "
        f"{len(suppressed_regions)} suppressed region(s), "
        f"{len(regions)} raw region(s) to {out_dir}"
    )
    print(f"- {out_dir / 'annotated_actual.png'}")
    print(f"- {out_dir / 'annotated_expected.png'}")
    print(f"- {out_dir / 'annotated_raw_actual.png'}")
    print(f"- {out_dir / 'annotated_raw_expected.png'}")
    print(f"- {out_dir / 'annotated_depth_actual.png'}")
    print(f"- {out_dir / 'annotated_depth_expected.png'}")
    print(f"- {out_dir / 'evidence_overlay_actual.png'}")
    print(f"- {out_dir / 'evidence_overlay_expected.png'}")
    print(f"- {out_dir / 'diff_heatmap.png'}")
    print(f"- {out_dir / 'diff_graymap.png'}")
    print(f"- {out_dir / 'diff_color_delta.png'}")
    print(f"- {out_dir / 'diff_structure.png'}")
    print(f"- {out_dir / 'diff_edges.png'}")
    print(f"- {out_dir / 'region_crops'}")
    print(f"- {out_dir / 'regions.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
