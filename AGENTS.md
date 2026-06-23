# Repository Guidelines

## Project Structure & Module Organization

This repository packages the `compare-ui-to-design` agent skill and its visual diff helper.

- `skills/compare-ui-to-design/SKILL.md`: primary skill instructions and workflow.
- `skills/compare-ui-to-design/scripts/visual_diff.py`: deterministic screenshot comparison CLI.
- `skills/compare-ui-to-design/references/`: capture checklist and audit rubric used by agents.
- `skills/compare-ui-to-design/agents/openai.yaml`: OpenAI agent adapter metadata.
- `scripts/check_skill.py`: portable validation for skill layout and frontmatter.
- `tests/`: pytest coverage for visual diff behavior and generated artifacts.
- `package.json`, `pyproject.toml`, and `packaging.allowlist`: package, Python dependency, and release metadata.

## Build, Test, and Development Commands

Set up Python dependencies before changing code:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install ".[dev]"
```

Run the full local check suite:

```bash
make check PYTHON=.venv/bin/python
```

Useful focused commands:

- `make validate PYTHON=.venv/bin/python`: validates skill frontmatter and required files.
- `make test PYTHON=.venv/bin/python`: runs pytest.
- `make skills-list`: verifies installer discovery with `npx skills add . -a codex --list`.
- `npm run check`: npm equivalent of validate, test, and skill listing.

## Coding Style & Naming Conventions

Python code uses 4-space indentation, type hints, `pathlib.Path`, dataclasses where useful, and small pure helper functions. Keep CLI flags explicit and documented in `argparse`. Test files follow `test_*.py`; test functions should describe visible behavior, for example `test_edge_safe_area_difference_is_reported_first`.

Skill content should stay instructional and audit-focused. Use concise Markdown headings, fenced command examples, and repository-relative paths.

## Testing Guidelines

Tests use `pytest`, `Pillow`, and `numpy` with synthetic images. Add or update tests when changing normalization, region grouping, artifact names, JSON fields, or reporting order. The expected CI command is `make check PYTHON=python` on Python 3.11 and Node 22.

## Commit & Pull Request Guidelines

Recent commits use short, imperative subjects such as `Add paired evidence maps and design scaling` or `Revise README for agent-wide usage`. Keep the first line specific and under about 72 characters.

Pull requests should include a concise summary, the checks run, linked issues when applicable, and screenshots or generated report paths when visual output changes. Do not commit temporary report directories, virtual environments, caches, or generated `__pycache__` files.
