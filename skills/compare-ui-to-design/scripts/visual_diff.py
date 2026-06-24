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
BOX_KEYS = ("x", "y", "width", "height")
NODE_KINDS = {
    "screen",
    "container",
    "text",
    "icon",
    "image",
    "control",
    "background",
    "unknown",
}


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


@dataclass
class UINode:
    node_id: str
    parent_id: str | None
    name: str
    kind: str
    x: int
    y: int
    width: int
    height: int
    text: str = ""
    style: dict[str, object] = field(default_factory=dict)
    visible: bool = True
    confidence: float = 1.0
    source_method: str = "unknown"
    children: list[str] = field(default_factory=list)

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def bbox_area(self) -> int:
        return self.width * self.height

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.width / 2.0, self.y + self.height / 2.0)


@dataclass
class NodeMatch:
    match_id: str
    expected_node: UINode | None
    actual_node: UINode | None
    status: str
    cost: float = 1.0
    local_box: tuple[int, int, int, int] | None = None
    local_score: float | None = None
    delta: dict[str, int] = field(default_factory=dict)
    parent_delta: dict[str, int] = field(default_factory=dict)
    residual_delta: dict[str, int] = field(default_factory=dict)


@dataclass
class UIIssue:
    issue_id: str
    issue_type: str
    category: str
    priority_tier: int
    target_node_id: str
    target_name: str
    node_kind: str
    expected_box: dict[str, int] | None
    actual_box: dict[str, int] | None
    delta: dict[str, int | float | None]
    parent_delta: dict[str, int | float | None]
    residual_delta: dict[str, int | float | None]
    severity_score: float
    confidence_score: float
    diagnosis: str
    suggested_fix: str
    evidence: dict[str, object]
    suppressed_children: list[dict[str, str]] = field(default_factory=list)
    deferred: bool = False
    source_method: str = "node"
    report_id: int | None = None


@dataclass
class ImplementationEvidence:
    evidence_id: str
    name: str
    kind: str
    source_method: str
    bbox: tuple[int, int, int, int] | None = None
    target_node_id: str | None = None
    candidate_id: str | None = None
    source_path: str | None = None
    properties: dict[str, object] = field(default_factory=dict)
    confidence: float = 1.0
    raw: dict[str, object] = field(default_factory=dict)


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
    parser.add_argument(
        "--node-mode",
        choices=("auto", "node", "pixel"),
        default="auto",
        help=(
            "Decision mode. auto/node use visual-first screenshot candidates with optional node "
            "evidence resolution; pixel preserves legacy pixel-region decisions. Default: auto."
        ),
    )
    parser.add_argument(
        "--expected-nodes",
        default=None,
        help="Optional expected/design UI node JSON. Expected boxes are normalized into actual coordinates.",
    )
    parser.add_argument(
        "--actual-nodes",
        default=None,
        help="Optional actual/runtime UI node JSON. Boxes are interpreted in actual screenshot coordinates.",
    )
    parser.add_argument(
        "--implementation-evidence",
        default=None,
        help=(
            "Optional implementation evidence JSON from code, Figma, Chrome DevTools, or other tools. "
            "Evidence is linked to screenshot candidates and cannot suppress visible screenshot issues."
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


def clamp_int(value: float, lower: int, upper: int) -> int:
    return max(lower, min(upper, int(round(value))))


def clamp_box(
    x: float,
    y: float,
    width: float,
    height: float,
    image_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    image_width, image_height = image_size
    x1 = clamp_int(x, 0, image_width)
    y1 = clamp_int(y, 0, image_height)
    x2 = clamp_int(x + max(1.0, width), 0, image_width)
    y2 = clamp_int(y + max(1.0, height), 0, image_height)
    if x2 <= x1:
        x2 = min(image_width, x1 + 1)
    if y2 <= y1:
        y2 = min(image_height, y1 + 1)
    return x1, y1, x2 - x1, y2 - y1


def box_payload(box: tuple[int, int, int, int] | None) -> dict[str, int] | None:
    if box is None:
        return None
    x, y, width, height = box
    return {"x": x, "y": y, "width": width, "height": height}


def node_box(node: UINode | None) -> tuple[int, int, int, int] | None:
    if node is None:
        return None
    return node.x, node.y, node.width, node.height


def box_center(box: tuple[int, int, int, int]) -> tuple[float, float]:
    x, y, width, height = box
    return x + width / 2.0, y + height / 2.0


def center_delta(
    expected_box: tuple[int, int, int, int] | None,
    actual_box: tuple[int, int, int, int] | None,
) -> dict[str, int]:
    if expected_box is None or actual_box is None:
        return {"dx": 0, "dy": 0, "dw": 0, "dh": 0}
    expected_center = box_center(expected_box)
    actual_center = box_center(actual_box)
    return {
        "dx": int(round(actual_center[0] - expected_center[0])),
        "dy": int(round(actual_center[1] - expected_center[1])),
        "dw": actual_box[2] - expected_box[2],
        "dh": actual_box[3] - expected_box[3],
    }


def normalize_node_kind(kind: object) -> str:
    value = str(kind or "unknown").strip().lower().replace("_", "-")
    aliases = {
        "frame": "container",
        "group": "container",
        "section": "container",
        "component": "container",
        "instance": "container",
        "rectangle": "container",
        "shape": "container",
        "vector": "icon",
        "svg": "icon",
        "button": "control",
        "imageview": "image",
        "label": "text",
    }
    normalized = aliases.get(value, value)
    return normalized if normalized in NODE_KINDS else "unknown"


def extract_bbox_payload(payload: dict[str, object]) -> tuple[float, float, float, float] | None:
    raw_box = (
        payload.get("bbox")
        or payload.get("box")
        or payload.get("frame")
        or payload.get("absoluteBoundingBox")
        or payload.get("absoluteRenderBounds")
        or payload.get("bounds")
    )
    if isinstance(raw_box, dict):
        if all(key in raw_box for key in BOX_KEYS):
            return (
                float(raw_box["x"]),
                float(raw_box["y"]),
                float(raw_box["width"]),
                float(raw_box["height"]),
            )
        if all(key in raw_box for key in ("left", "top", "right", "bottom")):
            left = float(raw_box["left"])
            top = float(raw_box["top"])
            return left, top, float(raw_box["right"]) - left, float(raw_box["bottom"]) - top
    if isinstance(raw_box, (list, tuple)) and len(raw_box) >= 4:
        return float(raw_box[0]), float(raw_box[1]), float(raw_box[2]), float(raw_box[3])
    if all(key in payload for key in BOX_KEYS):
        return (
            float(payload["x"]),
            float(payload["y"]),
            float(payload["width"]),
            float(payload["height"]),
        )
    return None


def transform_expected_node_box(
    box: tuple[float, float, float, float],
    normalization: dict[str, object],
    image_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    scale = float(normalization.get("scale", 1.0))
    offset = normalization.get("offset", {"x": 0, "y": 0})
    offset_x = float(offset["x"]) if isinstance(offset, dict) else 0.0
    offset_y = float(offset["y"]) if isinstance(offset, dict) else 0.0
    x, y, width, height = box
    return clamp_box(
        x * scale + offset_x,
        y * scale + offset_y,
        width * scale,
        height * scale,
        image_size,
    )


def node_visibility(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "hidden", "no", "off"}
    return True


def iter_node_payloads(
    payload: object,
    parent_id: str | None = None,
    ancestors_visible: bool = True,
) -> Iterable[tuple[dict[str, object], str | None]]:
    if isinstance(payload, dict):
        if isinstance(payload.get("nodes"), list):
            for item in payload["nodes"]:
                yield from iter_node_payloads(item, parent_id, ancestors_visible)
            return
        current_visible = ancestors_visible and node_visibility(payload.get("visible", True))
        if isinstance(payload.get("children"), list):
            if current_visible:
                yield payload, parent_id
            node_id = str(payload.get("id") or payload.get("node_id") or payload.get("name") or "")
            for child in payload["children"]:
                yield from iter_node_payloads(child, node_id or parent_id, current_visible)
            return
        if current_visible:
            yield payload, parent_id
    elif isinstance(payload, list):
        for item in payload:
            yield from iter_node_payloads(item, parent_id, ancestors_visible)


def load_ui_nodes(
    path: Path | None,
    image_size: tuple[int, int],
    normalization: dict[str, object] | None,
    source_method: str,
) -> list[UINode]:
    if path is None:
        return []

    data = json.loads(path.read_text(encoding="utf-8"))
    nodes: list[UINode] = []
    used_ids: set[str] = set()
    raw_id_to_unique_id: dict[str, str] = {}
    for index, (item, inherited_parent_id) in enumerate(iter_node_payloads(data), start=1):
        if not isinstance(item, dict):
            continue
        bbox = extract_bbox_payload(item)
        if bbox is None:
            continue
        if normalization is not None:
            x, y, width, height = transform_expected_node_box(bbox, normalization, image_size)
        else:
            x, y, width, height = clamp_box(*bbox, image_size)
        raw_id = str(item.get("id") or item.get("node_id") or item.get("name") or f"node-{index}")
        node_id = raw_id
        suffix = 2
        while node_id in used_ids:
            node_id = f"{raw_id}-{suffix}"
            suffix += 1
        used_ids.add(node_id)
        parent_id = item.get("parent_id") or item.get("parentId") or inherited_parent_id
        parent_node_id = raw_id_to_unique_id.get(str(parent_id), str(parent_id)) if parent_id else None
        raw_id_to_unique_id[raw_id] = node_id
        nodes.append(
            UINode(
                node_id=node_id,
                parent_id=parent_node_id,
                name=str(item.get("name") or node_id),
                kind=normalize_node_kind(item.get("kind") or item.get("type") or item.get("role")),
                x=x,
                y=y,
                width=width,
                height=height,
                text=str(item.get("text") or item.get("characters") or item.get("label") or ""),
                style=item.get("style") if isinstance(item.get("style"), dict) else {},
                visible=True,
                confidence=float(item.get("confidence", 1.0)),
                source_method=source_method,
            )
        )
    return build_node_hierarchy(nodes, image_size, source_method)


def iter_evidence_payloads(payload: object) -> Iterable[dict[str, object]]:
    if isinstance(payload, dict):
        for key in ("implementation_evidence", "evidence", "items", "findings", "nodes"):
            if isinstance(payload.get(key), list):
                for item in payload[key]:
                    yield from iter_evidence_payloads(item)
                return
        yield payload
    elif isinstance(payload, list):
        for item in payload:
            yield from iter_evidence_payloads(item)


def evidence_static_agreement(payload: dict[str, object]) -> bool:
    candidates = [
        payload.get("static_agreement"),
        payload.get("matches_expected"),
        payload.get("matches_design"),
        payload.get("agreement"),
        payload.get("static_status"),
    ]
    properties = payload.get("properties")
    if isinstance(properties, dict):
        candidates.extend(
            [
                properties.get("static_agreement"),
                properties.get("matches_expected"),
                properties.get("matches_design"),
                properties.get("agreement"),
                properties.get("static_status"),
            ]
        )
    for value in candidates:
        if isinstance(value, bool) and value:
            return True
        if isinstance(value, str) and value.strip().lower() in {
            "match",
            "matches",
            "matched",
            "aligned",
            "agree",
            "agrees",
            "agreement",
            "same",
            "equal",
            "true",
        }:
            return True
    return False


def load_implementation_evidence(
    path: Path | None,
    image_size: tuple[int, int],
) -> list[ImplementationEvidence]:
    if path is None:
        return []

    data = json.loads(path.read_text(encoding="utf-8"))
    evidence: list[ImplementationEvidence] = []
    used_ids: set[str] = set()
    for index, item in enumerate(iter_evidence_payloads(data), start=1):
        if not isinstance(item, dict):
            continue
        raw_id = str(item.get("id") or item.get("evidence_id") or item.get("name") or f"implementation-{index}")
        evidence_id = raw_id
        suffix = 2
        while evidence_id in used_ids:
            evidence_id = f"{raw_id}-{suffix}"
            suffix += 1
        used_ids.add(evidence_id)
        bbox_payload = extract_bbox_payload(item)
        bbox = clamp_box(*bbox_payload, image_size) if bbox_payload is not None else None
        properties = item.get("properties") if isinstance(item.get("properties"), dict) else {}
        if evidence_static_agreement(item):
            properties = {**properties, "static_agreement": True}
        evidence.append(
            ImplementationEvidence(
                evidence_id=evidence_id,
                name=str(item.get("name") or item.get("target_name") or evidence_id),
                kind=str(item.get("kind") or item.get("type") or "implementation").strip().lower(),
                source_method=str(item.get("source_method") or item.get("source") or "implementation-evidence"),
                bbox=bbox,
                target_node_id=(
                    str(
                        item.get("target_node_id")
                        or item.get("node_id")
                        or item.get("expected_node_id")
                        or item.get("actual_node_id")
                    )
                    if (
                        item.get("target_node_id")
                        or item.get("node_id")
                        or item.get("expected_node_id")
                        or item.get("actual_node_id")
                    )
                    else None
                ),
                candidate_id=str(item.get("candidate_id")) if item.get("candidate_id") else None,
                source_path=str(item.get("source_path") or item.get("file") or item.get("path") or "")
                or None,
                properties=properties,
                confidence=float(item.get("confidence", 1.0)),
                raw=item,
            )
        )
    return evidence


def build_node_hierarchy(
    nodes: list[UINode],
    image_size: tuple[int, int],
    source_method: str,
) -> list[UINode]:
    by_id = {node.node_id: node for node in nodes}
    for node in nodes:
        node.children = []
    for node in nodes:
        if node.parent_id in by_id:
            by_id[node.parent_id].children.append(node.node_id)
        elif node.kind != "screen":
            node.parent_id = "screen"

    if "screen" not in by_id:
        screen = UINode(
            node_id="screen",
            parent_id=None,
            name="Screen",
            kind="screen",
            x=0,
            y=0,
            width=image_size[0],
            height=image_size[1],
            confidence=1.0,
            source_method=source_method,
        )
        nodes.insert(0, screen)
        by_id["screen"] = screen
    for node in nodes:
        if node.node_id != "screen" and node.parent_id is None:
            node.parent_id = "screen"
        if node.parent_id == "screen" and node.node_id not in by_id["screen"].children:
            by_id["screen"].children.append(node.node_id)

    assign_containment_parents(nodes)
    return nodes


def assign_containment_parents(nodes: list[UINode]) -> None:
    by_id = {node.node_id: node for node in nodes}
    candidates = [node for node in nodes if node.kind in {"screen", "container", "background", "control"}]
    for node in nodes:
        if node.node_id == "screen" or node.parent_id not in {None, "screen"}:
            continue
        containing = [
            parent
            for parent in candidates
            if parent.node_id != node.node_id
            and parent.bbox_area > node.bbox_area
            and node.x >= parent.x
            and node.y >= parent.y
            and node.right <= parent.right
            and node.bottom <= parent.bottom
        ]
        if not containing:
            continue
        parent = min(containing, key=lambda candidate: candidate.bbox_area)
        if node.parent_id in by_id and node.node_id in by_id[node.parent_id].children:
            by_id[node.parent_id].children.remove(node.node_id)
        node.parent_id = parent.node_id
        parent.children.append(node.node_id)


def infer_node_kind_from_component(
    x: int,
    y: int,
    width: int,
    height: int,
    area: int,
    image_size: tuple[int, int],
) -> str:
    screen_area = image_size[0] * image_size[1]
    bbox_area = max(1, width * height)
    bbox_ratio = bbox_area / max(1, screen_area)
    fill_ratio = area / bbox_area
    aspect = width / max(1, height)
    if bbox_ratio > 0.18:
        return "background"
    if bbox_ratio > 0.025 or width / max(1, image_size[0]) > 0.28:
        return "container"
    if max(width, height) <= 96 and 0.45 <= aspect <= 2.2 and fill_ratio >= 0.08:
        return "icon"
    if aspect >= 3.0 and height <= 48:
        return "text"
    if 0.65 <= aspect <= 1.55 and width <= 128 and height <= 128:
        return "control"
    return "unknown"


def fallback_ui_nodes_from_image(
    image_array: np.ndarray,
    image_size: tuple[int, int],
    source_method: str,
    max_nodes: int = 120,
) -> list[UINode]:
    gray = luminance(image_array)
    edges = sobel_magnitude(gray)
    background = np.array(
        [
            image_array[0, 0],
            image_array[0, -1],
            image_array[-1, 0],
            image_array[-1, -1],
        ],
        dtype=np.float32,
    ).mean(axis=0)
    color_distance = np.linalg.norm(image_array - background, axis=2)
    edge_threshold = max(18.0, float(np.percentile(edges, 88)))
    color_threshold = max(10.0, float(np.percentile(color_distance, 72)))
    proposal_mask = denoise_mask((edges >= edge_threshold) | (color_distance >= color_threshold))
    components = connected_components(proposal_mask, 12)

    scored = sorted(
        components,
        key=lambda component: (
            component[4],
            (component[2] - component[0]) * (component[3] - component[1]),
        ),
        reverse=True,
    )[: max_nodes * 2]
    nodes = [
        UINode(
            node_id="screen",
            parent_id=None,
            name="Screen",
            kind="screen",
            x=0,
            y=0,
            width=image_size[0],
            height=image_size[1],
            confidence=1.0,
            source_method=source_method,
        )
    ]
    seen_boxes: set[tuple[int, int, int, int]] = set()
    screen_area = image_size[0] * image_size[1]
    for index, component in enumerate(scored, start=1):
        x1, y1, x2, y2, area, _ = component
        width = x2 - x1
        height = y2 - y1
        bbox_area = width * height
        if width < 3 or height < 3 or bbox_area / max(1, screen_area) > 0.90:
            continue
        box = (x1, y1, width, height)
        if box in seen_boxes:
            continue
        seen_boxes.add(box)
        nodes.append(
            UINode(
                node_id=f"{source_method}-{index}",
                parent_id="screen",
                name=f"{source_method}-{index}",
                kind=infer_node_kind_from_component(x1, y1, width, height, area, image_size),
                x=x1,
                y=y1,
                width=width,
                height=height,
                confidence=0.58,
                source_method=source_method,
            )
        )
        if len(nodes) >= max_nodes:
            break
    return build_node_hierarchy(nodes, image_size, source_method)


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


def visual_candidate_identity(region: Region) -> tuple[int, int, int, int]:
    return region.x, region.y, region.width, region.height


def is_detail_visual_candidate(region: Region, image_size: tuple[int, int]) -> bool:
    image_area = image_size[0] * image_size[1]
    if region.priority_tier >= 7:
        return False
    if (
        region.element_kind in {"background/color fill", "screen-edge/safe-area"}
        and region.priority_tier > 3
    ):
        return False
    if region.bbox_area > image_area * 0.18 and region.priority_tier > 3:
        return False
    return (
        region.suppressed_by is not None
        or region.display_depth >= 4
        or region.level >= 2
        or region.element_kind in {
            "icon/image detail",
            "typography/text metrics",
            "typography/icon stroke",
            "border/divider",
        }
    )


def visual_candidate_sort_key(
    region: Region,
    image_size: tuple[int, int],
) -> tuple[int, int, int, float, int, int, int]:
    detail_rank = 0 if is_detail_visual_candidate(region, image_size) else 1
    return (
        region.priority_tier,
        detail_rank,
        region.display_depth,
        -region.severity_score,
        region.y,
        region.x,
        region.region_id,
    )


def visual_candidate_pool(
    raw_regions: list[Region],
    reported_regions: list[Region],
    image_size: tuple[int, int],
    max_regions: int,
) -> list[Region]:
    """Keep screenshot candidates independent from compatibility report markers."""
    candidates = [
        *reported_regions,
        *[
            region
            for region in raw_regions
            if is_detail_visual_candidate(region, image_size)
        ],
    ]
    candidates.sort(key=lambda region: visual_candidate_sort_key(region, image_size))

    selected: list[Region] = []
    seen_boxes: set[tuple[int, int, int, int]] = set()
    for region in candidates:
        identity = visual_candidate_identity(region)
        if identity in seen_boxes:
            continue
        selected.append(region)
        seen_boxes.add(identity)
        if len(selected) >= max_regions:
            break
    return selected


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


def node_payload(node: UINode) -> dict[str, object]:
    return {
        "id": node.node_id,
        "parent_id": node.parent_id,
        "name": node.name,
        "kind": node.kind,
        "bbox": box_payload(node_box(node)),
        "text": node.text,
        "style": node.style,
        "visible": node.visible,
        "confidence": round(node.confidence, 3),
        "source_method": node.source_method,
        "children": node.children,
    }


def implementation_evidence_payload(evidence: ImplementationEvidence) -> dict[str, object]:
    return {
        "id": evidence.evidence_id,
        "name": evidence.name,
        "kind": evidence.kind,
        "source_method": evidence.source_method,
        "bbox": box_payload(evidence.bbox),
        "target_node_id": evidence.target_node_id,
        "candidate_id": evidence.candidate_id,
        "source_path": evidence.source_path,
        "properties": evidence.properties,
        "confidence": round(evidence.confidence, 3),
    }


def region_box(region: Region) -> tuple[int, int, int, int]:
    return region.x, region.y, region.width, region.height


def box_area(box: tuple[int, int, int, int] | None) -> int:
    if box is None:
        return 0
    return max(0, box[2]) * max(0, box[3])


def box_intersection_area(
    a: tuple[int, int, int, int] | None,
    b: tuple[int, int, int, int] | None,
) -> int:
    if a is None or b is None:
        return 0
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return max(0, min(ax + aw, bx + bw) - max(ax, bx)) * max(
        0,
        min(ay + ah, by + bh) - max(ay, by),
    )


def box_overlap_score(
    a: tuple[int, int, int, int] | None,
    b: tuple[int, int, int, int] | None,
) -> float:
    intersection = box_intersection_area(a, b)
    if intersection <= 0:
        return 0.0
    return intersection / max(1, min(box_area(a), box_area(b)))


def candidate_id_values(region: Region) -> set[str]:
    return {
        str(region.region_id),
        f"region-{region.region_id}",
        f"visual-{region.region_id}",
        f"V-{region.region_id:03d}",
    }


def candidate_simple_payload(region: Region, mask: np.ndarray | None = None) -> dict[str, object]:
    diff_count = None
    diff_bbox = None
    if mask is not None:
        diff_count, diff_bbox = diff_pixel_evidence(region, mask)
    return {
        "id": f"V-{region.region_id:03d}",
        "region_id": region.region_id,
        "bbox": box_payload(region_box(region)),
        "category": region.priority_category,
        "priority_tier": region.priority_tier,
        "element_kind": region.element_kind,
        "severity_score": region.severity_score,
        "confidence_score": region.confidence_score,
        "dominant_signal": region.dominant_signal,
        "diff_pixel_count": diff_count,
        "diff_pixel_bbox": diff_bbox,
    }


def is_detail_node(node: UINode) -> bool:
    return node.kind in {"text", "icon", "image", "control", "unknown"} and node.kind != "screen"


def is_screenshot_parser_node(node: UINode) -> bool:
    return node.source_method.endswith("-screenshot-parser")


def is_visual_detail_target_node(node: UINode) -> bool:
    if is_detail_node(node):
        return True
    if not is_screenshot_parser_node(node) or node.kind != "container":
        return False
    return max(node.width, node.height) <= 128 and node.bbox_area <= 96 * 96


def is_broad_screenshot_parser_node(node: UINode) -> bool:
    return (
        is_screenshot_parser_node(node)
        and node.kind in {"container", "background"}
        and not is_visual_detail_target_node(node)
    )


def has_external_node_link(links: list[tuple[UINode, float]]) -> bool:
    return any(not is_screenshot_parser_node(node) for node, _ in links)


def linked_nodes_for_region(
    region: Region,
    nodes: list[UINode],
    min_overlap: float = 0.08,
) -> list[tuple[UINode, float]]:
    candidate_box = region_box(region)
    linked: list[tuple[UINode, float]] = []
    for node in nodes:
        if node.kind == "screen":
            continue
        score = box_overlap_score(candidate_box, node_box(node))
        if score >= min_overlap:
            linked.append((node, score))
    linked.sort(
        key=lambda item: (
            not is_visual_detail_target_node(item[0]),
            -item[1],
            item[0].bbox_area,
            item[0].node_id,
        )
    )
    return linked[:8]


def linked_implementation_evidence_for_region(
    region: Region,
    implementation_evidence: list[ImplementationEvidence],
    linked_node_ids: set[str],
    min_overlap: float = 0.08,
) -> list[tuple[ImplementationEvidence, float]]:
    candidate_box = region_box(region)
    candidate_ids = candidate_id_values(region)
    linked: list[tuple[ImplementationEvidence, float]] = []
    for evidence in implementation_evidence:
        score = 0.0
        if evidence.candidate_id and evidence.candidate_id in candidate_ids:
            score = 1.0
        elif evidence.target_node_id and evidence.target_node_id in linked_node_ids:
            score = 0.95
        elif evidence.bbox is not None:
            score = box_overlap_score(candidate_box, evidence.bbox)
        if score >= min_overlap:
            linked.append((evidence, score))
    linked.sort(key=lambda item: (-item[1], item[0].evidence_id))
    return linked[:8]


def node_link_payload(node: UINode, score: float) -> dict[str, object]:
    payload = node_payload(node)
    payload["overlap_score"] = round(score, 4)
    return payload


def evidence_link_payload(evidence: ImplementationEvidence, score: float) -> dict[str, object]:
    payload = implementation_evidence_payload(evidence)
    payload["overlap_score"] = round(score, 4)
    return payload


def best_target_node(
    expected_links: list[tuple[UINode, float]],
    actual_links: list[tuple[UINode, float]],
) -> UINode | None:
    combined = [
        item
        for item in [*expected_links, *actual_links]
        if not is_broad_screenshot_parser_node(item[0])
    ]
    if not combined:
        return None
    combined.sort(
        key=lambda item: (
            not is_visual_detail_target_node(item[0]),
            -item[1],
            item[0].bbox_area,
            item[0].node_id,
        )
    )
    return combined[0][0]


def match_for_target_node(
    target_node: UINode | None,
    node_matches: list[NodeMatch],
) -> NodeMatch | None:
    if target_node is None:
        return None
    for match in node_matches:
        if match.expected_node and match.expected_node.node_id == target_node.node_id:
            return match
        if match.actual_node and match.actual_node.node_id == target_node.node_id:
            return match
    return None


def bbox_distance(a: UINode, b: UINode, image_size: tuple[int, int]) -> float:
    ac = a.center
    bc = b.center
    distance = math.hypot(ac[0] - bc[0], ac[1] - bc[1])
    diagonal = math.hypot(image_size[0], image_size[1])
    return min(1.0, distance / max(1.0, diagonal * 0.25))


def size_difference(a: UINode, b: UINode) -> float:
    width = abs(a.width - b.width) / max(a.width, b.width, 1)
    height = abs(a.height - b.height) / max(a.height, b.height, 1)
    return min(1.0, (width + height) / 2.0)


def text_distance(a: UINode, b: UINode) -> float:
    if not a.text and not b.text:
        return 0.0
    if a.text == b.text:
        return 0.0
    if not a.text or not b.text:
        return 0.6
    common = sum(1 for left, right in zip(a.text, b.text) if left == right)
    return 1.0 - common / max(len(a.text), len(b.text), 1)


def crop_array(
    image_array: np.ndarray,
    box: tuple[int, int, int, int],
) -> np.ndarray:
    x, y, width, height = box
    return image_array[y : y + height, x : x + width]


def reduced_patch_feature(patch: np.ndarray, max_side: int = 48) -> np.ndarray:
    if patch.size == 0:
        return np.zeros((1, 1), dtype=np.float32)
    gray = luminance(patch) if patch.ndim == 3 else patch.astype(np.float32)
    stride = max(1, math.ceil(max(gray.shape) / max_side))
    return gray[::stride, ::stride].astype(np.float32)


def patch_distance(
    expected_array: np.ndarray,
    actual_array: np.ndarray,
    expected_box: tuple[int, int, int, int],
    actual_box: tuple[int, int, int, int],
) -> float:
    if expected_box[2] <= 0 or expected_box[3] <= 0 or actual_box[2] <= 0 or actual_box[3] <= 0:
        return 1.0
    expected_patch = crop_array(expected_array, expected_box)
    actual_patch = crop_array(actual_array, actual_box)
    if expected_patch.size == 0 or actual_patch.size == 0:
        return 1.0
    if expected_patch.shape[:2] != actual_patch.shape[:2]:
        actual_image = Image.fromarray(np.clip(actual_patch, 0, 255).astype(np.uint8))
        actual_patch = np.asarray(actual_image.resize((expected_patch.shape[1], expected_patch.shape[0]), resize_filter()), dtype=np.float32)
    expected_feature = reduced_patch_feature(expected_patch)
    actual_feature = reduced_patch_feature(actual_patch)
    min_height = min(expected_feature.shape[0], actual_feature.shape[0])
    min_width = min(expected_feature.shape[1], actual_feature.shape[1])
    if min_height == 0 or min_width == 0:
        return 1.0
    expected_feature = expected_feature[:min_height, :min_width]
    actual_feature = actual_feature[:min_height, :min_width]
    gray_delta = float(np.mean(np.abs(expected_feature - actual_feature))) / 255.0
    edge_delta_value = float(
        np.mean(np.abs(sobel_magnitude(expected_feature) - sobel_magnitude(actual_feature)))
    ) / 255.0
    return min(1.0, gray_delta * 0.65 + edge_delta_value * 0.35)


def node_match_cost(
    expected_node: UINode,
    actual_node: UINode,
    expected_array: np.ndarray,
    actual_array: np.ndarray,
    image_size: tuple[int, int],
    hierarchy_context_distance: float,
) -> float:
    visual_distance = patch_distance(
        expected_array,
        actual_array,
        node_box(expected_node) or (0, 0, 1, 1),
        node_box(actual_node) or (0, 0, 1, 1),
    )
    kind_mismatch = 0.0 if expected_node.kind == actual_node.kind else 1.0
    return round(
        0.30 * bbox_distance(expected_node, actual_node, image_size)
        + 0.20 * size_difference(expected_node, actual_node)
        + 0.20 * visual_distance
        + 0.15 * text_distance(expected_node, actual_node)
        + 0.10 * kind_mismatch
        + 0.05 * hierarchy_context_distance,
        4,
    )


def best_local_match_box(
    expected_node: UINode,
    expected_array: np.ndarray,
    actual_array: np.ndarray,
    image_size: tuple[int, int],
) -> tuple[tuple[int, int, int, int], float]:
    margin = 12 if expected_node.kind in {"screen", "container", "background"} else 24
    expected_box = node_box(expected_node) or (0, 0, 1, 1)
    x, y, width, height = expected_box
    if width * height > image_size[0] * image_size[1] * 0.18:
        return expected_box, 1.0
    expected_patch = crop_array(expected_array, expected_box)
    if expected_patch.size == 0:
        return expected_box, 1.0
    expected_feature = reduced_patch_feature(expected_patch)
    if float(np.std(expected_feature)) < 3.0 and float(np.mean(sobel_magnitude(expected_feature))) < 3.0:
        return expected_box, 1.0
    step = 1 if max(width, height) <= 96 else 2
    best_box = expected_box
    best_distance = 1.0
    for dy in range(-margin, margin + 1, step):
        for dx in range(-margin, margin + 1, step):
            candidate = clamp_box(x + dx, y + dy, width, height, image_size)
            distance = patch_distance(expected_array, actual_array, expected_box, candidate)
            if distance < best_distance:
                best_distance = distance
                best_box = candidate
    return best_box, round(best_distance, 4)


def effective_actual_box_for_match(match: NodeMatch) -> tuple[int, int, int, int] | None:
    expected_box = node_box(match.expected_node)
    actual_box = node_box(match.actual_node)
    if (
        match.status != "matched"
        or match.expected_node is None
        or match.expected_node.kind in {"screen", "container", "background"}
        or expected_box is None
        or actual_box is None
        or match.local_box is None
        or match.local_score is None
        or match.local_score > 0.36
    ):
        return actual_box

    raw_delta = center_delta(expected_box, actual_box)
    raw_geometry_distance = max(
        abs(raw_delta["dx"]),
        abs(raw_delta["dy"]),
        abs(raw_delta["dw"]),
        abs(raw_delta["dh"]),
    )
    local_delta = center_delta(expected_box, match.local_box)
    local_position_distance = max(abs(local_delta["dx"]), abs(local_delta["dy"]))
    if raw_geometry_distance < 3 and local_position_distance >= 3:
        return match.local_box
    return actual_box


def children_by_parent(nodes: list[UINode]) -> dict[str | None, list[UINode]]:
    children: dict[str | None, list[UINode]] = {}
    for node in nodes:
        children.setdefault(node.parent_id, []).append(node)
    return children


def match_scope(
    expected_children: list[UINode],
    actual_children: list[UINode],
    expected_array: np.ndarray,
    actual_array: np.ndarray,
    image_size: tuple[int, int],
    hierarchy_context_distance: float,
    match_prefix: str,
) -> tuple[list[NodeMatch], set[str], set[str]]:
    candidates: list[tuple[float, UINode, UINode]] = []
    for expected_node in expected_children:
        if expected_node.kind == "screen":
            continue
        for actual_node in actual_children:
            if actual_node.kind == "screen":
                continue
            if (
                bbox_distance(expected_node, actual_node, image_size) >= 0.88
                and not (expected_node.text and expected_node.text == actual_node.text)
            ):
                continue
            cost = node_match_cost(
                expected_node,
                actual_node,
                expected_array,
                actual_array,
                image_size,
                hierarchy_context_distance,
            )
            if expected_node.kind == actual_node.kind or cost <= 0.52:
                candidates.append((cost, expected_node, actual_node))

    candidates.sort(key=lambda item: (item[0], item[1].node_id, item[2].node_id))
    matches: list[NodeMatch] = []
    used_expected: set[str] = set()
    used_actual: set[str] = set()
    for cost, expected_node, actual_node in candidates:
        if expected_node.node_id in used_expected or actual_node.node_id in used_actual:
            continue
        if cost > 0.74:
            continue
        local_box, local_score = best_local_match_box(
            expected_node,
            expected_array,
            actual_array,
            image_size,
        )
        match = NodeMatch(
            match_id=f"{match_prefix}-{len(matches) + 1}",
            expected_node=expected_node,
            actual_node=actual_node,
            status="matched",
            cost=cost,
            local_box=local_box,
            local_score=local_score,
        )
        match.delta = center_delta(node_box(expected_node), effective_actual_box_for_match(match))
        used_expected.add(expected_node.node_id)
        used_actual.add(actual_node.node_id)
        matches.append(match)
    return matches, used_expected, used_actual


def match_ui_nodes(
    expected_nodes: list[UINode],
    actual_nodes: list[UINode],
    expected_array: np.ndarray,
    actual_array: np.ndarray,
    image_size: tuple[int, int],
) -> list[NodeMatch]:
    expected_by_id = {node.node_id: node for node in expected_nodes}
    actual_by_id = {node.node_id: node for node in actual_nodes}
    expected_children = children_by_parent(expected_nodes)
    actual_children = children_by_parent(actual_nodes)
    matches: list[NodeMatch] = []
    matched_expected: set[str] = set()
    matched_actual: set[str] = set()

    if "screen" in expected_by_id and "screen" in actual_by_id:
        screen_match = NodeMatch(
            match_id="screen",
            expected_node=expected_by_id["screen"],
            actual_node=actual_by_id["screen"],
            status="matched",
            cost=0.0,
            delta=center_delta(node_box(expected_by_id["screen"]), node_box(actual_by_id["screen"])),
        )
        matches.append(screen_match)
        matched_expected.add("screen")
        matched_actual.add("screen")

    scopes = [("screen", "screen")]
    visited_scopes: set[tuple[str, str]] = set()
    while scopes:
        expected_parent_id, actual_parent_id = scopes.pop(0)
        if (expected_parent_id, actual_parent_id) in visited_scopes:
            continue
        visited_scopes.add((expected_parent_id, actual_parent_id))
        scope_matches, used_expected, used_actual = match_scope(
            [node for node in expected_children.get(expected_parent_id, []) if node.node_id not in matched_expected],
            [node for node in actual_children.get(actual_parent_id, []) if node.node_id not in matched_actual],
            expected_array,
            actual_array,
            image_size,
            0.0,
            f"scope-{len(visited_scopes)}",
        )
        matches.extend(scope_matches)
        matched_expected |= used_expected
        matched_actual |= used_actual
        for match in scope_matches:
            if match.expected_node and match.actual_node:
                scopes.append((match.expected_node.node_id, match.actual_node.node_id))

    remaining_expected = [node for node in expected_nodes if node.node_id not in matched_expected]
    remaining_actual = [node for node in actual_nodes if node.node_id not in matched_actual]
    fallback_matches, used_expected, used_actual = match_scope(
        remaining_expected,
        remaining_actual,
        expected_array,
        actual_array,
        image_size,
        1.0,
        "global",
    )
    matches.extend(fallback_matches)
    matched_expected |= used_expected
    matched_actual |= used_actual

    for node in expected_nodes:
        if node.node_id not in matched_expected and node.kind != "screen":
            matches.append(
                NodeMatch(
                    match_id=f"missing-{node.node_id}",
                    expected_node=node,
                    actual_node=None,
                    status="missing",
                    cost=1.0,
                )
            )
    for node in actual_nodes:
        if node.node_id not in matched_actual and node.kind != "screen":
            matches.append(
                NodeMatch(
                    match_id=f"extra-{node.node_id}",
                    expected_node=None,
                    actual_node=node,
                    status="extra",
                    cost=1.0,
                )
            )
    return matches


def category_tier(category: str) -> int:
    order = {
        "size / layout dimensions": 1,
        "position / alignment": 2,
        "relative relationship / spacing": 3,
        "missing element": 4,
        "extra element": 4,
        "image / icon consistency": 4,
        "font metrics / typography": 5,
        "foreground color": 6,
        "background color": 7,
        "gradient": 8,
        "shadow / effect": 9,
    }
    return order.get(category, 9)


def issue_category_for_node(
    node: UINode,
    delta: dict[str, int],
    residual: dict[str, int],
) -> str | None:
    size_delta = max(abs(delta["dw"]), abs(delta["dh"]))
    size_ratio = max(
        abs(delta["dw"]) / max(node.width, 1),
        abs(delta["dh"]) / max(node.height, 1),
    )
    residual_distance = max(abs(residual["dx"]), abs(residual["dy"]))
    if size_delta >= 3 or size_ratio >= 0.03:
        return "size / layout dimensions"
    if residual_distance >= 3:
        return "position / alignment"
    return None


def issue_severity(category: str, delta: dict[str, int], node: UINode | None, cost: float) -> float:
    distance = max(abs(delta.get("dx", 0)), abs(delta.get("dy", 0)), abs(delta.get("dw", 0)), abs(delta.get("dh", 0)))
    size_factor = min(1.0, distance / 24.0)
    area_factor = 0.0
    if node is not None:
        area_factor = min(1.0, math.sqrt(node.bbox_area) / 220.0)
    base = {
        "missing element": 74.0,
        "extra element": 66.0,
        "size / layout dimensions": 58.0,
        "position / alignment": 52.0,
        "image / icon consistency": 48.0,
        "font metrics / typography": 46.0,
        "background color": 22.0,
    }.get(category, 35.0)
    return round(min(100.0, base + size_factor * 28.0 + area_factor * 10.0 + max(0.0, 1.0 - cost) * 4.0), 2)


def issue_confidence(match: NodeMatch, source_method: str) -> float:
    base = 0.82 if "json" in source_method or "nodes" in source_method else 0.58
    if match.status == "matched":
        base += max(0.0, 0.18 * (1.0 - match.cost))
    if match.local_score is not None:
        base += max(0.0, 0.10 * (1.0 - match.local_score))
    return round(max(0.1, min(0.98, base)), 3)


def issue_text(
    issue_type: str,
    category: str,
    node: UINode,
    delta: dict[str, int],
    residual: dict[str, int],
    parent_delta: dict[str, int],
) -> tuple[str, str]:
    name = node.name or node.node_id
    if issue_type == "missing":
        return (
            f"{name} is present in the expected design but no matching runtime node was found.",
            "Add or reveal the missing UI element, or check conditional rendering for this state.",
        )
    if issue_type == "extra":
        return (
            f"{name} appears in the runtime UI but no matching expected design node was found.",
            "Remove the extra UI element or confirm the design reference includes this state.",
        )
    if category == "size / layout dimensions":
        return (
            f"{name} has size delta dw={delta['dw']}px, dh={delta['dh']}px versus the expected node.",
            "Adjust width, height, padding, or layout constraints for this node.",
        )
    return (
        f"{name} has residual position delta dx={residual['dx']}px, dy={residual['dy']}px after parent delta dx={parent_delta['dx']}px, dy={parent_delta['dy']}px.",
        "Adjust this node's alignment, offset, padding, gap, or local layout constraints.",
    )


def diagnose_node_issues(
    matches: list[NodeMatch],
    signals: DiffSignals,
    image_size: tuple[int, int],
) -> tuple[list[UIIssue], list[UIIssue]]:
    matched_by_expected = {
        match.expected_node.node_id: match
        for match in matches
        if match.status == "matched" and match.expected_node is not None
    }
    issues: list[UIIssue] = []
    issue_index = 1

    for match in matches:
        node = match.expected_node or match.actual_node
        if node is None or node.kind == "screen":
            continue
        expected_box = node_box(match.expected_node)
        actual_node_box = node_box(match.actual_node)
        actual_box = effective_actual_box_for_match(match)
        if match.status == "missing":
            category = "missing element"
            delta = {"dx": None, "dy": None, "dw": None, "dh": None}
            parent_delta = {"dx": 0, "dy": 0, "dw": 0, "dh": 0}
            residual = parent_delta
        elif match.status == "extra":
            category = "extra element"
            delta = {"dx": None, "dy": None, "dw": None, "dh": None}
            parent_delta = {"dx": 0, "dy": 0, "dw": 0, "dh": 0}
            residual = parent_delta
        else:
            delta = center_delta(expected_box, actual_box)
            parent_match = (
                matched_by_expected.get(match.expected_node.parent_id)
                if match.expected_node and match.expected_node.parent_id
                else None
            )
            parent_delta = (
                center_delta(node_box(parent_match.expected_node), effective_actual_box_for_match(parent_match))
                if parent_match
                else {"dx": 0, "dy": 0, "dw": 0, "dh": 0}
            )
            residual = {
                "dx": int(delta["dx"] - parent_delta["dx"]),
                "dy": int(delta["dy"] - parent_delta["dy"]),
                "dw": int(delta["dw"]),
                "dh": int(delta["dh"]),
            }
            match.delta = delta
            match.parent_delta = parent_delta
            match.residual_delta = residual
            category = issue_category_for_node(node, delta, residual)
            if category is None:
                continue

        diagnosis, suggested_fix = issue_text(
            match.status,
            category,
            node,
            {key: int(value or 0) for key, value in delta.items()},
            {key: int(value or 0) for key, value in residual.items()},
            {key: int(value or 0) for key, value in parent_delta.items()},
        )
        evidence_region = Region(
            region_id=0,
            x=(actual_box or expected_box or (0, 0, 1, 1))[0],
            y=(actual_box or expected_box or (0, 0, 1, 1))[1],
            width=(actual_box or expected_box or (0, 0, 1, 1))[2],
            height=(actual_box or expected_box or (0, 0, 1, 1))[3],
            area=max(1, (actual_box or expected_box or (0, 0, 1, 1))[2] * (actual_box or expected_box or (0, 0, 1, 1))[3]),
            mean_delta=0.0,
            max_delta=0.0,
            category_hint=category,
        )
        diff_count, diff_bbox = diff_pixel_evidence(evidence_region, signals.combined_mask)
        source_method = node.source_method
        issue = UIIssue(
            issue_id=f"I-{issue_index:03d}",
            issue_type=match.status if match.status != "matched" else "node_diff",
            category=category,
            priority_tier=category_tier(category),
            target_node_id=node.node_id,
            target_name=node.name,
            node_kind=node.kind,
            expected_box=box_payload(expected_box),
            actual_box=box_payload(actual_box),
            delta=delta,
            parent_delta=parent_delta,
            residual_delta=residual,
            severity_score=issue_severity(category, {key: int(value or 0) for key, value in delta.items()}, node, match.cost),
            confidence_score=issue_confidence(match, source_method),
            diagnosis=diagnosis,
            suggested_fix=suggested_fix,
            evidence={
                "match_cost": match.cost,
                "node_actual_box": box_payload(actual_node_box),
                "local_search_box": box_payload(match.local_box),
                "local_search_score": match.local_score,
                "diff_pixel_count": diff_count,
                "diff_pixel_bbox": diff_bbox,
                "pixel_diff_is_evidence_only": True,
            },
            source_method=source_method,
        )
        issues.append(issue)
        issue_index += 1

    by_target = {issue.target_node_id: issue for issue in issues}
    for match in matches:
        if match.status != "matched" or match.expected_node is None:
            continue
        parent_issue = by_target.get(match.expected_node.parent_id or "")
        if parent_issue is None or match.expected_node.node_id == parent_issue.target_node_id:
            continue
        residual = match.residual_delta or {"dx": 0, "dy": 0}
        if max(abs(int(residual.get("dx", 0))), abs(int(residual.get("dy", 0)))) < 3:
            parent_issue.suppressed_children.append(
                {
                    "node": match.expected_node.node_id,
                    "reason": f"same common parent offset as {parent_issue.target_node_id}",
                }
            )

    actionable = [issue for issue in issues if not issue.deferred and issue.priority_tier <= 6]
    deferred = [issue for issue in issues if issue.deferred or issue.priority_tier >= 7]
    actionable.sort(key=lambda issue: (issue.priority_tier, -issue.severity_score, issue.target_name))
    deferred.sort(key=lambda issue: (issue.priority_tier, -issue.severity_score, issue.target_name))
    for report_id, issue in enumerate([*actionable, *deferred], start=1):
        issue.report_id = report_id
    return actionable, deferred


def deferred_background_issues_from_pixels(
    pixel_regions: list[Region],
    signals: DiffSignals,
    image_size: tuple[int, int],
    start_index: int,
) -> list[UIIssue]:
    deferred: list[UIIssue] = []
    screen_area = image_size[0] * image_size[1]
    for region in pixel_regions:
        area_ratio = region.bbox_area / max(1, screen_area)
        edge_count = region.signal_counts.get("edge", 0)
        structure_mean = region.signal_strengths.get("structure_dissimilarity", 0.0)
        color_mean = region.signal_strengths.get("color_delta_e", 0.0)
        edge_density = edge_count / max(1, region.area)
        if not (
            area_ratio > 0.18
            and color_mean > signals.thresholds["color_delta_e"]
            and edge_density < 0.025
            and structure_mean < 0.08
        ):
            continue
        box = {"x": region.x, "y": region.y, "width": region.width, "height": region.height}
        deferred.append(
            UIIssue(
                issue_id=f"I-{start_index + len(deferred):03d}",
                issue_type="deferred_style",
                category="background color",
                priority_tier=7,
                target_node_id=f"pixel-region-{region.region_id}",
                target_name=f"Pixel region {region.region_id}",
                node_kind="background",
                expected_box=box,
                actual_box=box,
                delta={"dx": 0, "dy": 0, "dw": 0, "dh": 0},
                parent_delta={"dx": 0, "dy": 0, "dw": 0, "dh": 0},
                residual_delta={"dx": 0, "dy": 0, "dw": 0, "dh": 0},
                severity_score=min(40.0, region.severity_score),
                confidence_score=region.confidence_score,
                diagnosis="Large low-frequency color difference is treated as deferred visual style evidence.",
                suggested_fix="Check background fill, gradient, opacity, or shadow only after actionable layout/text/icon issues are handled.",
                evidence={
                    "source_region_id": region.region_id,
                    "area_ratio": round(area_ratio, 4),
                    "edge_density": round(edge_density, 5),
                    "structure_mean": structure_mean,
                    "color_mean": color_mean,
                    "pixel_diff_is_evidence_only": True,
                },
                deferred=True,
                source_method="pixel-evidence",
            )
        )
    return deferred[:1]


def issue_box_tuple(payload: dict[str, int] | None) -> tuple[int, int, int, int] | None:
    if payload is None:
        return None
    return (
        int(payload["x"]),
        int(payload["y"]),
        int(payload["width"]),
        int(payload["height"]),
    )


def issue_overlaps_any_visual_candidate(issue: UIIssue, candidates: list[Region]) -> bool:
    issue_boxes = [
        issue_box_tuple(issue.expected_box),
        issue_box_tuple(issue.actual_box),
    ]
    for box in issue_boxes:
        if box is None:
            continue
        if any(box_overlap_score(box, region_box(candidate)) >= 0.08 for candidate in candidates):
            return True
    return False


def visual_issue_text(
    region: Region,
    target_name: str,
    resolution_status: str,
    static_agreement: bool,
) -> tuple[str, str]:
    if static_agreement:
        return (
            f"{target_name} has a visible screenshot mismatch, while static implementation evidence agrees with the design.",
            "Keep the visual issue; inspect rendered asset size, mask, stroke, shadow, scale, anti-aliasing, layout proposal, or clipping rather than trusting constants alone.",
        )
    if resolution_status == "resolved_to_detail_node":
        return (
            f"{target_name} is the nearest detail node explaining visual candidate V-{region.region_id:03d}.",
            "Fix the local rendered node: size, position, crop, glyph metrics, icon asset, stroke, padding, or alignment.",
        )
    if resolution_status == "screenshot_parser_detail_candidate":
        return (
            f"{target_name} is the screenshot-parser detail candidate explaining visual candidate V-{region.region_id:03d}.",
            "Keep the screenshot-backed issue, then use Figma/get_design_context, Chrome DevTools, or source search to confirm the owning implementation node.",
        )
    if resolution_status == "resolved_to_container_or_metadata":
        return (
            f"{target_name} is the nearest available node/evidence for visual candidate V-{region.region_id:03d}, but no leaf detail node was confirmed.",
            "Use Figma/get_design_context, Chrome DevTools, or code search to inspect child nodes before applying a broad parent fix.",
        )
    return (
        f"Visual candidate V-{region.region_id:03d} is screenshot-backed but has no external node/code evidence attached.",
        "Use Figma/get_design_context, Chrome DevTools, or source search around this crop to locate the exact owning element.",
    )


def visual_issue_confidence(
    region: Region,
    resolution_status: str,
    linked_implementation: list[tuple[ImplementationEvidence, float]],
) -> float:
    confidence = region.confidence_score or 0.5
    if resolution_status == "resolved_to_detail_node":
        confidence += 0.14
    elif resolution_status == "screenshot_parser_detail_candidate":
        confidence += 0.08
    elif resolution_status == "resolved_to_container_or_metadata":
        confidence += 0.07
    if linked_implementation:
        confidence += min(0.08, max(score for _, score in linked_implementation) * 0.08)
    return round(max(0.1, min(0.98, confidence)), 3)


def build_visual_issue(
    region: Region,
    issue_index: int,
    mask: np.ndarray,
    expected_links: list[tuple[UINode, float]],
    actual_links: list[tuple[UINode, float]],
    implementation_links: list[tuple[ImplementationEvidence, float]],
    node_matches: list[NodeMatch],
) -> tuple[UIIssue, dict[str, object] | None]:
    target_node = best_target_node(expected_links, actual_links)
    target_match = match_for_target_node(target_node, node_matches)
    target_name = target_node.name if target_node else f"Visual candidate V-{region.region_id:03d}"
    target_id = target_node.node_id if target_node else f"visual-candidate-{region.region_id}"
    target_kind = target_node.kind if target_node else region.element_kind
    detail_resolved = target_node is not None and is_visual_detail_target_node(target_node)
    target_has_external_node = target_node is not None and not is_screenshot_parser_node(target_node)
    has_external_evidence = (
        has_external_node_link(expected_links)
        or has_external_node_link(actual_links)
        or bool(implementation_links)
    )
    static_agreement = any(
        bool(evidence.properties.get("static_agreement"))
        for evidence, _ in implementation_links
    )

    if static_agreement:
        resolution_status = "rendered visual mismatch with static implementation agreement"
    elif detail_resolved and target_has_external_node:
        resolution_status = "resolved_to_detail_node"
    elif detail_resolved:
        resolution_status = "screenshot_parser_detail_candidate"
    elif has_external_evidence:
        resolution_status = "resolved_to_container_or_metadata"
    else:
        resolution_status = "visual_only_unresolved"

    expected_box = None
    actual_box = None
    delta: dict[str, int | float | None] = {"dx": None, "dy": None, "dw": None, "dh": None}
    parent_delta: dict[str, int | float | None] = {"dx": 0, "dy": 0, "dw": 0, "dh": 0}
    residual_delta: dict[str, int | float | None] = {"dx": None, "dy": None, "dw": None, "dh": None}
    if target_match is not None:
        expected_box_tuple = node_box(target_match.expected_node)
        actual_box_tuple = effective_actual_box_for_match(target_match)
        expected_box = box_payload(expected_box_tuple)
        actual_box = box_payload(actual_box_tuple)
        delta = target_match.delta or center_delta(expected_box_tuple, actual_box_tuple)
        parent_delta = target_match.parent_delta or {"dx": 0, "dy": 0, "dw": 0, "dh": 0}
        residual_delta = target_match.residual_delta or delta
    elif target_node is not None:
        if any(node.node_id == target_node.node_id for node, _ in expected_links):
            expected_box = box_payload(node_box(target_node))
            actual_box = box_payload(region_box(region))
        else:
            expected_box = box_payload(region_box(region))
            actual_box = box_payload(node_box(target_node))
    else:
        expected_box = box_payload(region_box(region))
        actual_box = box_payload(region_box(region))

    category = region.priority_category
    priority_tier = region.priority_tier
    if target_node is not None and all(value is not None for value in delta.values()):
        node_category = issue_category_for_node(
            target_node,
            {key: int(value or 0) for key, value in delta.items()},
            {key: int(value or 0) for key, value in residual_delta.items()},
        )
        if node_category is not None and category_tier(node_category) < priority_tier:
            category = node_category
            priority_tier = category_tier(node_category)

    diff_count, diff_bbox = diff_pixel_evidence(region, mask)
    diagnosis, suggested_fix = visual_issue_text(region, target_name, resolution_status, static_agreement)
    issue = UIIssue(
        issue_id=f"I-{issue_index:03d}",
        issue_type="visual_diff",
        category=category,
        priority_tier=priority_tier,
        target_node_id=target_id,
        target_name=target_name,
        node_kind=target_kind,
        expected_box=expected_box,
        actual_box=actual_box,
        delta=delta,
        parent_delta=parent_delta,
        residual_delta=residual_delta,
        severity_score=region.severity_score,
        confidence_score=visual_issue_confidence(region, resolution_status, implementation_links),
        diagnosis=diagnosis,
        suggested_fix=suggested_fix,
        evidence={
            "visual_candidate": candidate_simple_payload(region, mask),
            "linked_expected_nodes": [node_link_payload(node, score) for node, score in expected_links],
            "linked_actual_nodes": [node_link_payload(node, score) for node, score in actual_links],
            "linked_implementation_evidence": [
                evidence_link_payload(evidence, score)
                for evidence, score in implementation_links
            ],
            "node_match_id": target_match.match_id if target_match else None,
            "node_actual_box": box_payload(node_box(target_match.actual_node)) if target_match else None,
            "node_expected_box": box_payload(node_box(target_match.expected_node)) if target_match else None,
            "evidence_resolution": resolution_status,
            "screenshot_is_ground_truth": True,
            "static_evidence_cannot_suppress": static_agreement,
            "pixel_diff_is_evidence_only": False,
            "diff_pixel_count": diff_count,
            "diff_pixel_bbox": diff_bbox,
        },
        deferred=priority_tier >= 7,
        source_method="visual-first",
    )

    unresolved = None
    if resolution_status in {
        "visual_only_unresolved",
        "resolved_to_container_or_metadata",
        "screenshot_parser_detail_candidate",
    }:
        unresolved = {
            **candidate_simple_payload(region, mask),
            "reason": (
                "no external node/code evidence attached"
                if resolution_status == "visual_only_unresolved"
                else "screenshot-parser detail only; no external node/code evidence attached"
                if resolution_status == "screenshot_parser_detail_candidate"
                else "only broad container or metadata evidence attached; no leaf detail node confirmed"
            ),
            "resolution_status": resolution_status,
            "linked_expected_node_ids": [node.node_id for node, _ in expected_links],
            "linked_actual_node_ids": [node.node_id for node, _ in actual_links],
        }
    return issue, unresolved


def metadata_only_from_issue(issue: UIIssue) -> dict[str, object]:
    payload = issue_payload(issue)
    payload["metadata_only"] = True
    payload["reason"] = "node/code evidence has no visible screenshot candidate overlap"
    return payload


def resolve_visual_issues(
    visual_candidates: list[Region],
    mask: np.ndarray,
    expected_nodes: list[UINode],
    actual_nodes: list[UINode],
    node_matches: list[NodeMatch],
    node_metadata_issues: list[UIIssue],
    implementation_evidence: list[ImplementationEvidence],
) -> tuple[list[UIIssue], list[UIIssue], list[UIIssue], list[dict[str, object]], list[dict[str, object]]]:
    issues: list[UIIssue] = []
    actionable: list[UIIssue] = []
    deferred: list[UIIssue] = []
    unresolved_visual_candidates: list[dict[str, object]] = []
    metadata_only_findings: list[dict[str, object]] = []
    linked_evidence_ids: set[str] = set()

    for issue_index, region in enumerate(visual_candidates, start=1):
        expected_links = linked_nodes_for_region(region, expected_nodes)
        actual_links = linked_nodes_for_region(region, actual_nodes)
        linked_node_ids = {
            node.node_id
            for node, _ in [*expected_links, *actual_links]
        }
        implementation_links = linked_implementation_evidence_for_region(
            region,
            implementation_evidence,
            linked_node_ids,
        )
        linked_evidence_ids.update(evidence.evidence_id for evidence, _ in implementation_links)
        issue, unresolved = build_visual_issue(
            region,
            issue_index,
            mask,
            expected_links,
            actual_links,
            implementation_links,
            node_matches,
        )
        issues.append(issue)
        if issue.deferred:
            deferred.append(issue)
        else:
            actionable.append(issue)
        if unresolved is not None:
            unresolved_visual_candidates.append(unresolved)

    for metadata_issue in node_metadata_issues:
        if issue_overlaps_any_visual_candidate(metadata_issue, visual_candidates):
            continue
        metadata_only_findings.append(metadata_only_from_issue(metadata_issue))

    for evidence in implementation_evidence:
        if evidence.evidence_id in linked_evidence_ids:
            continue
        metadata_only_findings.append(
            {
                "metadata_only": True,
                "reason": "implementation evidence has no visible screenshot candidate overlap",
                "implementation_evidence": implementation_evidence_payload(evidence),
            }
        )

    actionable.sort(key=lambda issue: (issue.priority_tier, -issue.severity_score, issue.target_name))
    deferred.sort(key=lambda issue: (issue.priority_tier, -issue.severity_score, issue.target_name))
    issues = [*actionable, *deferred]
    for report_id, issue in enumerate(issues, start=1):
        issue.report_id = report_id
    return issues, actionable, deferred, unresolved_visual_candidates, metadata_only_findings


def issue_payload(issue: UIIssue) -> dict[str, object]:
    return {
        "issue_id": issue.issue_id,
        "report_id": issue.report_id,
        "issue_type": issue.issue_type,
        "target": {
            "id": issue.target_node_id,
            "name": issue.target_name,
            "kind": issue.node_kind,
            "box_expected": issue.expected_box,
            "box_actual": issue.actual_box,
        },
        "category": issue.category,
        "priority_tier": issue.priority_tier,
        "severity_score": issue.severity_score,
        "confidence": {
            "score": issue.confidence_score,
            "level": "high" if issue.confidence_score >= 0.72 else "medium" if issue.confidence_score >= 0.5 else "low",
        },
        "delta": issue.delta,
        "parent_delta": issue.parent_delta,
        "residual_delta": issue.residual_delta,
        "diagnosis": issue.diagnosis,
        "suggested_fix": issue.suggested_fix,
        "evidence": issue.evidence,
        "suppressed_children": issue.suppressed_children,
        "deferred": issue.deferred,
        "source_method": issue.source_method,
    }


def issue_to_region(issue: UIIssue, region_id: int) -> Region:
    box = issue.actual_box or issue.expected_box or {"x": 0, "y": 0, "width": 1, "height": 1}
    region = Region(
        region_id=region_id,
        x=int(box["x"]),
        y=int(box["y"]),
        width=max(1, int(box["width"])),
        height=max(1, int(box["height"])),
        area=max(1, int(box["width"]) * int(box["height"])),
        mean_delta=0.0,
        max_delta=0.0,
        category_hint=issue.category,
        level=2 if issue.node_kind in {"container", "background"} else 3,
        priority=issue.severity_score,
        display_depth=3 if issue.priority_tier <= 3 else 5,
        report_id=issue.report_id,
        element_kind=f"{issue.node_kind} node",
        severity_score=issue.severity_score,
        confidence_score=issue.confidence_score,
        confidence_level="high" if issue.confidence_score >= 0.72 else "medium" if issue.confidence_score >= 0.5 else "low",
        priority_category=issue.category,
        priority_tier=issue.priority_tier,
        report_group=issue.issue_id,
    )
    return region


def match_payload(match: NodeMatch) -> dict[str, object]:
    return {
        "id": match.match_id,
        "status": match.status,
        "cost": match.cost,
        "expected_node_id": match.expected_node.node_id if match.expected_node else None,
        "actual_node_id": match.actual_node.node_id if match.actual_node else None,
        "delta": match.delta,
        "parent_delta": match.parent_delta,
        "residual_delta": match.residual_delta,
        "local_box": box_payload(match.local_box),
        "local_score": match.local_score,
    }


def hierarchy_policy_text(
    hierarchy_depth: int | None,
    report_mode: str | None,
    effective_depth: int | None,
    node_mode: str = "auto",
) -> str:
    if effective_depth is None:
        if node_mode != "pixel":
            return (
                "Compatibility marker regions stay top-down, while visual_candidates "
                "also retain eligible raw detail regions that were suppressed by a parent marker."
            )
        return (
            "Report page, edge, and parent-module differences before child elements. "
            "Suppress child regions when a parent layout/spacing/background/edge issue explains them."
        )
    source = f"report-mode {report_mode!r}" if hierarchy_depth is None and report_mode else "hierarchy-depth"
    if node_mode != "pixel":
        return (
            f"Report markers use hierarchy-depth {effective_depth} from {source} for compatibility. "
            "visual_candidates remain screenshot-first and keep eligible child detail regions for evidence resolution."
        )
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
    node_mode: str = "auto",
    expected_nodes: list[UINode] | None = None,
    actual_nodes: list[UINode] | None = None,
    node_matches: list[NodeMatch] | None = None,
    issues: list[UIIssue] | None = None,
    actionable_issues: list[UIIssue] | None = None,
    deferred_visual_issues: list[UIIssue] | None = None,
    raw_pixel_regions: list[Region] | None = None,
    visual_candidates: list[Region] | None = None,
    resolved_issues: list[UIIssue] | None = None,
    unresolved_visual_candidates: list[dict[str, object]] | None = None,
    metadata_only_findings: list[dict[str, object]] | None = None,
    implementation_evidence: list[ImplementationEvidence] | None = None,
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
    issue_by_id = {issue.issue_id: issue for issue in (issues or [])}

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
            "issue": issue_payload(issue_by_id[region.report_group])
            if region.report_group in issue_by_id
            else None,
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
            "mode": "visual-first" if node_mode != "pixel" else "multi-signal",
            "signals": [
                "rgb pixel distance",
                "CIE Lab perceptual color distance",
                "local structural dissimilarity",
                "Sobel edge/stroke delta",
            ],
            "decision_policy": (
                "Screenshot diff produces primary visual candidates; Figma, runtime, and "
                "implementation metadata resolve targets and root-cause hints but cannot "
                "suppress visible screenshot mismatches."
                if node_mode != "pixel"
                else "Legacy pixel-region hierarchy produces primary regions."
            ),
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
        "hierarchy_policy": hierarchy_policy_text(hierarchy_depth, report_mode, effective_depth, node_mode),
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
            "node_mode": node_mode,
            "signal_thresholds": signals.thresholds,
        },
        "visual_candidates": [
            region_payload(region)
            for region in (visual_candidates or [])
        ],
        "ui_nodes": {
            "expected": [node_payload(node) for node in (expected_nodes or [])],
            "actual": [node_payload(node) for node in (actual_nodes or [])],
            "schema": {
                "fields": [
                    "id",
                    "parent_id",
                    "name",
                    "kind",
                    "bbox",
                    "text",
                    "style",
                    "visible",
                    "confidence",
                    "source_method",
                    "children",
                ],
                "kinds": sorted(NODE_KINDS),
            },
        },
        "implementation_evidence": [
            implementation_evidence_payload(evidence)
            for evidence in (implementation_evidence or [])
        ],
        "node_matches": [match_payload(match) for match in (node_matches or [])],
        "issues": [issue_payload(issue) for issue in (issues or [])],
        "resolved_issues": [issue_payload(issue) for issue in (resolved_issues or issues or [])],
        "actionable_issues": [issue_payload(issue) for issue in (actionable_issues or [])],
        "deferred_visual_issues": [issue_payload(issue) for issue in (deferred_visual_issues or [])],
        "unresolved_visual_candidates": unresolved_visual_candidates or [],
        "metadata_only_findings": metadata_only_findings or [],
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
        "raw_regions": [region_payload(region) for region in (raw_pixel_regions or regions)],
        "raw_pixel_regions": [region_payload(region) for region in (raw_pixel_regions or [])],
    }
    (out_dir / "regions.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    effective_depth = effective_hierarchy_depth(args.hierarchy_depth, args.report_mode)
    actual_path = Path(args.actual).expanduser().resolve()
    expected_path = Path(args.expected).expanduser().resolve()
    expected_nodes_path = Path(args.expected_nodes).expanduser().resolve() if args.expected_nodes else None
    actual_nodes_path = Path(args.actual_nodes).expanduser().resolve() if args.actual_nodes else None
    implementation_evidence_path = (
        Path(args.implementation_evidence).expanduser().resolve()
        if args.implementation_evidence
        else None
    )
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
    raw_pixel_regions = make_regions(merged, signals, args.max_regions)
    raw_pixel_regions, pixel_reported_regions, pixel_suppressed_regions = apply_hierarchy(
        raw_pixel_regions,
        actual_image.size,
        effective_depth,
    )
    expected_nodes: list[UINode] = []
    actual_nodes: list[UINode] = []
    node_matches: list[NodeMatch] = []
    actionable_issues: list[UIIssue] = []
    deferred_visual_issues: list[UIIssue] = []
    issues: list[UIIssue] = []
    visual_candidates: list[Region] = []
    unresolved_visual_candidates: list[dict[str, object]] = []
    metadata_only_findings: list[dict[str, object]] = []
    implementation_evidence: list[ImplementationEvidence] = []

    if args.node_mode != "pixel":
        expected_nodes = load_ui_nodes(
            expected_nodes_path,
            actual_image.size,
            normalization,
            "expected-node-json",
        ) if expected_nodes_path else fallback_ui_nodes_from_image(
            expected_array,
            actual_image.size,
            "expected-screenshot-parser",
        )
        actual_nodes = load_ui_nodes(
            actual_nodes_path,
            actual_image.size,
            None,
            "actual-node-json",
        ) if actual_nodes_path else fallback_ui_nodes_from_image(
            actual_array,
            actual_image.size,
            "actual-screenshot-parser",
        )
        node_matches = match_ui_nodes(
            expected_nodes,
            actual_nodes,
            expected_array,
            actual_array,
            actual_image.size,
        )
        implementation_evidence = load_implementation_evidence(
            implementation_evidence_path,
            actual_image.size,
        )
        node_metadata_issues: list[UIIssue] = []
        if expected_nodes_path or actual_nodes_path:
            node_actionable, node_deferred = diagnose_node_issues(
                node_matches,
                signals,
                actual_image.size,
            )
            node_metadata_issues = [*node_actionable, *node_deferred]
        visual_candidates = visual_candidate_pool(
            raw_pixel_regions,
            pixel_reported_regions,
            actual_image.size,
            args.max_regions,
        )
        (
            issues,
            actionable_issues,
            deferred_visual_issues,
            unresolved_visual_candidates,
            metadata_only_findings,
        ) = resolve_visual_issues(
            visual_candidates,
            mask,
            expected_nodes,
            actual_nodes,
            node_matches,
            node_metadata_issues,
            implementation_evidence,
        )

    if args.node_mode == "pixel" or (args.node_mode == "auto" and not issues and len(expected_nodes) <= 1 and len(actual_nodes) <= 1):
        regions = raw_pixel_regions
        reported_regions = pixel_reported_regions
        suppressed_regions = pixel_suppressed_regions
        active_node_mode = "pixel"
    else:
        marker_issues = (actionable_issues if actionable_issues else deferred_visual_issues)[: args.max_regions]
        regions = [issue_to_region(issue, index) for index, issue in enumerate(marker_issues, start=1)]
        reported_regions = regions
        suppressed_regions = pixel_suppressed_regions
        active_node_mode = args.node_mode

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
    annotated_raw = draw_annotations(actual_image, raw_pixel_regions)
    annotated_raw_expected = draw_annotations(expected_image, raw_pixel_regions)
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
        node_mode=active_node_mode,
        expected_nodes=expected_nodes,
        actual_nodes=actual_nodes,
        node_matches=node_matches,
        issues=issues,
        actionable_issues=actionable_issues,
        deferred_visual_issues=deferred_visual_issues,
        raw_pixel_regions=raw_pixel_regions,
        visual_candidates=visual_candidates,
        resolved_issues=issues,
        unresolved_visual_candidates=unresolved_visual_candidates,
        metadata_only_findings=metadata_only_findings,
        implementation_evidence=implementation_evidence,
    )

    print(
        f"Wrote {len(reported_regions)} reported region(s), "
        f"{len(suppressed_regions)} suppressed region(s), "
        f"{len(raw_pixel_regions)} raw pixel region(s) to {out_dir}"
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
