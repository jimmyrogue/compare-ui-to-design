---
name: compare-ui-to-design
description: Audit UI/UX visual fidelity between a running UI and a design reference in top-down hierarchy order. Use when an AI agent needs to compare web pages, app screenshots, iOS/Android simulators, real-device screenshots, Figma exports, design mockups, or image/PDF references for page layout, module position, size, border, color, background, gradient, spacing, margin, padding, typography metrics, icon/image size, alignment, screen-edge, and safe-area differences; mark differences on screenshots and report precise coordinates while ignoring copy/data-only and device/system UI mismatches unless they affect app-owned layout.
---

# Compare UI to Design

## Overview

Use this skill to compare an actual running UI against a design reference and produce an evidence-based UI/UX visual audit. Default to audit-only work: identify, mark, and explain differences in structure, visual styling, spacing, typography metrics, and media placement without changing application code unless the user explicitly asks for fixes.

Focus on UI/UX implementation fidelity, not copy review or dynamic data parity. Treat text values, timestamps, counters, list content, and fetched data as ignorable context unless they change layout, wrapping, size, typography, alignment, or visual state.

Pay special attention to screen edges and safe-area boundaries. Top, bottom, left, and right edge spacing is easy to miss, especially around status bars, menu bars, navigation bars, home indicators, browser chrome, notches, and tablet split-view gutters. Compare those regions only when they belong to the designed UI; otherwise ignore device/system UI differences.

Audit from top to bottom in the UI hierarchy. Start with page-level layout, then top-level modules, then nested modules, then element details. If a parent module or page-level spacing issue explains child differences, report the parent issue first and do not expand every child pixel difference unless the child has an independent UI problem.

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
   - If the actual screenshot and design export have different pixel sizes, use the actual screenshot as the coordinate baseline and let `visual_diff.py` proportionally fit the design into that canvas without cropping. Inspect `regions.json.normalization` before judging size, margin, or edge findings.

3. Run automated visual diff when both comparable images are available.
   - Use `scripts/visual_diff.py`. The helper is node-first by default: UI node matching and hierarchical attribution make the primary decisions, while RGB/Lab/structure/edge pixel diffs are evidence and debugging inputs.
   - Prefer passing real node trees when available. Expected/design nodes use expected-image coordinates and are normalized into the actual screenshot coordinate space; actual/runtime nodes use actual screenshot coordinates.

   ```bash
   python skills/compare-ui-to-design/scripts/visual_diff.py \
     --actual actual.png \
     --expected expected.png \
     --out-dir report \
     --expected-nodes expected-nodes.json \
     --actual-nodes actual-nodes.json
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

   - Use `--node-mode pixel` only when you need the legacy pixel-region hierarchy for debugging or compatibility. In `auto` mode, missing node JSON falls back to lightweight screenshot node proposals.
   - Use `--report-mode` when you need to drill into details without waiting for every parent-level issue to be resolved first. Presets are `structure`, `module`, `detail`, and `raw`. Use `--hierarchy-depth 1..9` only when you need finer control; it overrides the preset if both are provided.

   ```bash
   python skills/compare-ui-to-design/scripts/visual_diff.py \
     --actual actual.png \
     --expected expected.png \
     --out-dir report-detail \
     --report-mode detail
   ```

   - A good audit loop is: run the default command or `--report-mode structure` for structure, then rerun with `--report-mode module`, `detail`, or `raw` when the parent finding is understood well enough to inspect deeper UI details.

4. Inspect the result manually.
   - Treat the script as a detector, not a final judge.
   - Classify likely differences using `references/audit-rubric.md`.
   - Follow top-down order: page layout -> top-level modules -> nested modules -> element details.
   - Inspect `annotated_actual.png` and `annotated_expected.png` together. They use the same actual/normalized-design coordinates and marker numbers, so compare the actual and design at each matching region before writing conclusions.
   - In hierarchy-depth mode, inspect `annotated_depth_actual.png` and `annotated_depth_expected.png` for the selected drilldown layer. Use `annotated_raw_actual.png` / `annotated_raw_expected.png` when you need every raw pixel-evidence candidate.
   - Inspect `issues`, `actionable_issues`, `deferred_visual_issues`, `ui_nodes`, and `node_matches` in `regions.json` before writing the report. Use `raw_pixel_regions` only as evidence/debug context.
   - When a marker is broad, inspect `evidence_overlay_actual.png`, `evidence_overlay_expected.png`, `diff_heatmap.png`, `diff_graymap.png`, `diff_color_delta.png`, `diff_structure.png`, and `diff_edges.png` to locate the precise changed pixels that support the node-level issue.
   - Open the per-region crop pair in `region_crops/` for each reported marker before deciding the exact issue. The crop pair is usually the clearest evidence for small typography, icon, border, radius, color, and alignment problems.
   - Prioritize issues by visual implementation impact, not by raw color area. Use this order unless the user gives a different one: size/layout dimensions, position/alignment, relative relationship/spacing, image or icon consistency, font metrics/typography, foreground color, background color, gradient, then shadow/effects.
   - Report modules, containers, images, icons, borders, typography metrics, spacing, margin, padding, and alignment before color-only and decorative effect differences.
   - Audit screen-edge regions explicitly: top inset, bottom inset, left/right rails, safe-area padding, full-bleed backgrounds, clipped cards, sticky headers/footers, and edge-aligned controls.
   - Prefer `actionable_issues` from `regions.json` for the user-facing report. `reported_regions` and `focus_regions` are issue-backed marker boxes for annotation compatibility. Use `deferred_visual_issues` for background/color/gradient/shadow issues that should not outrank layout/text/icon problems.
   - When a reported region includes `finding_summary`, `review_guidance`, or `edge_evidence`, use those fields as script evidence in the report. Do not dismiss a broad parent/module region as a false positive merely because it groups many child pixel differences.
   - When a reported region includes `priority_tier`, `priority_category`, `element_kind`, `severity_score`, `confidence`, `dominant_signal`, and `diff_signals`, use those fields to prioritize and explain the issue. `element_kind` is a hypothesis, not a final label; verify it against the actual/design crop pair.
   - When an issue includes `delta`, `parent_delta`, `residual_delta`, `suppressed_children`, and `evidence`, use those fields to explain whether the fix belongs to a parent layout or a child node. Pixel evidence supports the node diagnosis; it is not the primary decision.
   - If `edge_evidence.touches` includes an edge or `edge_evidence.margins` shows a very small margin such as `right=0px`, explicitly compare that edge against the design. State whether app-owned content is too close to the screen edge, clipped, missing safe-area padding, or using a different full-bleed background.
   - Treat `suppressed_child_count > 0` as evidence that the parent issue explains lower-level noise. Report the parent/root issue first, then inspect suppressed children only for independent icon, image, typography, color, or border problems.
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

Annotated actual: /absolute/path/to/annotated_actual.png
Annotated design: /absolute/path/to/annotated_expected.png
Depth annotations: /absolute/path/to/annotated_depth_actual.png, /absolute/path/to/annotated_depth_expected.png
Raw annotations: /absolute/path/to/annotated_raw_actual.png, /absolute/path/to/annotated_raw_expected.png
Evidence overlays: /absolute/path/to/evidence_overlay_actual.png, /absolute/path/to/evidence_overlay_expected.png
Diff maps: /absolute/path/to/diff_heatmap.png, /absolute/path/to/diff_graymap.png, /absolute/path/to/diff_color_delta.png, /absolute/path/to/diff_structure.png, /absolute/path/to/diff_edges.png
Region crops: /absolute/path/to/region_crops

| # | Target | Region | Category | Difference |
|---|---|---|---|---|
| 1 | ProfileCard.badge.icon | x=120 y=84 w=48 h=20 | Position / Alignment | Icon residual dx=5px after parent dx=0px; adjust local padding/gap. |
| 2 | Header.title | x=24 y=308 w=327 h=24 | Typography Metrics | Text baseline is 3px lower and height is 2px taller than expected. |
| 3 | ProductCard | x=16 y=144 w=358 h=92 | Size / Layout | Card width is 12px wider; children share the same parent offset. |
| 4 | AppBackground | x=0 y=0 w=390 h=844 | Deferred Visual | Background color differs, but no structural node issue is attached. |

## Notes
- Screenshot size: 390x844.
- Design normalization: expected image was proportionally fit into the actual screenshot canvas; no cropping was applied.
- Script evidence: use `actionable_issues` first; use `deferred_visual_issues` for background/color/gradient/shadow follow-up.
- Prioritization evidence: use priority_tier, category, severity_score, confidence, delta, parent_delta, residual_delta, suppressed_children, and region crop pairs to decide which issues matter most.
- Copy-only and live-data differences were ignored unless they affected layout.
- Device/system UI chrome, dynamic clock, and caret regions were ignored.
```

Keep the report factual. Avoid vague language like "looks different" unless followed by the specific location and visual property that differs.

## Resources

- `scripts/visual_diff.py`: deterministic image comparison and annotation CLI.
- `references/capture-checklist.md`: capture rules for Web, Figma, simulators, and devices.
- `references/audit-rubric.md`: top-down hierarchy, difference categories, tolerance policy, and reporting rules.
