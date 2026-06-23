#!/usr/bin/env python3
"""Portable checks for this repository's skill layout."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md must start with YAML frontmatter")

    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError("SKILL.md frontmatter must end with ---")

    fields: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"invalid frontmatter line: {line!r}")
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields


def check_skill(skill_dir: Path) -> list[str]:
    errors: list[str] = []
    skill_md = skill_dir / "SKILL.md"

    if not skill_md.exists():
        return [f"{skill_dir}: missing SKILL.md"]

    text = skill_md.read_text(encoding="utf-8")
    try:
        fields = parse_frontmatter(text)
    except ValueError as exc:
        return [f"{skill_md}: {exc}"]

    expected_name = skill_dir.name
    actual_name = fields.get("name")
    description = fields.get("description", "")

    if actual_name != expected_name:
        errors.append(f"{skill_md}: name must be {expected_name!r}, got {actual_name!r}")
    if not description:
        errors.append(f"{skill_md}: description is required")
    if "TODO" in text:
        errors.append(f"{skill_md}: remove TODO placeholders")
    if len(description) < 80:
        errors.append(f"{skill_md}: description should explain triggers and use cases")

    if not (skill_dir / "agents" / "openai.yaml").exists():
        errors.append(f"{skill_dir}: missing agents/openai.yaml")
    if not (skill_dir / "scripts" / "visual_diff.py").exists():
        errors.append(f"{skill_dir}: missing scripts/visual_diff.py")
    if not (skill_dir / "references" / "capture-checklist.md").exists():
        errors.append(f"{skill_dir}: missing references/capture-checklist.md")
    if not (skill_dir / "references" / "audit-rubric.md").exists():
        errors.append(f"{skill_dir}: missing references/audit-rubric.md")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate skill repository layout.")
    parser.add_argument("skill_dirs", nargs="+", help="Skill directories to check.")
    args = parser.parse_args()

    all_errors: list[str] = []
    for raw_path in args.skill_dirs:
        all_errors.extend(check_skill(Path(raw_path)))

    if all_errors:
        for error in all_errors:
            print(error, file=sys.stderr)
        return 1

    print(f"ok: checked {len(args.skill_dirs)} skill(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
