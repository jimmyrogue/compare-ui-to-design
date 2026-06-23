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


def save_image(path, color=(255, 255, 255), size=(120, 90)):
    image = Image.new("RGB", size, color)
    image.save(path)
    return image


def resize_filter():
    try:
        return Image.Resampling.LANCZOS
    except AttributeError:
        return Image.LANCZOS


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

    out_dir, payload = run_diff(tmp_path, actual_path, expected_path)

    assert (out_dir / "annotated_actual.png").exists()
    assert (out_dir / "annotated_expected.png").exists()
    assert (out_dir / "evidence_overlay_actual.png").exists()
    assert (out_dir / "evidence_overlay_expected.png").exists()
    assert (out_dir / "diff_heatmap.png").exists()
    assert (out_dir / "diff_graymap.png").exists()
    assert payload["artifacts"] == {
        "annotated_actual": str(out_dir / "annotated_actual.png"),
        "annotated_expected": str(out_dir / "annotated_expected.png"),
        "evidence_overlay_actual": str(out_dir / "evidence_overlay_actual.png"),
        "evidence_overlay_expected": str(out_dir / "evidence_overlay_expected.png"),
        "diff_heatmap": str(out_dir / "diff_heatmap.png"),
        "diff_graymap": str(out_dir / "diff_graymap.png"),
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


def test_actual_and_expected_annotations_use_matching_coordinates(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"

    expected = save_image(expected_path)
    actual = save_image(actual_path)
    ImageDraw.Draw(expected).rectangle((20, 20, 60, 48), fill=(230, 240, 255))
    ImageDraw.Draw(actual).rectangle((24, 20, 64, 48), fill=(220, 235, 255))
    expected.save(expected_path)
    actual.save(actual_path)

    out_dir, payload = run_diff(tmp_path, actual_path, expected_path)
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

    _, payload = run_diff(tmp_path, actual_path, expected_path, "--min-area", "4")

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

    _, payload = run_diff(tmp_path, actual_path, expected_path, "--min-area", "4")

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

    _, payload = run_diff(tmp_path, actual_path, expected_path)

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

    _, payload = run_diff(tmp_path, actual_path, expected_path)

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

    _, payload = run_diff(tmp_path, actual_path, expected_path)

    assert payload["regions"] == []


def test_scales_expected_to_actual_when_dimensions_differ(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"

    expected = save_image(expected_path, size=(60, 40))
    ImageDraw.Draw(expected).rectangle((12, 8, 36, 24), fill=(20, 20, 20))
    expected.save(expected_path)
    expected.resize((120, 80), resize_filter()).save(actual_path)

    out_dir, payload = run_diff(tmp_path, actual_path, expected_path)

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

    _, payload = run_diff(tmp_path, actual_path, expected_path)

    assert payload["regions"] == []
    assert payload["normalization"]["mode"] == "proportional-fit"
    assert payload["normalization"]["cropped"] is False
    assert payload["normalization"]["padded"] is True
    assert payload["normalization"]["offset"] == {"x": 0, "y": 20}
    assert payload["normalization"]["scaled_expected_content_size"] == {"width": 120, "height": 40}
