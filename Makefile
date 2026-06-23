PYTHON ?= python3

.PHONY: check validate test skills-list official-validate

check: validate test skills-list

validate:
	$(PYTHON) scripts/check_skill.py skills/compare-ui-to-design

test:
	$(PYTHON) -m pytest

skills-list:
	npx -y skills add . -a codex --list

official-validate:
	$(PYTHON) /Users/jimmy/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/compare-ui-to-design
