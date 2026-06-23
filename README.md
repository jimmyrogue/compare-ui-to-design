# compare-ui-to-design

[![Tests](https://github.com/jimmyrogue/compare-ui-to-design/actions/workflows/test.yml/badge.svg)](https://github.com/jimmyrogue/compare-ui-to-design/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Audit visual differences between a running UI and a design reference, then mark the exact regions that differ.

`compare-ui-to-design` is a Codex-compatible skill for comparing web pages, simulator screenshots, real-device screenshots, Figma exports, and static design images. It is audit-only by default: it identifies color, spacing, typography, layout, icon, and content mismatches without changing application code unless you explicitly ask for fixes.

## Skills

| Skill | When | What it does |
| :--- | :--- | :--- |
| [`compare-ui-to-design`](skills/compare-ui-to-design/SKILL.md) | Running UI does not match a Figma/design reference | Captures or accepts screenshots, runs visual diff tooling when possible, marks difference regions, and reports precise coordinates. |

Each skill uses the standard `skills/<name>/SKILL.md` layout supported by the `skills` installer.

## Install and Update

Most users should install globally so the skill is available in every project.

**Codex**

```bash
npx skills add jimmyrogue/compare-ui-to-design -a codex -g -y
```

Invoke it in Codex:

```text
Use $compare-ui-to-design to compare my running UI screenshot with the Figma export and mark every visual difference.
```

**Claude Code**

```bash
npx skills add jimmyrogue/compare-ui-to-design -a claude-code -g -y
```

Invoke it as the installed skill command in Claude Code, or ask Claude to use `compare-ui-to-design`.

**Other compatible agents**

```bash
npx skills add jimmyrogue/compare-ui-to-design -a antigravity -g -y
npx skills add jimmyrogue/compare-ui-to-design -a opencode -g -y
```

**Inspect before installing**

```bash
npx skills add jimmyrogue/compare-ui-to-design --list
```

**Update**

```bash
npx skills update -g -y
```

## Manual Install

Copy or symlink the skill folder into your local Codex skills directory:

```bash
mkdir -p ~/.codex/skills
ln -s "$(pwd)/skills/compare-ui-to-design" ~/.codex/skills/compare-ui-to-design
```

## Visual Diff CLI

The skill includes a deterministic helper script for comparing two same-sized screenshots:

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

## Project Layout

```text
.
├── skills/compare-ui-to-design/   # Installable skill
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── references/
│   └── scripts/visual_diff.py
├── scripts/check_skill.py          # Portable structure/frontmatter checker
├── tests/                          # Synthetic visual-diff tests
├── package.json                    # Skill package metadata
├── pyproject.toml                  # Python test/runtime dependencies
└── packaging.allowlist             # Release/package allowlist
```

## Development

Set up Python dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install ".[dev]"
```

Run all local checks:

```bash
make check PYTHON=.venv/bin/python
```

Useful targets:

```bash
make validate PYTHON=.venv/bin/python
make test PYTHON=.venv/bin/python
make skills-list
```

If you have Codex's `skill-creator` validator locally, you can also run:

```bash
.venv/bin/python /Users/jimmy/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  skills/compare-ui-to-design
```

## License

MIT
