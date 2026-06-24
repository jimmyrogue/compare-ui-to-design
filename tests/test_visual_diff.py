import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "compare-ui-to-design" / "scripts" / "visual_diff.py"


def run_diff(tmp_path, actual, expected, *extra_args):
    out_dir = tmp_path / "report"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--actual",
            str(actual),
            "--expected",
            str(expected),
            "--out-dir",
            str(out_dir),
            *extra_args,
        ],
        check=True,
    )
    return out_dir, json.loads((out_dir / "regions.json").read_text(encoding="utf-8"))


def run_pixel_diff(tmp_path, actual, expected, *extra_args):
    return run_diff(tmp_path, actual, expected, "--node-mode", "pixel", *extra_args)


def run_diff_process(tmp_path, actual, expected, *extra_args):
    out_dir = tmp_path / "report"
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--actual",
            str(actual),
            "--expected",
            str(expected),
            "--out-dir",
            str(out_dir),
            *extra_args,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def save_image(path, color=(255, 255, 255), size=(120, 90)):
    image = Image.new("RGB", size, color)
    image.save(path)
    return image


def save_nodes(path, nodes):
    path.write_text(json.dumps({"nodes": nodes}) + "\n", encoding="utf-8")
    return path


def resize_filter():
    try:
        return Image.Resampling.LANCZOS
    except AttributeError:
        return Image.LANCZOS


def test_node_json_normalizes_expected_boxes_and_reports_issue(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"
    expected_nodes_path = tmp_path / "expected_nodes.json"
    actual_nodes_path = tmp_path / "actual_nodes.json"

    save_image(expected_path, size=(100, 50))
    save_image(actual_path, size=(200, 100))
    save_nodes(
        expected_nodes_path,
        [{"id": "button", "name": "Primary Button", "kind": "control", "bbox": [10, 10, 30, 10]}],
    )
    save_nodes(
        actual_nodes_path,
        [{"id": "button-runtime", "name": "Primary Button", "kind": "control", "bbox": [24, 20, 60, 20]}],
    )

    _, payload = run_diff(
        tmp_path,
        actual_path,
        expected_path,
        "--expected-nodes",
        str(expected_nodes_path),
        "--actual-nodes",
        str(actual_nodes_path),
    )

    assert payload["diff_engine"]["mode"] == "node-first"
    assert payload["parameters"]["node_mode"] == "auto"
    expected_button = next(node for node in payload["ui_nodes"]["expected"] if node["id"] == "button")
    assert expected_button["bbox"] == {"x": 20, "y": 20, "width": 60, "height": 20}
    issue = payload["actionable_issues"][0]
    assert issue["target"]["id"] == "button"
    assert issue["category"] == "position / alignment"
    assert issue["delta"]["dx"] == 4
    assert issue["evidence"]["pixel_diff_is_evidence_only"] is True
    assert payload["reported_regions"][0]["issue"]["issue_id"] == issue["issue_id"]


def test_node_diff_reports_child_residual_instead_of_parent(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"
    expected_nodes_path = tmp_path / "expected_nodes.json"
    actual_nodes_path = tmp_path / "actual_nodes.json"

    save_image(expected_path, size=(200, 140))
    save_image(actual_path, size=(200, 140))
    save_nodes(
        expected_nodes_path,
        [
            {"id": "card", "name": "Card", "kind": "container", "bbox": [20, 20, 120, 80]},
            {"id": "badge", "parent_id": "card", "name": "Badge Icon", "kind": "icon", "bbox": [40, 44, 20, 20]},
        ],
    )
    save_nodes(
        actual_nodes_path,
        [
            {"id": "card-runtime", "name": "Card", "kind": "container", "bbox": [20, 20, 120, 80]},
            {"id": "badge-runtime", "parent_id": "card-runtime", "name": "Badge Icon", "kind": "icon", "bbox": [46, 44, 20, 20]},
        ],
    )

    _, payload = run_diff(
        tmp_path,
        actual_path,
        expected_path,
        "--expected-nodes",
        str(expected_nodes_path),
        "--actual-nodes",
        str(actual_nodes_path),
    )

    actionable_ids = [issue["target"]["id"] for issue in payload["actionable_issues"]]
    assert actionable_ids == ["badge"]
    issue = payload["actionable_issues"][0]
    assert issue["residual_delta"]["dx"] == 6
    assert issue["parent_delta"]["dx"] == 0


def test_node_diff_suppresses_children_when_parent_shift_explains_them(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"
    expected_nodes_path = tmp_path / "expected_nodes.json"
    actual_nodes_path = tmp_path / "actual_nodes.json"

    save_image(expected_path, size=(220, 160))
    save_image(actual_path, size=(220, 160))
    save_nodes(
        expected_nodes_path,
        [
            {"id": "card", "name": "Card", "kind": "container", "bbox": [30, 30, 120, 80]},
            {"id": "title", "parent_id": "card", "name": "Title", "kind": "text", "bbox": [48, 48, 60, 16], "text": "Title"},
            {"id": "icon", "parent_id": "card", "name": "Icon", "kind": "icon", "bbox": [48, 76, 20, 20]},
        ],
    )
    save_nodes(
        actual_nodes_path,
        [
            {"id": "card-runtime", "name": "Card", "kind": "container", "bbox": [38, 30, 120, 80]},
            {"id": "title-runtime", "parent_id": "card-runtime", "name": "Title", "kind": "text", "bbox": [56, 48, 60, 16], "text": "Title"},
            {"id": "icon-runtime", "parent_id": "card-runtime", "name": "Icon", "kind": "icon", "bbox": [56, 76, 20, 20]},
        ],
    )

    _, payload = run_diff(
        tmp_path,
        actual_path,
        expected_path,
        "--expected-nodes",
        str(expected_nodes_path),
        "--actual-nodes",
        str(actual_nodes_path),
    )

    assert [issue["target"]["id"] for issue in payload["actionable_issues"]] == ["card"]
    suppressed = payload["actionable_issues"][0]["suppressed_children"]
    assert {item["node"] for item in suppressed} == {"title", "icon"}


def test_node_diff_reports_missing_and_extra_nodes(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"
    expected_nodes_path = tmp_path / "expected_nodes.json"
    actual_nodes_path = tmp_path / "actual_nodes.json"

    save_image(expected_path, size=(240, 140))
    save_image(actual_path, size=(240, 140))
    save_nodes(
        expected_nodes_path,
        [{"id": "expected-only", "name": "Expected Only", "kind": "icon", "bbox": [24, 40, 20, 20]}],
    )
    save_nodes(
        actual_nodes_path,
        [{"id": "actual-only", "name": "Actual Only", "kind": "control", "bbox": [190, 80, 28, 28]}],
    )

    _, payload = run_diff(
        tmp_path,
        actual_path,
        expected_path,
        "--expected-nodes",
        str(expected_nodes_path),
        "--actual-nodes",
        str(actual_nodes_path),
    )

    issue_types = {issue["issue_type"] for issue in payload["actionable_issues"]}
    assert issue_types == {"missing", "extra"}
    categories = {issue["category"] for issue in payload["actionable_issues"]}
    assert categories == {"missing element", "extra element"}


def test_node_json_skips_invisible_nodes_and_descendants(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"
    expected_nodes_path = tmp_path / "expected_nodes.json"
    actual_nodes_path = tmp_path / "actual_nodes.json"

    save_image(expected_path, size=(160, 100))
    save_image(actual_path, size=(160, 100))
    save_nodes(
        expected_nodes_path,
        [
            {
                "id": "hidden-parent",
                "name": "Hidden Parent",
                "kind": "container",
                "bbox": [20, 20, 80, 40],
                "visible": False,
                "children": [
                    {"id": "hidden-child", "name": "Hidden Child", "kind": "icon", "bbox": [28, 28, 16, 16]},
                ],
            }
        ],
    )
    save_nodes(actual_nodes_path, [])

    _, payload = run_diff(
        tmp_path,
        actual_path,
        expected_path,
        "--expected-nodes",
        str(expected_nodes_path),
        "--actual-nodes",
        str(actual_nodes_path),
    )

    expected_ids = {node["id"] for node in payload["ui_nodes"]["expected"]}
    assert "hidden-parent" not in expected_ids
    assert "hidden-child" not in expected_ids
    assert payload["actionable_issues"] == []


def test_duplicate_node_ids_remap_children_to_unique_parent(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"
    expected_nodes_path = tmp_path / "expected_nodes.json"
    actual_nodes_path = tmp_path / "actual_nodes.json"

    save_image(expected_path, size=(180, 100))
    save_image(actual_path, size=(180, 100))
    save_nodes(
        expected_nodes_path,
        [
            {
                "name": "Row",
                "kind": "container",
                "bbox": [10, 10, 50, 40],
                "children": [{"name": "Badge", "kind": "icon", "bbox": [20, 20, 12, 12]}],
            },
            {
                "name": "Row",
                "kind": "container",
                "bbox": [80, 10, 50, 40],
                "children": [{"name": "Badge", "kind": "icon", "bbox": [90, 20, 12, 12]}],
            },
        ],
    )
    save_nodes(actual_nodes_path, [])

    _, payload = run_diff(
        tmp_path,
        actual_path,
        expected_path,
        "--expected-nodes",
        str(expected_nodes_path),
        "--actual-nodes",
        str(actual_nodes_path),
    )

    expected_by_id = {node["id"]: node for node in payload["ui_nodes"]["expected"]}
    assert expected_by_id["Badge"]["parent_id"] == "Row"
    assert expected_by_id["Badge-2"]["parent_id"] == "Row-2"
    assert "Badge-2" in expected_by_id["Row-2"]["children"]


def test_local_search_reports_visual_shift_inside_stable_node_box(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"
    expected_nodes_path = tmp_path / "expected_nodes.json"
    actual_nodes_path = tmp_path / "actual_nodes.json"

    expected = save_image(expected_path, size=(120, 90))
    actual = save_image(actual_path, size=(120, 90))
    ImageDraw.Draw(expected).rectangle((30, 30, 42, 42), fill=(20, 20, 20))
    ImageDraw.Draw(actual).rectangle((36, 30, 48, 42), fill=(20, 20, 20))
    expected.save(expected_path)
    actual.save(actual_path)
    save_nodes(
        expected_nodes_path,
        [{"id": "icon", "name": "Icon", "kind": "icon", "bbox": [26, 26, 22, 22]}],
    )
    save_nodes(
        actual_nodes_path,
        [{"id": "icon-runtime", "name": "Icon", "kind": "icon", "bbox": [26, 26, 22, 22]}],
    )

    _, payload = run_diff(
        tmp_path,
        actual_path,
        expected_path,
        "--expected-nodes",
        str(expected_nodes_path),
        "--actual-nodes",
        str(actual_nodes_path),
    )

    issue = payload["actionable_issues"][0]
    assert issue["target"]["id"] == "icon"
    assert issue["category"] == "position / alignment"
    assert issue["delta"]["dx"] == 6
    assert issue["target"]["box_actual"]["x"] == 32
    assert issue["evidence"]["node_actual_box"]["x"] == 26


def test_large_background_color_diff_is_deferred_visual_issue(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"

    save_image(expected_path, color=(236, 248, 240), size=(180, 120))
    save_image(actual_path, color=(210, 235, 225), size=(180, 120))

    _, payload = run_diff(tmp_path, actual_path, expected_path)

    assert payload["actionable_issues"] == []
    assert payload["deferred_visual_issues"]
    assert payload["deferred_visual_issues"][0]["category"] == "background color"
    assert payload["deferred_visual_issues"][0]["evidence"]["pixel_diff_is_evidence_only"] is True


def test_screenshot_fallback_reports_shifted_icon_node(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"

    expected = save_image(expected_path, size=(160, 120))
    actual = save_image(actual_path, size=(160, 120))
    ImageDraw.Draw(expected).rectangle((48, 44, 70, 66), fill=(20, 20, 20))
    ImageDraw.Draw(actual).rectangle((56, 44, 78, 66), fill=(20, 20, 20))
    expected.save(expected_path)
    actual.save(actual_path)

    _, payload = run_diff(tmp_path, actual_path, expected_path)

    assert payload["diff_engine"]["mode"] == "node-first"
    assert any(node["source_method"] == "expected-screenshot-parser" for node in payload["ui_nodes"]["expected"])
    assert any(issue["category"] == "position / alignment" for issue in payload["actionable_issues"])
    assert payload["raw_pixel_regions"]


def test_detects_color_spacing_and_icon_differences(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"

    expected = save_image(expected_path)
    actual = save_image(actual_path)

    expected_draw = ImageDraw.Draw(expected)
    actual_draw = ImageDraw.Draw(actual)

    expected_draw.rectangle((12, 12, 52, 28), fill=(230, 240, 255))
    actual_draw.rectangle((14, 12, 54, 28), fill=(220, 235, 255))

    expected_draw.rectangle((70, 14, 82, 26), fill=(20, 20, 20))
    actual_draw.rectangle((70, 14, 82, 26), fill=(255, 255, 255))

    expected_draw.line((10, 60, 110, 60), fill=(230, 230, 230), width=1)
    actual_draw.line((10, 62, 110, 62), fill=(230, 230, 230), width=1)

    expected.save(expected_path)
    actual.save(actual_path)

    out_dir, payload = run_pixel_diff(tmp_path, actual_path, expected_path)

    assert (out_dir / "annotated_actual.png").exists()
    assert (out_dir / "annotated_expected.png").exists()
    assert (out_dir / "evidence_overlay_actual.png").exists()
    assert (out_dir / "evidence_overlay_expected.png").exists()
    assert (out_dir / "diff_heatmap.png").exists()
    assert (out_dir / "diff_graymap.png").exists()
    assert (out_dir / "diff_color_delta.png").exists()
    assert (out_dir / "diff_structure.png").exists()
    assert (out_dir / "diff_edges.png").exists()
    assert (out_dir / "region_crops").exists()
    assert (out_dir / "annotated_raw_actual.png").exists()
    assert (out_dir / "annotated_raw_expected.png").exists()
    assert (out_dir / "annotated_depth_actual.png").exists()
    assert (out_dir / "annotated_depth_expected.png").exists()
    assert payload["artifacts"] == {
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
    assert len(payload["regions"]) >= 3
    assert payload["actual_size"] == {"width": 120, "height": 90}
    assert [region["id"] for region in payload["regions"]] == list(
        range(1, len(payload["regions"]) + 1)
    )
    assert all({"x", "y", "width", "height", "mean_delta", "max_delta"} <= set(region) for region in payload["regions"])
    assert "UI/UX structure" in payload["audit_focus"]
    assert "proportionally fit" in payload["normalization_policy"]
    assert "copy-only text differences" in payload["ignored_by_default"]
    assert all("content" not in region["category_hint"].lower() for region in payload["regions"])
    assert all("data" not in region["category_hint"].lower() for region in payload["regions"])
    assert all("visual_evidence" in region for region in payload["reported_regions"])
    assert payload["diff_engine"]["mode"] == "multi-signal"
    assert "CIE Lab perceptual color distance" in payload["diff_engine"]["signals"]
    assert payload["diff_engine"]["priority_order"] == [
        "1 size / layout dimensions",
        "2 position / alignment",
        "3 relative relationship / spacing",
        "4 image / icon consistency",
        "5 font metrics / typography",
        "6 foreground color",
        "7 background color",
        "8 gradient",
        "9 shadow / effect",
    ]
    assert "structure_dissimilarity" in payload["parameters"]["signal_thresholds"]
    assert all("element_kind" in region for region in payload["reported_regions"])
    assert all("severity_score" in region for region in payload["reported_regions"])
    assert all("priority_tier" in region for region in payload["reported_regions"])
    assert all("priority_category" in region for region in payload["reported_regions"])
    assert all("confidence" in region for region in payload["reported_regions"])
    assert all("diff_signals" in region for region in payload["reported_regions"])
    assert all(
        region["visual_evidence"]["region_crops"] is not None
        for region in payload["reported_regions"]
    )
    for region in payload["reported_regions"]:
        for path in region["visual_evidence"]["region_crops"].values():
            if isinstance(path, str):
                assert Path(path).exists()
    assert payload["parameters"]["hierarchy_depth"] is None
    assert all("display_depth" in region for region in payload["regions"])
    assert all(1 <= region["display_depth"] <= 9 for region in payload["regions"])


def test_actual_and_expected_annotations_use_matching_coordinates(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"

    expected = save_image(expected_path)
    actual = save_image(actual_path)
    ImageDraw.Draw(expected).rectangle((20, 20, 60, 48), fill=(230, 240, 255))
    ImageDraw.Draw(actual).rectangle((24, 20, 64, 48), fill=(220, 235, 255))
    expected.save(expected_path)
    actual.save(actual_path)

    out_dir, payload = run_pixel_diff(tmp_path, actual_path, expected_path)
    annotated_actual = Image.open(out_dir / "annotated_actual.png").convert("RGB")
    annotated_expected = Image.open(out_dir / "annotated_expected.png").convert("RGB")

    assert payload["reported_regions"]
    for region in payload["reported_regions"]:
        marker_pixel = (region["x"], region["y"])
        assert annotated_actual.getpixel(marker_pixel) == (255, 36, 36)
        assert annotated_expected.getpixel(marker_pixel) == (255, 36, 36)
        assert region["visual_evidence"]["same_coordinate_on_expected"] is True
        assert region["visual_evidence"]["coordinate_space"] == "actual_and_normalized_expected"
        assert region["visual_evidence"]["diff_pixel_count"] > 0
        assert region["visual_evidence"]["diff_pixel_bbox"] is not None


def test_text_like_pixel_changes_are_not_classified_as_content(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"

    expected = save_image(expected_path, size=(140, 60))
    actual = save_image(actual_path, size=(140, 60))
    expected_draw = ImageDraw.Draw(expected)
    actual_draw = ImageDraw.Draw(actual)

    expected_draw.rectangle((20, 20, 100, 24), fill=(30, 30, 30))
    expected_draw.rectangle((20, 30, 82, 34), fill=(30, 30, 30))
    actual_draw.rectangle((22, 20, 102, 24), fill=(30, 30, 30))
    actual_draw.rectangle((22, 30, 84, 34), fill=(30, 30, 30))

    expected.save(expected_path)
    actual.save(actual_path)

    _, payload = run_pixel_diff(tmp_path, actual_path, expected_path, "--min-area", "4")

    assert payload["regions"]
    assert all("content" not in region["category_hint"].lower() for region in payload["regions"])
    assert all("data" not in region["category_hint"].lower() for region in payload["regions"])
    assert all(
        any(
            token in region["category_hint"].lower()
            for token in ("typography", "icon", "image", "layout", "border", "ui", "visual")
        )
        for region in payload["regions"]
    )


def test_parent_module_shift_suppresses_child_regions(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"

    expected = save_image(expected_path, size=(220, 160))
    actual = save_image(actual_path, size=(220, 160))
    expected_draw = ImageDraw.Draw(expected)
    actual_draw = ImageDraw.Draw(actual)

    expected_draw.rectangle((40, 30, 160, 110), outline=(30, 80, 180), width=3)
    actual_draw.rectangle((48, 30, 168, 110), outline=(30, 80, 180), width=3)
    expected_draw.rectangle((60, 52, 92, 66), fill=(30, 30, 30))
    actual_draw.rectangle((68, 52, 100, 66), fill=(30, 30, 30))
    expected_draw.rectangle((60, 78, 132, 90), fill=(210, 220, 240))
    actual_draw.rectangle((68, 78, 140, 90), fill=(210, 220, 240))

    expected.save(expected_path)
    actual.save(actual_path)

    _, payload = run_pixel_diff(tmp_path, actual_path, expected_path, "--min-area", "4")

    assert payload["audit_order"] == "top-down"
    assert payload["reported_regions"]
    assert payload["suppressed_regions"]
    assert len(payload["reported_regions"]) == 1
    assert len(payload["reported_regions"]) < len(payload["regions"])
    assert payload["reported_regions"][0]["level"] <= 2
    assert len(payload["reported_regions"][0]["source_region_ids"]) > 1
    assert all(region["suppressed_by"] is not None for region in payload["suppressed_regions"])
    reported = payload["reported_regions"][0]
    assert reported["suppressed_child_count"] == len(payload["suppressed_regions"])
    assert "not as a false positive" in " ".join(reported["review_guidance"])
    assert "suppressed child diff" in reported["finding_summary"]
    assert reported["visual_evidence"]["uses_suppressed_children"] is True
    assert reported["visual_evidence"]["diff_pixel_count"] > 0

    annotated = np.asarray(Image.open(tmp_path / "report" / "annotated_actual.png").convert("RGB"))
    overlay = np.asarray(Image.open(tmp_path / "report" / "evidence_overlay_actual.png").convert("RGB"))
    assert np.count_nonzero(overlay != annotated) > 0


def test_edge_safe_area_difference_is_reported_first(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"

    expected = save_image(expected_path, size=(160, 120), color=(250, 250, 250))
    actual = save_image(actual_path, size=(160, 120), color=(250, 250, 250))
    expected_draw = ImageDraw.Draw(expected)
    actual_draw = ImageDraw.Draw(actual)

    expected_draw.rectangle((0, 0, 159, 18), fill=(232, 240, 255))
    actual_draw.rectangle((0, 0, 159, 18), fill=(248, 248, 248))
    expected_draw.rectangle((90, 70, 104, 84), fill=(20, 20, 20))
    actual_draw.rectangle((90, 70, 104, 84), fill=(255, 255, 255))

    expected.save(expected_path)
    actual.save(actual_path)

    _, payload = run_pixel_diff(tmp_path, actual_path, expected_path)

    first = payload["reported_regions"][0]
    assert first["level"] == 0
    assert first["y"] == 0
    assert "edge" in first["category_hint"].lower() or "safe-area" in first["category_hint"].lower()
    assert "top" in first["edge_evidence"]["touches"]
    assert "screen-edge spacing" in " ".join(first["review_guidance"])
    assert first["visual_evidence"]["diff_pixel_bbox"]["y"] == 0


def test_child_difference_is_reported_when_parent_matches(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"

    expected = save_image(expected_path, size=(180, 120))
    actual = save_image(actual_path, size=(180, 120))
    expected_draw = ImageDraw.Draw(expected)
    actual_draw = ImageDraw.Draw(actual)

    expected_draw.rectangle((24, 24, 156, 96), fill=(238, 242, 248))
    actual_draw.rectangle((24, 24, 156, 96), fill=(238, 242, 248))
    expected_draw.rectangle((44, 44, 62, 62), fill=(20, 20, 20))
    actual_draw.rectangle((44, 44, 62, 62), fill=(238, 242, 248))

    expected.save(expected_path)
    actual.save(actual_path)

    _, payload = run_pixel_diff(tmp_path, actual_path, expected_path)

    assert len(payload["reported_regions"]) == 1
    assert payload["suppressed_regions"] == []
    assert payload["reported_regions"][0]["level"] >= 2
    assert "content" not in payload["reported_regions"][0]["category_hint"].lower()


def test_filters_isolated_noise(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"

    expected = save_image(expected_path, size=(60, 40))
    actual = save_image(actual_path, size=(60, 40))
    actual.putpixel((5, 5), (0, 0, 0))
    actual.putpixel((42, 20), (0, 0, 0))
    actual.save(actual_path)

    _, payload = run_pixel_diff(tmp_path, actual_path, expected_path)

    assert payload["regions"] == []


def test_low_contrast_color_delta_is_detected_below_rgb_threshold(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"

    expected = save_image(expected_path, size=(120, 80), color=(255, 255, 255))
    actual = save_image(actual_path, size=(120, 80), color=(255, 255, 255))
    ImageDraw.Draw(expected).rectangle((20, 18, 100, 58), fill=(240, 240, 240))
    ImageDraw.Draw(actual).rectangle((20, 18, 100, 58), fill=(246, 246, 246))
    expected.save(expected_path)
    actual.save(actual_path)

    _, payload = run_pixel_diff(tmp_path, actual_path, expected_path)

    assert payload["regions"]
    assert all(region["mean_delta"] < payload["parameters"]["threshold"] for region in payload["regions"])
    assert any(region["dominant_signal"] == "color" for region in payload["regions"])
    assert any(
        region["diff_signals"]["counts"]["color"] > 0
        and region["element_kind"] == "background/color fill"
        and region["priority_category"] == "background color"
        and region["priority_tier"] == 7
        for region in payload["reported_regions"]
    )


def test_priority_ranking_prefers_geometry_over_background_color(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"

    expected = save_image(expected_path, size=(220, 150), color=(240, 240, 240))
    actual = save_image(actual_path, size=(220, 150), color=(246, 246, 246))
    expected_draw = ImageDraw.Draw(expected)
    actual_draw = ImageDraw.Draw(actual)

    expected_draw.rectangle((40, 44, 104, 88), fill=(30, 210, 120))
    actual_draw.rectangle((52, 44, 116, 88), fill=(30, 210, 120))
    expected_draw.rectangle((132, 48, 156, 72), fill=(20, 20, 20))
    actual_draw.rectangle((132, 48, 156, 72), fill=(250, 250, 250))
    expected.save(expected_path)
    actual.save(actual_path)

    _, payload = run_pixel_diff(tmp_path, actual_path, expected_path)

    reported = payload["reported_regions"]
    assert reported
    assert reported[0]["priority_tier"] <= 4
    assert reported[0]["priority_category"] in {
        "size / layout dimensions",
        "position / alignment",
        "relative relationship / spacing",
        "image / icon consistency",
    }
    background_regions = [
        region for region in reported if region["priority_category"] == "background color"
    ]
    assert background_regions
    assert all(region["priority_tier"] == 7 for region in background_regions)


def test_scales_expected_to_actual_when_dimensions_differ(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"

    expected = save_image(expected_path, size=(60, 40))
    ImageDraw.Draw(expected).rectangle((12, 8, 36, 24), fill=(20, 20, 20))
    expected.save(expected_path)
    expected.resize((120, 80), resize_filter()).save(actual_path)

    out_dir, payload = run_pixel_diff(tmp_path, actual_path, expected_path)

    assert payload["regions"] == []
    assert payload["actual_size"] == {"width": 120, "height": 80}
    assert payload["expected_size"] == {"width": 60, "height": 40}
    assert payload["expected_normalized_size"] == {"width": 120, "height": 80}
    assert payload["comparison_size"] == {"width": 120, "height": 80}
    assert payload["normalization"]["mode"] == "proportional-fit"
    assert payload["normalization"]["scale"] == 2.0
    assert payload["normalization"]["cropped"] is False
    assert payload["normalization"]["padded"] is False
    assert Image.open(out_dir / "annotated_expected.png").size == (120, 80)
    assert Image.open(out_dir / "evidence_overlay_expected.png").size == (120, 80)


def test_proportional_fit_pads_expected_without_cropping(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"

    expected = save_image(expected_path, size=(60, 20))
    ImageDraw.Draw(expected).rectangle((10, 5, 30, 14), fill=(20, 20, 20))
    expected.save(expected_path)

    actual = Image.new("RGB", (120, 80), (255, 255, 255))
    actual.paste(expected.resize((120, 40), resize_filter()), (0, 20))
    actual.save(actual_path)

    _, payload = run_pixel_diff(tmp_path, actual_path, expected_path)

    assert payload["regions"] == []
    assert payload["normalization"]["mode"] == "proportional-fit"
    assert payload["normalization"]["cropped"] is False
    assert payload["normalization"]["padded"] is True
    assert payload["normalization"]["offset"] == {"x": 0, "y": 20}
    assert payload["normalization"]["scaled_expected_content_size"] == {"width": 120, "height": 40}


def test_rejects_invalid_hierarchy_depth(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"
    save_image(expected_path)
    save_image(actual_path)

    too_shallow = run_diff_process(tmp_path, actual_path, expected_path, "--hierarchy-depth", "0")
    too_deep = run_diff_process(tmp_path, actual_path, expected_path, "--hierarchy-depth", "10")

    assert too_shallow.returncode != 0
    assert too_deep.returncode != 0
    assert "hierarchy-depth must be between 1 and 9" in too_shallow.stderr
    assert "hierarchy-depth must be between 1 and 9" in too_deep.stderr


def test_hierarchy_depth_progressively_includes_deeper_regions(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"

    expected = save_image(expected_path, color=(250, 250, 250), size=(180, 120))
    actual = save_image(actual_path, color=(250, 250, 250), size=(180, 120))
    expected_draw = ImageDraw.Draw(expected)
    actual_draw = ImageDraw.Draw(actual)

    expected_draw.rectangle((0, 0, 179, 18), fill=(232, 240, 255))
    actual_draw.rectangle((0, 0, 179, 18), fill=(248, 248, 248))
    expected_draw.rectangle((40, 42, 132, 86), fill=(230, 245, 235), outline=(120, 200, 150), width=2)
    actual_draw.rectangle((40, 42, 132, 86), fill=(230, 245, 235), outline=(120, 200, 150), width=2)
    expected_draw.rectangle((54, 54, 70, 70), fill=(20, 20, 20))
    actual_draw.rectangle((54, 54, 70, 70), fill=(230, 245, 235))

    expected.save(expected_path)
    actual.save(actual_path)

    _, shallow_payload = run_pixel_diff(tmp_path / "shallow", actual_path, expected_path, "--hierarchy-depth", "1")
    _, mid_payload = run_pixel_diff(tmp_path / "mid", actual_path, expected_path, "--hierarchy-depth", "5")
    _, deep_payload = run_pixel_diff(tmp_path / "deep", actual_path, expected_path, "--hierarchy-depth", "9")

    assert shallow_payload["parameters"]["hierarchy_depth"] == 1
    assert all(region["display_depth"] <= 1 for region in shallow_payload["reported_regions"])
    assert len(mid_payload["reported_regions"]) > len(shallow_payload["reported_regions"])
    assert any(region["display_depth"] == 5 for region in mid_payload["reported_regions"])
    assert len(deep_payload["reported_regions"]) >= len(mid_payload["reported_regions"])
    assert all(region["display_depth"] <= 9 for region in deep_payload["reported_regions"])

    for key in (
        "annotated_raw_actual",
        "annotated_raw_expected",
        "annotated_depth_actual",
        "annotated_depth_expected",
    ):
        assert key in mid_payload["artifacts"]
        assert Path(mid_payload["artifacts"][key]).exists()


def test_depth_mode_keeps_detail_regions_inside_full_screen_edge_parent(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"

    expected = save_image(expected_path, color=(250, 250, 250), size=(120, 80))
    actual = save_image(actual_path, color=(250, 250, 250), size=(120, 100))
    expected_draw = ImageDraw.Draw(expected)
    actual_draw = ImageDraw.Draw(actual)

    expected_draw.rectangle((48, 34, 64, 50), fill=(20, 20, 20))
    expected.save(expected_path)

    actual_draw.rectangle((0, 0, 119, 9), fill=(210, 230, 255))
    actual_draw.rectangle((0, 90, 119, 99), fill=(210, 230, 255))
    actual_draw.rectangle((48, 44, 64, 60), fill=(250, 250, 250))
    actual.save(actual_path)

    _, payload = run_pixel_diff(tmp_path, actual_path, expected_path, "--hierarchy-depth", "5")

    assert len(payload["reported_regions"]) > 1
    assert any(region["priority_tier"] == 1 for region in payload["reported_regions"])
    assert any(
        region["display_depth"] == 5
        and region["priority_tier"] == 4
        and region["x"] <= 64
        and region["x"] + region["width"] >= 48
        and region["y"] <= 60
        and region["y"] + region["height"] >= 44
        for region in payload["reported_regions"]
    )


def test_hierarchy_depth_five_includes_sparse_icon_edge_regions(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"

    expected = save_image(expected_path, color=(255, 255, 255), size=(1000, 1000))
    expected_draw = ImageDraw.Draw(expected)
    expected_draw.line((400, 500, 560, 500), fill=(0, 0, 0), width=2)
    expected_draw.line((560, 500, 540, 485), fill=(0, 0, 0), width=2)
    expected_draw.line((560, 500, 540, 515), fill=(0, 0, 0), width=2)
    expected.save(expected_path)
    save_image(actual_path, color=(255, 255, 255), size=(1000, 1000))

    _, payload = run_pixel_diff(tmp_path, actual_path, expected_path, "--hierarchy-depth", "5")

    assert any(
        region["display_depth"] == 5
        and region["priority_tier"] == 4
        and region["priority_category"] == "image / icon consistency"
        and region["category_hint"] == "typography/icon edge or alignment"
        for region in payload["reported_regions"]
    )


def test_hierarchy_policy_describes_depth_mode(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"

    expected = save_image(expected_path)
    actual = save_image(actual_path)
    ImageDraw.Draw(expected).rectangle((20, 20, 60, 48), fill=(20, 20, 20))
    expected.save(expected_path)
    actual.save(actual_path)

    _, payload = run_pixel_diff(tmp_path, actual_path, expected_path, "--hierarchy-depth", "5")

    assert "hierarchy-depth" in payload["hierarchy_policy"]
    assert "do not hide eligible child detail regions" in payload["hierarchy_policy"]
    assert "Suppress child regions" not in payload["hierarchy_policy"]


def test_report_mode_detail_selects_depth_five(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"

    expected = save_image(expected_path, color=(255, 255, 255), size=(1000, 1000))
    expected_draw = ImageDraw.Draw(expected)
    expected_draw.line((400, 500, 560, 500), fill=(0, 0, 0), width=2)
    expected_draw.line((560, 500, 540, 485), fill=(0, 0, 0), width=2)
    expected_draw.line((560, 500, 540, 515), fill=(0, 0, 0), width=2)
    expected.save(expected_path)
    save_image(actual_path, color=(255, 255, 255), size=(1000, 1000))

    _, payload = run_pixel_diff(tmp_path, actual_path, expected_path, "--report-mode", "detail")

    assert payload["parameters"]["report_mode"] == "detail"
    assert payload["parameters"]["effective_hierarchy_depth"] == 5
    assert any(
        region["display_depth"] == 5
        and region["priority_category"] == "image / icon consistency"
        for region in payload["reported_regions"]
    )


def test_detail_mode_splits_internal_objects_from_broad_parent_regions(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"

    expected = save_image(expected_path, color=(250, 250, 250), size=(560, 360))
    actual = save_image(actual_path, color=(250, 250, 250), size=(560, 360))
    expected_draw = ImageDraw.Draw(expected)
    actual_draw = ImageDraw.Draw(actual)

    expected_draw.rectangle((60, 40, 520, 190), fill=(236, 247, 240), outline=(225, 235, 228), width=2)
    actual_draw.rectangle((60, 40, 520, 190), fill=(240, 250, 243), outline=(225, 235, 228), width=2)

    expected_draw.polygon(
        [(388, 58), (430, 78), (438, 128), (405, 168), (352, 146), (344, 92)],
        fill=(204, 235, 190),
        outline=(122, 150, 108),
    )
    expected_draw.ellipse((362, 82, 432, 152), outline=(84, 185, 132), width=7)
    expected_draw.line((382, 152, 420, 82), fill=(84, 185, 132), width=9)

    actual_draw.polygon(
        [(370, 54), (424, 76), (436, 136), (396, 174), (338, 148), (330, 86)],
        fill=(204, 235, 190),
        outline=(122, 150, 108),
    )
    actual_draw.ellipse((346, 82, 430, 164), outline=(84, 185, 132), width=7)
    actual_draw.line((370, 160, 416, 78), fill=(84, 185, 132), width=9)

    expected_draw.rectangle((70, 230, 510, 304), fill=(236, 247, 240), outline=(225, 235, 228), width=2)
    actual_draw.rectangle((70, 230, 510, 304), fill=(240, 250, 243), outline=(225, 235, 228), width=2)
    expected_draw.ellipse((438, 246, 482, 290), outline=(38, 210, 120), width=6)
    expected_draw.ellipse((451, 259, 469, 277), fill=(245, 255, 248))
    actual_draw.ellipse((430, 242, 486, 298), outline=(38, 210, 120), width=6)
    actual_draw.ellipse((446, 258, 470, 282), fill=(245, 255, 248))

    expected.save(expected_path)
    actual.save(actual_path)

    _, payload = run_pixel_diff(tmp_path, actual_path, expected_path, "--report-mode", "detail", "--min-area", "8")
    reported = payload["reported_regions"]

    assert any(
        region["display_depth"] == 5
        and region["priority_tier"] == 4
        and region["priority_category"] == "image / icon consistency"
        and 320 <= region["x"] <= 410
        and 45 <= region["y"] <= 95
        and region["width"] <= 150
        and region["height"] <= 140
        for region in reported
    )
    assert any(
        region["display_depth"] == 5
        and region["priority_tier"] == 4
        and 420 <= region["x"] <= 450
        and 235 <= region["y"] <= 255
        and region["width"] <= 80
        and region["height"] <= 80
        for region in reported
    )
    assert payload["focus_regions"]
    assert all(4 <= region["display_depth"] <= 5 for region in payload["focus_regions"])


def test_hierarchy_depth_overrides_report_mode_preset(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"

    expected = save_image(expected_path, color=(255, 255, 255), size=(1000, 1000))
    ImageDraw.Draw(expected).rectangle((300, 300, 500, 500), fill=(20, 20, 20))
    expected.save(expected_path)
    save_image(actual_path, color=(255, 255, 255), size=(1000, 1000))

    _, payload = run_pixel_diff(
        tmp_path,
        actual_path,
        expected_path,
        "--report-mode",
        "detail",
        "--hierarchy-depth",
        "1",
    )

    assert payload["parameters"]["report_mode"] == "detail"
    assert payload["parameters"]["hierarchy_depth"] == 1
    assert payload["parameters"]["effective_hierarchy_depth"] == 1
    assert all(region["display_depth"] <= 1 for region in payload["reported_regions"])


def test_depth_mode_exposes_structured_region_buckets(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"

    expected = save_image(expected_path, color=(250, 250, 250), size=(180, 120))
    actual = save_image(actual_path, color=(250, 250, 250), size=(180, 120))
    expected_draw = ImageDraw.Draw(expected)
    actual_draw = ImageDraw.Draw(actual)

    expected_draw.rectangle((0, 0, 179, 18), fill=(232, 240, 255))
    actual_draw.rectangle((0, 0, 179, 18), fill=(248, 248, 248))
    expected_draw.rectangle((54, 54, 70, 70), fill=(20, 20, 20))
    actual_draw.rectangle((54, 54, 70, 70), fill=(250, 250, 250))
    expected.save(expected_path)
    actual.save(actual_path)

    _, payload = run_pixel_diff(tmp_path, actual_path, expected_path, "--report-mode", "detail")

    assert [region["id"] for region in payload["depth_regions"]] == [
        region["id"] for region in payload["reported_regions"]
    ]
    assert [region["id"] for region in payload["focus_regions"]] == [
        region["id"]
        for region in payload["reported_regions"]
        if 4 <= region["display_depth"] <= 5
    ]
    assert all(region["display_depth"] <= 3 for region in payload["parent_regions"])
    assert all(4 <= region["display_depth"] <= 8 for region in payload["detail_regions"])
    assert [region["id"] for region in payload["raw_regions"]] == [
        region["id"] for region in payload["regions"]
    ]
