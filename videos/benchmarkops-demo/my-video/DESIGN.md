# BenchmarkOps — DESIGN.md（品牌速查）

> 数据来源：`capture/extracted/tokens.json` + `capture/extracted/design-styles.json`（真实捕获值，禁止凭记忆改色）。

## 1. Visual Theme

BenchmarkOps 是深色优先的企业级 AI 评测平台：近黑画布 `#090D0F` 打底，面板 `#101719` 浮起，酸橙绿 `#D5F36A` 是唯一的行动/强调色。界面靠细网格线（白 2% 透明度）与极淡的绿色斜向渐变制造“工程感”，而不是靠高光或玻璃拟态。文字层级靠字号与字重，不靠颜色变化；元信息一律 `#A2B0AD`。整体气质是冷静、可量化的数据工作台：每一次渲染都必须像产品截图一样精确。

## 2. Quick Reference

### Colors

- **Canvas** `#090D0F` — 页面/画布主背景
- **Surface** `#101719` — 卡片/面板背景（带 `linear-gradient(145deg, rgba(255,255,255,0.035), rgba(0,0,0,0) 38%)`）
- **Surface-2** `#172225` — 次级面板、表头
- **Surface-3 / Chip bg** `#1C2A2E` — 芯片/分组底色
- **Sidebar** `#0B1113` — 侧栏背景
- **Text** `#F2F2E9` — 主文字（在 Canvas/Surface 上约 17.5:1 ✅）
- **Text Muted** `#A2B0AD` — 次级文字（在 Canvas 上约 8.4:1 ✅；在 Surface 上约 7.5:1 ✅）
- **Text Faint** `#667875` — 弱元信息（仅在非关键标签使用）
- **Accent** `#D5F36A` — CTA、强调、高亮；配深字 `#10150E`（约 13:1 ✅）；禁止做正文颜色
- **Accent Soft** `rgba(213,243,106,0.12)` — 选中/激活底
- **OK** `#77D79A` — 成功/已完成；配深底可读
- **Warn** `#F2C56D` — 进行中/待处理
- **Info** `#89C8FF` — 信息/模型
- **Coral** `#F49B74` — 次要强调/图表点缀
- **Bad** `#FF8F8F` — 失败/错误
- **Border** `#27383C` — 卡片描边；**Border Soft** `#1C2A2E` — 细分隔线
- **Grid line** `rgba(255,255,255,0.018)` — 背景网格

### Fonts

- **Display / 标题**：`"Avenir Next"`（600/700），中文回退 `"PingFang SC", "Microsoft YaHei", sans-serif`
  - `@font-face { font-family: "Avenir Next"; src: local("Avenir Next"); }`（系统字体，捕获无 woff2 文件）
- **Mono / 代码与元信息**：`"SFMono-Regular"`，回退 `Consolas, monospace`
  - `@font-face { font-family: "SFMono-Regular"; src: local("SFMono-Regular"); }`
- 视频内最小字号：标题 ≥80px，正文 ≥20px，弱标签 ≥16px

### Component Stylings

#### Primary Button（开始新评测）
- Background `#D5F36A`；Text `#10150E`；Font Avenir Next 600 32px；Padding `20px 44px`；Radius `12px`；Border `1px solid #27383C`

#### Card
- Background `#101719` + 顶部 3.5% 白渐变；Border `1px solid #27383C`；Radius `16px`；Padding `20px`；Shadow `0 20px 55px rgba(0,0,0,0.22), 0 2px 8px rgba(0,0,0,0.22)`

#### Chip / Status
- Radius `999px`；Padding `8px 18px`；Font 18px/700
- `openrouter`：bg `#1C2A2E`、text `#D5F36A`
- `active / 已完成`：bg `rgba(119,215,154,0.14)`、text `#77D79A`、border 透明
- `运行中`：bg `rgba(242,197,109,0.14)`、text `#F2C56D`
- `待运行`：bg `rgba(137,200,255,0.14)`、text `#89C8FF`

#### Stat Cell
- Surface 卡片内：数字 56px/700 Avenir Next，标签 18px `#A2B0AD`；强调数字用 `#D5F36A`

#### Node / 流程节点
- 圆形/圆角方块 44px，bg `#1C2A2E`，icon 用捕获的真实 SVG（stroke 继承 `#D5F36A`）

## 4. Spacing & Layout

**Base unit:** `4px`；视频画布 1920×1080。
- 卡片间距 `20–24px`；卡片内边距 `20px`；标题区下边距 `40px`
- Radius：`8px`（小元素）、`12px`（按钮）、`16px`（卡片）、`999px`（芯片）
- 布局优先 flex/grid + 固定画布居中；装饰层可用 absolute，但子元素用 relative，避免嵌套绝对定位偏移

## 5. Iteration Guide

1. 画布永远用 `#090D0F`，卡片用 `#101719` + `1px #27383C` 描边 + `16px` 圆角；其他底色一律不出现。
2. CTA/强调只允许 `#D5F36A`，按钮文字必须 `#10150E`；正文用 `#F2F2E9`，次级用 `#A2B0AD`。
3. 标题用 Avenir Next 600/700；中文回退 PingFang SC / Microsoft YaHei；元信息用 SFMono。
4. 动画只用 opacity / x / y / scale / rotation / color，**禁止 stroke-dasharray、scaleX、width、height 动画**；2px 细线禁用，连线至少 4px。
5. 确定性：无 `Math.random` / `Date.now` / `setTimeout` / `repeat:-1`；入场一律 `tl.fromTo()`。
6. 每个 scene 顶部放 Avenir Next 与 SFMono 的 `@font-face local()` 块，满足 lint 且字体一致。
7. 场景内元素 id 全局唯一（前缀 `b1-`/`b2-`…）；`data-composition-id` 与 `window.__timelines` key 三处一致。
8. 每个 beat 至少一个 headline ≥80px；动画事件必须铺满整段（最后事件 ≥ 70% 时长）。
