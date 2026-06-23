---
name: compare-ui-to-design
description: Audit visual fidelity between a running UI and a design reference. Use when Codex needs to compare web pages, app screenshots, iOS/Android simulators, real-device screenshots, Figma exports, design mockups, or image/PDF design references for differences in layout, margin, padding, color, typography, iconography, spacing, alignment, content, or visual state; mark differences on screenshots and report precise coordinates.
---

# Compare UI to Design

## Overview

Use this skill to compare an actual running UI against a design reference and produce an evidence-based visual audit. Default to audit-only work: identify, mark, and explain differences without changing application code unless the user explicitly asks for fixes.

## Workflow

1. Establish comparable inputs.
   - Confirm the exact screen, route, component state, viewport/device size, DPR/scale, theme, locale, and data state.
   - Capture or request the actual running UI screenshot.
   - Export or request the design reference screenshot from Figma or another source.
   - If capture details matter, read `references/capture-checklist.md`.

2. Normalize before comparing.
   - Prefer same viewport dimensions and pixel density.
   - Crop browser chrome, simulator bezels, status bars, or navigation bars only when they are not part of the design target.
   - Preserve screenshots as PNG when possible.
   - Do not resize one image unless the user confirms the intended scale or the mismatch is clearly from export size.

3. Run automated visual diff when both comparable images are available.
   - Use `scripts/visual_diff.py`:

   ```bash
   python skills/compare-ui-to-design/scripts/visual_diff.py \
     --actual actual.png \
     --expected expected.png \
     --out-dir report
   ```

   - Use stricter or looser options only when the task requires it:

   ```bash
   python skills/compare-ui-to-design/scripts/visual_diff.py \
     --actual actual.png \
     --expected expected.png \
     --out-dir report \
     --threshold 10 \
     --min-area 12 \
     --merge-gap 6
   ```

4. Inspect the result manually.
   - Treat the script as a detector, not a final judge.
   - Classify likely differences using `references/audit-rubric.md`.
   - Filter noise from anti-aliasing, compression, DPR rounding, dynamic content, cursor/caret state, animations, clocks, or remote image loading.

5. Report with location evidence.
   - Include the marked screenshot path when available.
   - List each issue by marker number with `x`, `y`, `width`, and `height` coordinates relative to the actual screenshot.
   - Explain the exact visible mismatch: actual vs expected.
   - If screenshots cannot be generated, provide coordinates from the inspected viewport/device frame and describe how the region was located.

## Output Format

Use this concise structure:

```markdown
## Visual Differences

Annotated screenshot: /absolute/path/to/annotated_actual.png

| # | Region | Category | Difference |
|---|---|---|---|
| 1 | x=120 y=84 w=48 h=20 | Typography | Actual title is 14px/medium; design appears 16px/semibold. |
| 2 | x=24 y=308 w=327 h=1 | Color | Divider is #E5E7EB; design uses a lighter #F1F2F4. |

## Notes
- Screenshot size: 390x844.
- Dynamic clock and caret regions were ignored.
```

Keep the report factual. Avoid vague language like "looks different" unless followed by the specific location and visual property that differs.

## Resources

- `scripts/visual_diff.py`: deterministic image comparison and annotation CLI.
- `references/capture-checklist.md`: capture rules for Web, Figma, simulators, and devices.
- `references/audit-rubric.md`: difference categories, tolerance policy, and reporting rules.
