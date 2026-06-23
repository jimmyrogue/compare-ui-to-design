# compare-ui-to-design

An open-source Codex skill for auditing visual differences between a running UI and a design reference.

The skill helps compare web pages, simulator screenshots, real-device screenshots, Figma exports, and static design images. It marks visible differences on the actual screenshot and reports precise coordinates for layout, spacing, color, typography, icon, and content mismatches.

## What it includes

- `skills/compare-ui-to-design/SKILL.md`: Codex skill instructions.
- `skills/compare-ui-to-design/scripts/visual_diff.py`: deterministic image diff CLI.
- `skills/compare-ui-to-design/references/`: capture and audit guidance.
- `tests/`: synthetic tests for color, spacing, missing content, and noise filtering.

## Install the skill locally

Copy or symlink the skill folder into your Codex skills directory:

```bash
mkdir -p ~/.codex/skills
ln -s "$(pwd)/skills/compare-ui-to-design" ~/.codex/skills/compare-ui-to-design
```

Then invoke it in Codex:

```text
Use $compare-ui-to-design to compare this running UI screenshot with the Figma export and mark every visual difference.
```

## Use the visual diff CLI

Install dependencies:

```bash
python3 -m pip install -e ".[test]"
```

Run a comparison:

```bash
python skills/compare-ui-to-design/scripts/visual_diff.py \
  --actual actual.png \
  --expected expected.png \
  --out-dir report
```

Outputs:

- `report/annotated_actual.png`
- `report/diff_heatmap.png`
- `report/regions.json`

`regions.json` contains numbered regions with `x`, `y`, `width`, `height`, `area`, `mean_delta`, `max_delta`, and a category hint.

## Development

Validate the skill:

```bash
python3 path/to/skill-creator/scripts/quick_validate.py skills/compare-ui-to-design
```

Run tests:

```bash
python -m pytest
```

## License

MIT
