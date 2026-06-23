# Capture Checklist

Use this reference when screenshot capture details can change the visual comparison.

## Shared Rules

- Capture the exact UI state requested by the user: route, modal/drawer state, selected tab, scroll offset, theme, locale, data fixtures, and loading state.
- Record screenshot dimensions, device/viewport, DPR or simulator scale, OS/browser, app build, and timestamp when relevant.
- Prefer PNG. Avoid JPEG, compressed messenger previews, or scaled images.
- Capture the actual UI and design reference at the same logical size whenever possible.
- Freeze animations, hover states, blinking carets, clocks, network images, and random content when possible.
- Exclude browser chrome, simulator bezels, device frames, menu bars, status bars, navigation bars, and home indicators unless the design includes them.
- Decide which top/bottom/side edge regions are app-owned before comparing; system-owned UI should be masked, cropped, or explicitly ignored.
- Always inspect screen-edge spacing separately after the main diff: top inset, bottom inset, side rails, safe-area padding, full-bleed backgrounds, and clipped edge-aligned controls.

## Web

- Use Playwright screenshots when possible.
- Set viewport size and device scale factor explicitly.
- Wait for fonts, images, and network-driven content before capture.
- Capture full page only if the design reference is full page; otherwise capture viewport or a specific element.
- Disable animations if they are not part of the design target.
- Ignore browser toolbar/tab/address-bar differences unless the design explicitly includes browser chrome.
- Check viewport edges after capture; full-bleed sections, sticky headers, sticky footers, and side gutters often drift from design.

## Figma And Design References

- Prefer exporting the exact frame at 1x or the same DPR used by the runtime screenshot.
- Confirm whether status bars, navigation bars, safe areas, tab bars, shadows, overlays, and backgrounds are included in the frame.
- Confirm whether top/bottom safe-area backgrounds are intended to be app-owned or system-owned.
- If only a shared Figma link is available, identify the exact frame and export dimensions before comparing.
- If Figma access is unavailable, ask for a PNG export or a design screenshot.

## iOS Simulator

- Prefer `xcrun simctl io booted screenshot actual.png` for simulator captures.
- Record device model, iOS version, appearance mode, content size category, locale, and simulator scale.
- Capture after the app settles; avoid transition frames.
- Decide explicitly whether to include status bar, home indicator, keyboard, sheets, and safe-area backgrounds.
- Ignore status bar and home indicator differences unless the Figma frame includes them as designed app content.
- Check whether app backgrounds, cards, rails, and bottom controls extend correctly into or around safe areas.

## Real Devices

- Ask for original screenshots, not compressed chat previews.
- Record device model, OS version, appearance mode, content size category, display zoom, locale, and app version.
- Watch for hardware-specific safe areas, Dynamic Island, notch, home indicator, and keyboard differences.
- Do not report hardware/system status bar, Dynamic Island, notch, home indicator, or menu bar differences unless the design explicitly models them.
- If exact repeat capture is not possible, report coordinate regions relative to the screenshot provided.

## Android

- Prefer `adb exec-out screencap -p > actual.png`.
- Record device/emulator model, Android version, density, font scale, navigation mode, theme, locale, and app build.
- Account for status/navigation bars and gesture insets when comparing against design frames.
- Ignore Android system status/navigation/gesture bar differences unless the design includes them.
