# Audit Rubric

Use this reference to classify UI/UX implementation differences and decide what to report.

## Default Sensitivity

- Compare in hierarchy order: page-level layout first, then top-level modules, nested modules, and finally element details.
- Return parent/module problems before child details. If a parent layout, spacing, background, or edge issue explains child differences, do not expand every child region in the main report.
- Prioritize findings by visual implementation impact: size/layout dimensions, position/alignment, relative relationship/spacing, image/icon consistency, font metrics/typography, foreground color, background color, gradient, then shadow/effects.
- Do not let a large color-only background region outrank smaller but more actionable geometry, relationship, icon, or typography issues.
- Report subtle but meaningful UI/UX differences: module position and size, color shifts, 1-2 px spacing changes, margin/padding drift, misalignment, font size/weight/line-height changes, missing or wrong icons, image crop/size changes, radius changes, shadow/elevation differences, border changes, and gradient color/direction differences.
- Always check screen edges and safe-area boundaries as a separate pass: top, bottom, left, right, status-bar-adjacent areas, menu-bar-adjacent areas, home-indicator-adjacent areas, full-bleed backgrounds, and edge-aligned controls.
- Filter isolated noise from anti-aliasing, compression, subpixel rendering, DPR rounding, text rasterization, and transparent edge pixels.
- Treat repeated tiny differences as a pattern only when they form a coherent region or affect a visible UI element.
- Ignore copy-only and data-only mismatches by default. Different labels, counters, timestamps, names, IDs, and fetched values are not visual audit findings unless they change layout, wrapping, module size, visual state, or typography metrics.
- Ignore device/system UI differences by default: OS status bars, menu bars, browser chrome, simulator bezels, hardware notches, Dynamic Island, home indicators, gesture bars, and system navigation bars. Report them only when the design explicitly includes or styles those regions as app-owned UI.

## Categories

- Module Layout: x/y position, width, height, alignment, clipping, overflow, z-order.
- Spacing: margin, padding, gap, safe area, inset, list row height.
- Edge / Safe Area: screen-edge spacing, top/bottom inset, side gutters, app-owned status/menu/navigation areas, home-indicator spacing, full-bleed edge backgrounds.
- Border / Shape: border width, stroke color, radius, divider placement, shadow, elevation, mask.
- Background / Color: container background, foreground color, overlay, opacity, blur/tint.
- Gradient: gradient colors, stops, direction, angle, spread, opacity.
- Typography Metrics: font family, size, weight, line height, letter spacing, text box position, wrapping, truncation.
- Icon / Image: wrong asset, missing asset, size, crop, alignment, stroke width, filled vs outlined, color.
- UI State: selected, disabled, pressed, loading, empty, error, focus, hover, active state.

Do not use `Content` as a primary category. If text or data differs, classify only the UI effect: for example `Typography Metrics` for text box size/position, `Module Layout` for a card resizing, or `UI State` for a selected/empty state.

## Region Reporting

- Coordinates are relative to the top-left corner of the actual screenshot.
- Use `x`, `y`, `width`, and `height` for every region.
- Compare `annotated_actual.png` and `annotated_expected.png` as a pair. Matching marker numbers and coordinates show the same screenshot location in actual and normalized design.
- Check `regions.json.normalization` when source dimensions differ. The actual screenshot is the coordinate baseline; the design is proportionally fit without cropping, and any padding/offset is recorded there.
- Use `evidence_overlay_actual.png`, `evidence_overlay_expected.png`, `diff_heatmap.png`, and `diff_graymap.png` to understand where changed pixels sit inside a broad marker. Do not turn every evidence pixel into a separate report row.
- Use `diff_color_delta.png`, `diff_structure.png`, and `diff_edges.png` to distinguish color/fill changes from structural layout changes and edge/stroke movement.
- Open `region_crops/` for reported markers before writing the final issue. The crop pair is usually the clearest evidence for small typography, icon, border, radius, shadow, color, and alignment problems.
- Prefer `reported_regions` for the main report; treat `regions` as raw diff evidence and `suppressed_regions` as child noise explained by a parent issue.
- If a reported region has `finding_summary`, use it as the first script-backed interpretation of that region. Do not replace it with a guess that the region is noise unless there is concrete capture/setup evidence.
- If a reported region has `priority_tier`, `priority_category`, `element_kind`, `severity_score`, `confidence`, `dominant_signal`, and `diff_signals`, use them to prioritize review order and explain why the region was surfaced. Treat `element_kind` as a hypothesis until verified against the actual/design crop pair.
- If a reported region has `review_guidance`, follow it before expanding child regions. In particular, a broad parent region that touches screen edges or explains suppressed children is a high-priority UI/UX finding, not a low-value pixel artifact.
- If a reported region has `edge_evidence`, translate the edge margins into concrete UI observations: for example, `right=0px` means the actual app-owned region reaches the right screenshot edge and should be checked for missing side gutter, safe-area padding, or clipping against the design.
- If a reported region has `visual_evidence.diff_pixel_bbox`, use that box to state where the precise pixel evidence is concentrated within the broader parent/module marker.
- Use `suppressed_child_count` to explain hierarchy. A nonzero value usually means the tool found one parent/root issue that accounts for many internal diffs; report that parent first and avoid listing every child artifact.
- Use `level` to preserve hierarchy: lower values are higher-level page/module/edge findings; higher values are detail-level findings.
- Combine adjacent pixels into one issue when they belong to the same UI element or module.
- Split regions when one broad diff contains separate root causes.
- Prefer a clear module/element-level region over a huge page-level rectangle.
- Add explicit edge regions when the mismatch is at the screen boundary, even if the rest of the module looks correct.
- For text, mark the text box or baseline/line-height issue, not each glyph difference.
- For images, mark the image frame and note size/crop/position differences, not every pixel in the image.

## Confidence

- High: clear element-level mismatch and likely root cause.
- Medium: visible mismatch but root cause may be shared with another issue.
- Low: likely screenshot/setup mismatch, dynamic content, copy/data difference, or rasterization artifact.

## Report Style

- State actual vs expected in one sentence.
- Include exact values when measured or confidently inferred.
- Say when a result depends on screenshot setup.
- Say when a region was intentionally ignored because it is copy-only, data-only, or dynamic.
- Say when system UI was ignored because it was not part of the design target.
- Do not recommend code changes unless the user asks for fixes.
