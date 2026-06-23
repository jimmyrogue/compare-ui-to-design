# Audit Rubric

Use this reference to classify differences and decide what to report.

## Default Sensitivity

- Report subtle but meaningful visual differences: color shifts, 1-2 px spacing changes, misalignment, font size/weight changes, missing or wrong icons, radius changes, shadow/elevation differences, and content that appears in the wrong place.
- Filter isolated noise from anti-aliasing, compression, subpixel rendering, DPR rounding, text rasterization, and transparent edge pixels.
- Treat repeated tiny differences as a pattern only when they form a coherent region or affect a visible UI element.

## Categories

- Layout: x/y position, alignment, size, wrapping, clipping, overflow, z-order.
- Spacing: margin, padding, gap, safe area, inset, list row height.
- Color: background, foreground, border, divider, overlay, opacity, gradient, blur/tint.
- Typography: font family, size, weight, line height, letter spacing, truncation.
- Iconography: wrong icon, missing icon, stroke width, filled vs outlined, size, color.
- Shape: border radius, border width, shadow, elevation, mask, image crop.
- Content: missing text, wrong copy, wrong image, wrong data, localization mismatch.
- State: hover, focus, selected, disabled, pressed, loading, empty, error.

## Region Reporting

- Coordinates are relative to the top-left corner of the actual screenshot.
- Use `x`, `y`, `width`, and `height` for every region.
- Combine adjacent pixels into one issue when they belong to the same UI element.
- Split regions when one broad diff contains separate root causes.
- Prefer a clear element-level region over a huge page-level rectangle.

## Confidence

- High: clear element-level mismatch and likely root cause.
- Medium: visible mismatch but root cause may be shared with another issue.
- Low: likely screenshot/setup mismatch, dynamic content, or rasterization artifact.

## Report Style

- State actual vs expected in one sentence.
- Include exact values when measured or confidently inferred.
- Say when a result depends on screenshot setup.
- Do not recommend code changes unless the user asks for fixes.
