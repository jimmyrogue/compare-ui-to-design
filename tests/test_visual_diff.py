import json
import subprocess
import sys
from pathlib import Path

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
    assert (out_dir / "diff_heatmap.png").exists()
    assert len(payload["regions"]) >= 3
    assert payload["actual_size"] == {"width": 120, "height": 90}
    assert [region["id"] for region in payload["regions"]] == list(
        range(1, len(payload["regions"]) + 1)
    )
    assert all({"x", "y", "width", "height", "mean_delta", "max_delta"} <= set(region) for region in payload["regions"])
    assert "UI/UX structure" in payload["audit_focus"]
    assert "copy-only text differences" in payload["ignored_by_default"]
    assert all("content" not in region["category_hint"].lower() for region in payload["regions"])
    assert all("data" not in region["category_hint"].lower() for region in payload["regions"])


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


def test_rejects_mismatched_dimensions(tmp_path):
    expected_path = tmp_path / "expected.png"
    actual_path = tmp_path / "actual.png"
    save_image(expected_path, size=(60, 40))
    save_image(actual_path, size=(61, 40))

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--actual",
            str(actual_path),
            "--expected",
            str(expected_path),
            "--out-dir",
            str(tmp_path / "report"),
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "same pixel size" in result.stderr
