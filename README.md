# compare-ui-to-design

[![Tests](https://github.com/jimmyrogue/compare-ui-to-design/actions/workflows/test.yml/badge.svg)](https://github.com/jimmyrogue/compare-ui-to-design/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Agent skill for auditing UI/UX differences between a running interface and a design reference, then marking the exact regions that differ.

English | [中文](#中文)

## What It Does

`compare-ui-to-design` compares web pages, app screenshots, simulator captures, real-device screenshots, Figma exports, and static design images. It is audit-only by default: it identifies UI/UX implementation differences and does not modify application code unless you explicitly ask for fixes.

The skill focuses on:

- Top-down comparison: page layout, top-level modules, nested modules, then element details
- Module position, size, alignment, clipping, and z-order
- Border, radius, shadow, divider, background, color, opacity, and gradient direction
- Spacing, margin, padding, gap, safe-area inset, and edge alignment
- Typography metrics: font family, size, weight, line height, letter spacing, text box position, wrapping, and truncation
- Icon and image size, crop, placement, stroke/fill style, and color
- Screen edges and safe areas, which are easy to miss

It intentionally avoids noisy or low-value comparisons:

- Copy-only text differences
- Live-data differences such as timestamps, counters, labels, names, IDs, or fetched values
- Device/system UI chrome such as phone status bars, tablet menu bars, browser chrome, home indicators, gesture bars, navigation bars, notches, and Dynamic Island

Those differences are reported only when they affect app-owned UI layout, component size, visual state, or typography metrics.

## Install

Install with the standard `skills` installer. Pick the adapter for your agent:

| Agent | Command |
| :--- | :--- |
| Codex | `npx skills add jimmyrogue/compare-ui-to-design -a codex -g -y` |
| Claude Code | `npx skills add jimmyrogue/compare-ui-to-design -a claude-code -g -y` |
| Antigravity | `npx skills add jimmyrogue/compare-ui-to-design -a antigravity -g -y` |
| OpenCode | `npx skills add jimmyrogue/compare-ui-to-design -a opencode -g -y` |

Inspect available skills before installing:

```bash
npx skills add jimmyrogue/compare-ui-to-design --list
```

Update installed skills:

```bash
npx skills update -g -y
```

## Usage Prompt

```text
Use $compare-ui-to-design to compare my running UI screenshot with the Figma export and mark the UI/UX differences.
Compare from page layout to top-level modules to nested modules to element details.
Focus on module layout, screen edges, safe areas, spacing, color, typography metrics, icons, images, and gradients.
Ignore copy-only, live-data, and device/system UI differences unless they affect app-owned UI layout.
When the diff script reports a broad parent region, use its finding_summary, review_guidance, edge_evidence, and suppressed_child_count directly before deciding whether to inspect child regions.
Compare annotated_actual.png and annotated_expected.png together, then use evidence_overlay_* and diff_graymap.png to locate the precise pixel evidence inside broad markers.
```

## Skill

| Skill | When | What it does |
| :--- | :--- | :--- |
| [`compare-ui-to-design`](skills/compare-ui-to-design/SKILL.md) | Running UI does not visually match a Figma/design reference | Captures or accepts screenshots, runs visual diff tooling when useful, marks UI/UX difference regions, and reports precise coordinates. |

This repository uses the standard `skills/<name>/SKILL.md` layout supported by the `skills` installer.

## Manual Install

For agents that load skills from a local folder, copy or symlink `skills/compare-ui-to-design` into that agent's skill root:

```bash
mkdir -p /path/to/agent/skills
ln -s "$(pwd)/skills/compare-ui-to-design" /path/to/agent/skills/compare-ui-to-design
```

## Visual Diff CLI

The skill includes a deterministic helper script for comparing an actual screenshot with a design reference. If the design reference has a different pixel size, it is proportionally fit into the actual screenshot canvas without cropping before comparison:

```bash
python skills/compare-ui-to-design/scripts/visual_diff.py \
  --actual actual.png \
  --expected expected.png \
  --out-dir report
```

Outputs:

- `report/annotated_actual.png`
- `report/annotated_expected.png`
- `report/annotated_raw_actual.png`
- `report/annotated_raw_expected.png`
- `report/annotated_depth_actual.png`
- `report/annotated_depth_expected.png`
- `report/evidence_overlay_actual.png`
- `report/evidence_overlay_expected.png`
- `report/diff_heatmap.png`
- `report/diff_graymap.png`
- `report/diff_color_delta.png`
- `report/diff_structure.png`
- `report/diff_edges.png`
- `report/region_crops/`
- `report/regions.json`

The default engine is visual-first. It uses RGB pixel distance, CIE Lab perceptual color distance, local structural dissimilarity, and Sobel edge/stroke delta to create screenshot-backed `visual_candidates` first. Figma/design nodes, Chrome/runtime nodes, and implementation evidence resolve the candidate target and likely root cause; they do not replace or suppress visible screenshot mismatches.

If node JSON is available, pass it with `--expected-nodes` and `--actual-nodes`. Use `--implementation-evidence` for code or tool output such as SwiftUI frame/padding/offset checks, DOM style, source paths, or static alignment notes. Static metadata can become `implementation_hint` evidence or `metadata_only_findings`, but the actual screenshot remains the fidelity ground truth.

`regions.json` contains issue-centered fields: `visual_candidates`, `resolved_issues`, `issues`, `actionable_issues`, `deferred_visual_issues`, `unresolved_visual_candidates`, `metadata_only_findings`, `ui_nodes`, `node_matches`, `implementation_evidence`, and `raw_pixel_regions`. `visual_candidates` is the screenshot-backed investigation pool and may include eligible raw detail candidates that parent hierarchy markers suppressed. `reported_regions` and `focus_regions` remain for annotation compatibility, but they are issue-backed marker boxes.

Report order is intentionally geometry-first: size/layout dimensions, position/alignment, relative relationship/spacing, image/icon consistency, font metrics/typography, foreground color, background color, gradient, then shadow/effects. `--report-mode detail` includes tiers 1-5 by default, so color-only backgrounds and decorative effects do not dominate the marked screenshot.

The JSON also includes `audit_order: "top-down"`, `reported_regions`, `depth_regions`, `parent_regions`, `detail_regions`, `raw_regions`, and `suppressed_regions`. Use screenshot-backed `actionable_issues` for the main audit and `deferred_visual_issues` for background/color/gradient/shadow differences that should not outrank layout, text, or icon problems. Screenshot-parser fallback nodes are lightweight localization proposals, not external Figma/Chrome/code evidence. Treat `metadata_only_findings` as non-user-facing evidence unless a visual candidate supports it.

Use `--node-mode pixel` to run the legacy pixel-region decision path. Use `--report-mode structure|module|detail|raw` to drill into deeper layers while keeping top-down context. `--hierarchy-depth 1..9` is the advanced numeric form and overrides the preset when both are provided. A practical sequence is:

```bash
python skills/compare-ui-to-design/scripts/visual_diff.py \
  --actual actual.png \
  --expected expected.png \
  --out-dir report-detail \
  --report-mode detail
```

- `structure`: page, screen edge, safe area, global background (`depth=1`)
- `module`: nested modules, cards, list rows (`depth=3`)
- `detail`: icons, images, progress rings, badges (`depth=5`)
- `raw`: all raw/debug regions (`depth=9`)

Reported regions can include `finding_summary`, `review_guidance`, `edge_evidence`, and `suppressed_child_count`. Agents should use those fields directly as script evidence. A broad parent/module region is not a false positive just because it covers many child diffs; for example, `edge_evidence.margins.right = 0` means the actual app-owned region reaches the right screenshot edge and must be checked for missing side gutter, safe-area padding, or clipping against the design.

Each run also returns paired visual evidence. `annotated_actual.png` and `annotated_expected.png` use the same marker numbers and coordinates, so agents can compare the actual and design views directly. `annotated_depth_*` shows the selected drilldown layer, and `annotated_raw_*` shows every raw pixel-evidence candidate. When source sizes differ, `annotated_expected.png` is the normalized design image in the actual screenshot coordinate space; `regions.json.normalization` records the original design size, scale, offset, padding, and `cropped: false`. `evidence_overlay_actual.png`, `evidence_overlay_expected.png`, `diff_heatmap.png`, `diff_graymap.png`, `diff_color_delta.png`, `diff_structure.png`, and `diff_edges.png` show the changed pixels behind each visual candidate. `region_crops/` contains paired actual/design/diff crops for reported markers and is the fastest way to verify the exact visual property before calling Figma, Chrome DevTools, or source search for the candidate area.

## Project Layout

```text
.
├── skills/compare-ui-to-design/   # Installable skill
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── references/
│   └── scripts/visual_diff.py
├── scripts/check_skill.py          # Portable structure/frontmatter checker
├── tests/                          # Synthetic visual-diff tests
├── package.json                    # Skill package metadata
├── pyproject.toml                  # Python test/runtime dependencies
└── packaging.allowlist             # Release/package allowlist
```

## Development

Set up Python dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install ".[dev]"
```

Run all local checks:

```bash
make check PYTHON=.venv/bin/python
```

Useful targets:

```bash
make validate PYTHON=.venv/bin/python
make test PYTHON=.venv/bin/python
make skills-list
```

If you have the official `skill-creator` validator locally, you can also run:

```bash
python3 path/to/skill-creator/scripts/quick_validate.py skills/compare-ui-to-design
```

## License

MIT

---

## 中文

`compare-ui-to-design` 是一个面向各类 AI agent 的 skill，用于对比“实际运行中的 UI”和“设计稿/Figma 导出图”，找出 UI/UX 实现差异，并在截图上标注具体区域。

它默认只做审计，不会修改业务代码；只有你明确要求修复时，agent 才应该继续改代码。

## 它关注什么

这个 skill 关注 UI/UX 实现是否和设计稿一致：

- 按层级从整体到局部对比：页面整体、顶层模块、嵌套模块、元素细节
- 模块的位置、尺寸、对齐、裁切、层级
- 边框、圆角、阴影、分割线、背景、颜色、透明度、渐变方向
- 间距、margin、padding、gap、安全区 inset、屏幕边缘对齐
- 文字的字体、字号、字重、行高、字距、文本框位置、换行、截断
- 图标和图片的尺寸、裁切、位置、描边/填充样式、颜色
- 屏幕边缘和安全区，这些位置最容易被忽略

它默认忽略低价值或容易误报的差异：

- 纯文案差异
- 动态数据差异，例如时间、计数器、标签、用户名、ID、接口返回值
- 设备或系统自带 UI，例如手机 status bar、平板 menu bar、浏览器工具栏、home indicator、手势条、系统导航栏、刘海、Dynamic Island

只有当这些差异影响了 app 自己的布局、组件尺寸、视觉状态或文字排版度量时，才应该报告。

## 安装

使用标准 `skills` installer 安装。根据你的 agent 选择 adapter：

| Agent | 命令 |
| :--- | :--- |
| Codex | `npx skills add jimmyrogue/compare-ui-to-design -a codex -g -y` |
| Claude Code | `npx skills add jimmyrogue/compare-ui-to-design -a claude-code -g -y` |
| Antigravity | `npx skills add jimmyrogue/compare-ui-to-design -a antigravity -g -y` |
| OpenCode | `npx skills add jimmyrogue/compare-ui-to-design -a opencode -g -y` |

安装前查看仓库里的 skill：

```bash
npx skills add jimmyrogue/compare-ui-to-design --list
```

更新已安装的 skills：

```bash
npx skills update -g -y
```

## 使用提示词

```text
Use $compare-ui-to-design to compare my running UI screenshot with the Figma export and mark the UI/UX differences.
Focus on module layout, screen edges, safe areas, spacing, color, typography metrics, icons, images, and gradients.
Ignore copy-only, live-data, and device/system UI differences unless they affect app-owned UI layout.
When the diff script reports a broad parent region, use its finding_summary, review_guidance, edge_evidence, and suppressed_child_count directly before deciding whether to inspect child regions.
```

也可以用中文直接说：

```text
使用 $compare-ui-to-design 对比实际运行截图和 Figma 设计稿，标注 UI/UX 差异。
先比较页面整体，再比较顶层模块、嵌套模块，最后比较元素细节。
重点关注模块布局、屏幕边缘、安全区、间距、颜色、字体字号、图标、图片和渐变。
忽略纯文案、动态数据、设备或系统自带 UI 的差异，除非它们影响 app 自己的布局。
当 diff 脚本报告一个较大的父级区域时，先直接使用它的 finding_summary、review_guidance、edge_evidence 和 suppressed_child_count，再决定是否继续检查子区域。
同时对照 annotated_actual.png 和 annotated_expected.png，再用 evidence_overlay_* 和 diff_graymap.png 定位大标记区域里的精细像素证据。
```

## Skill

| Skill | 使用场景 | 作用 |
| :--- | :--- | :--- |
| [`compare-ui-to-design`](skills/compare-ui-to-design/SKILL.md) | 实际运行 UI 和 Figma/设计稿视觉不一致 | 获取或接收截图，必要时运行视觉 diff 工具，标注 UI/UX 差异区域，并输出精确坐标。 |

本仓库使用 `skills/<name>/SKILL.md` 标准结构，可被 `skills` installer 识别。

## 手动安装

如果你的 agent 支持从本地目录加载 skill，可以把 `skills/compare-ui-to-design` 复制或软链到该 agent 的 skill 根目录：

```bash
mkdir -p /path/to/agent/skills
ln -s "$(pwd)/skills/compare-ui-to-design" /path/to/agent/skills/compare-ui-to-design
```

## Visual Diff CLI

skill 内置了一个可重复运行的截图对比脚本，用于对比实际截图和设计稿。如果设计稿像素尺寸不同，脚本会先把设计稿按比例完整 fit 到实际截图画布里，不做裁切，然后再对比：

```bash
python skills/compare-ui-to-design/scripts/visual_diff.py \
  --actual actual.png \
  --expected expected.png \
  --out-dir report
```

输出：

- `report/annotated_actual.png`
- `report/annotated_expected.png`
- `report/annotated_raw_actual.png`
- `report/annotated_raw_expected.png`
- `report/annotated_depth_actual.png`
- `report/annotated_depth_expected.png`
- `report/evidence_overlay_actual.png`
- `report/evidence_overlay_expected.png`
- `report/diff_heatmap.png`
- `report/diff_graymap.png`
- `report/diff_color_delta.png`
- `report/diff_structure.png`
- `report/diff_edges.png`
- `report/region_crops/`
- `report/regions.json`

默认引擎现在是 visual-first：先用 RGB 像素距离、CIE Lab 感知色差、局部结构差异和 Sobel 边缘/描边差异生成有截图证据的 `visual_candidates`。Figma/设计节点、Chrome/runtime 节点和代码实现证据只用于解析候选问题的目标节点、归因和修复线索，不能替代或压掉真实截图中的可见问题。

已有节点树时，用 `--expected-nodes` 和 `--actual-nodes` 传入。`--implementation-evidence` 用于传入代码或工具检查结果，例如 SwiftUI frame/padding/offset、DOM style、source path 或静态对齐说明。静态 metadata 可以成为 implementation hint 或 `metadata_only_findings`，但真实截图才是 UI fidelity 的 ground truth。

`regions.json` 会包含 issue-centered 字段：`visual_candidates`、`resolved_issues`、`issues`、`actionable_issues`、`deferred_visual_issues`、`unresolved_visual_candidates`、`metadata_only_findings`、`ui_nodes`、`node_matches`、`implementation_evidence` 和 `raw_pixel_regions`。`visual_candidates` 是有截图证据的调查候选池，可能包含被父级层级 marker 压住、但仍值得检查的 raw detail candidate。`reported_regions` 和 `focus_regions` 仍然保留，用于兼容标注图，但它们是 issue-backed marker boxes。

报告顺序会优先看几何和结构：尺寸/布局、位置/对齐、相对关系/间距、图片/icon 一致性、字体指标/排版、前景色、背景色、渐变、阴影/效果。`--report-mode detail` 默认只包含 1-5 层，所以纯背景色和装饰效果不会主导标注截图。

JSON 还会包含 `audit_order: "top-down"`、`reported_regions`、`depth_regions`、`parent_regions`、`detail_regions`、`raw_regions` 和 `suppressed_regions`。主报告应优先使用有截图证据的 `actionable_issues`，背景色、渐变、阴影等低优先级视觉差异放在 `deferred_visual_issues`。截图 fallback parser 节点只是轻量定位 proposal，不是外部 Figma/Chrome/code 证据。`metadata_only_findings` 只是静态证据，除非有 visual candidate 支持，否则不应该作为用户级 UI 问题报告。

使用 `--node-mode pixel` 可以运行旧的 pixel-region 决策路径。使用 `--report-mode structure|module|detail|raw` 可以在保留 top-down 上下文的同时继续向细节层钻取。`--hierarchy-depth 1..9` 是高级数字形式；如果 preset 和数字同时传入，数字优先。常用命令：

```bash
python skills/compare-ui-to-design/scripts/visual_diff.py \
  --actual actual.png \
  --expected expected.png \
  --out-dir report-detail \
  --report-mode detail
```

- `structure`：页面、屏幕边缘、安全区、全局背景（`depth=1`）
- `module`：嵌套模块、卡片、列表行（`depth=3`）
- `detail`：图标、图片、进度环、徽标（`depth=5`）
- `raw`：所有 raw/debug 区域（`depth=9`）

`reported_regions` 可能包含 `finding_summary`、`review_guidance`、`edge_evidence` 和 `suppressed_child_count`。Agent 应该把这些字段当作脚本证据直接使用。一个较大的父级/模块区域不应该因为覆盖了很多子级 diff 就被当成误报；例如 `edge_evidence.margins.right = 0` 表示实际 app 区域已经贴到截图右边缘，应该检查是否缺少右侧 gutter、安全区 padding，或者是否发生裁切。

每次运行还会返回成对的视觉证据。`annotated_actual.png` 和 `annotated_expected.png` 使用相同编号和坐标，方便 agent 直接对照实际图与设计稿。`annotated_depth_*` 展示当前选择的钻取层级，`annotated_raw_*` 展示所有 raw pixel evidence。当源图尺寸不一致时，`annotated_expected.png` 是已经归一化到实际截图坐标系的设计稿；`regions.json.normalization` 会记录原始设计稿尺寸、缩放比例、offset、padding，以及 `cropped: false`。`evidence_overlay_actual.png`、`evidence_overlay_expected.png`、`diff_heatmap.png`、`diff_graymap.png`、`diff_color_delta.png`、`diff_structure.png` 和 `diff_edges.png` 用来展示每个 visual candidate 背后的变化像素。`region_crops/` 会为上报 marker 生成实际图/设计图/diff 的局部裁剪，是确认具体视觉属性、再针对该区域调用 Figma/Chrome/代码搜索的最快入口。

## 项目结构

```text
.
├── skills/compare-ui-to-design/   # 可安装 skill
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── references/
│   └── scripts/visual_diff.py
├── scripts/check_skill.py          # 可移植的结构/frontmatter 检查脚本
├── tests/                          # 合成截图测试
├── package.json                    # skill package metadata
├── pyproject.toml                  # Python 测试/运行依赖
└── packaging.allowlist             # 发布/打包 allowlist
```

## 开发

安装 Python 依赖：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install ".[dev]"
```

运行全部本地检查：

```bash
make check PYTHON=.venv/bin/python
```

常用命令：

```bash
make validate PYTHON=.venv/bin/python
make test PYTHON=.venv/bin/python
make skills-list
```

如果本地有官方 `skill-creator` validator，也可以运行：

```bash
python3 path/to/skill-creator/scripts/quick_validate.py skills/compare-ui-to-design
```

## License

MIT
