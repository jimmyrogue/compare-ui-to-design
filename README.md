# compare-ui-to-design

[![Tests](https://github.com/jimmyrogue/compare-ui-to-design/actions/workflows/test.yml/badge.svg)](https://github.com/jimmyrogue/compare-ui-to-design/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Audit UI/UX differences between a running interface and a design reference, then mark the exact regions that differ.

`compare-ui-to-design` is an agent-compatible skill for comparing web pages, simulator screenshots, real-device screenshots, Figma exports, and static design images. It is audit-only by default: it focuses on UI/UX implementation fidelity, including module position, size, border, color, background, gradient direction, spacing, margin, padding, typography metrics, icon/image size, and alignment.

It does not try to report every pixel or every copy/data mismatch. Text values, timestamps, counters, fetched data, and labels are treated as context unless they affect layout, typography metrics, visual state, or component size.

It also calls out screen-edge and safe-area differences, which are easy to miss, while ignoring device/system UI chrome such as phone status bars, tablet menu bars, browser chrome, home indicators, and navigation bars unless the design explicitly includes them.

## Skills

| Skill | When | What it does |
| :--- | :--- | :--- |
| [`compare-ui-to-design`](skills/compare-ui-to-design/SKILL.md) | Running UI does not visually match a Figma/design reference | Captures or accepts screenshots, runs visual diff tooling when possible, marks UI/UX difference regions, and reports precise coordinates. |

Each skill uses the standard `skills/<name>/SKILL.md` layout supported by the `skills` installer.

## Install and Update

Most users should install globally so the skill is available in every project.

**Codex**

```bash
npx skills add jimmyrogue/compare-ui-to-design -a codex -g -y
```

Invoke it in Codex:

```text
Use $compare-ui-to-design to compare my running UI screenshot with the Figma export and mark the UI/UX differences.
Focus on module layout, screen edges, safe areas, spacing, color, typography metrics, icons, images, and gradients. Ignore copy-only, live-data, and device/system UI differences unless they affect app-owned UI layout.
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

For agents that load skills from a local folder, copy or symlink `skills/compare-ui-to-design` into that agent's skill root. For Codex, the local skill root is usually `~/.codex/skills`:

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

`regions.json` contains numbered regions with `x`, `y`, `width`, `height`, `area`, `mean_delta`, `max_delta`, and a UI/UX category hint. Treat those hints as review aids; the final report should merge raw pixel regions into meaningful module-level UI findings.

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

If you have the official `skill-creator` validator locally, you can also run:

```bash
.venv/bin/python /Users/jimmy/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  skills/compare-ui-to-design
```

## License

MIT
