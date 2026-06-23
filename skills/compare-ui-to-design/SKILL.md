---
name: compare-ui-to-design
description: Audit UI/UX visual fidelity between a running UI and a design reference. Use when an AI agent needs to compare web pages, app screenshots, iOS/Android simulators, real-device screenshots, Figma exports, design mockups, or image/PDF references for module position, size, border, color, background, gradient, spacing, margin, padding, typography metrics, icon/image size, alignment, screen-edge, and safe-area differences; mark differences on screenshots and report precise coordinates while ignoring copy/data-only and device/system UI mismatches unless they affect app-owned layout.
---

# Compare UI to Design

## Overview

Use this skill to compare an actual running UI against a design reference and produce an evidence-based UI/UX visual audit. Default to audit-only work: identify, mark, and explain differences in structure, visual styling, spacing, typography metrics, and media placement without changing application code unless the user explicitly asks for fixes.

Focus on UI/UX implementation fidelity, not copy review or dynamic data parity. Treat text values, timestamps, counters, list content, and fetched data as ignorable context unless they change layout, wrapping, size, typography, alignment, or visual state.

Pay special attention to screen edges and safe-area boundaries. Top, bottom, left, and right edge spacing is easy to miss, especially around status bars, menu bars, navigation bars, home indicators, browser chrome, notches, and tablet split-view gutters. Compare those regions only when they belong to the designed UI; otherwise ignore device/system UI differences.

## Workflow

1. Establish comparable inputs.
   - Confirm the exact screen, route, component state, viewport/device size, DPR/scale, theme, locale, and data state.
   - Capture or request the actual running UI screenshot.
   - Export or request the design reference screenshot from Figma or another source.
   - If capture details matter, read `references/capture-checklist.md`.

2. Normalize before comparing.
   - Prefer same viewport dimensions and pixel density.
   - Crop or mask browser chrome, simulator bezels, menu bars, status bars, navigation bars, home indicators, and other device/system UI only when they are not part of the design target.
   - Decide whether design frames include safe-area content before comparing top/bottom/side edges.
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
   - Report modules, containers, images, icons, borders, backgrounds, gradients, typography metrics, spacing, margin, padding, and alignment first.
   - Audit screen-edge regions explicitly: top inset, bottom inset, left/right rails, safe-area padding, full-bleed backgrounds, clipped cards, sticky headers/footers, and edge-aligned controls.
   - Ignore copy-only and data-only differences by default: different labels, counters, timestamps, IDs, names, list items, or backend values are not UI/UX issues unless they change visual layout.
   - Filter noise from anti-aliasing, compression, DPR rounding, dynamic content, cursor/caret state, animations, clocks, remote image loading, and system-owned UI chrome.

5. Report with location evidence.
   - Include the marked screenshot path when available.
   - List each issue by marker number with `x`, `y`, `width`, and `height` coordinates relative to the actual screenshot.
   - Explain the exact UI/UX mismatch: actual vs expected.
   - If screenshots cannot be generated, provide coordinates from the inspected viewport/device frame and describe how the region was located.

## Output Format

Use this concise structure:

```markdown
## Visual Differences

Annotated screenshot: /absolute/path/to/annotated_actual.png

| # | Region | Category | Difference |
|---|---|---|---|
| 1 | x=120 y=84 w=48 h=20 | Typography Metrics | Actual title renders 14px/medium and sits 3px too high; design appears 16px/semibold. |
| 2 | x=24 y=308 w=327 h=1 | Border / Color | Divider is #E5E7EB and 1px lower; design uses a lighter #F1F2F4 at y=307. |
| 3 | x=16 y=144 w=358 h=92 | Module / Spacing | Card width matches, but internal horizontal padding is 12px larger than design. |
| 4 | x=0 y=0 w=390 h=44 | Edge / Safe Area | Top background stops below the status-bar area; design expects the same color to extend to the screen edge. |

## Notes
- Screenshot size: 390x844.
- Copy-only and live-data differences were ignored unless they affected layout.
- Device/system UI chrome, dynamic clock, and caret regions were ignored.
```

Keep the report factual. Avoid vague language like "looks different" unless followed by the specific location and visual property that differs.

## Resources

- `scripts/visual_diff.py`: deterministic image comparison and annotation CLI.
- `references/capture-checklist.md`: capture rules for Web, Figma, simulators, and devices.
- `references/audit-rubric.md`: difference categories, tolerance policy, and reporting rules.
