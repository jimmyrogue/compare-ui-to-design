# Audit Rubric

Use this reference to classify UI/UX implementation differences and decide what to report.

## Default Sensitivity

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
