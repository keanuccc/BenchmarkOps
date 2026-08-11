# BenchmarkOps 演示视频 — STORYBOARD

**Message:** 把“跑一次模型评测”从脚本杂乱、结果难比，变成可复现、可审计、可对比的标准流水线。
**Arc:** Demonstration — 开场立题（工作台真实数据）→ 资源中心（数据集/基准/提示词）→ 实验运行（四要素绑定+异步执行）→ 对比分析（多模型同框）→ 报告与雷达（结论落地）→ 收尾 CTA（品牌承诺）。
**Audience:** 产品/技术负责人、AI 工程师；在项目 README、官网或演示会上观看的 16:9 视频。
**Brand voice:** 冷静、数据驱动、企业级；克制但有力的动效，无旁白、无音乐，靠 UI 动效 + 中文画面文字。
**Why this matters now:** BenchmarkOps 需要一个开箱即用的产品演示，展示真实界面与真实数据，证明“Mock 模式离线即可完整体验”。

**Pacing: Moderate** — 6 beats × 7s，共 40s；子组合 + GSAP 交叉淡化（overlap 0.4s）。
**Format:** 1920×1080 · 30fps
**Audio:** 无旁白、无音乐、无 SFX（离线方案）
**Style basis:** DESIGN.md（深色数据工作台，#D5F36A 强调）

## 时间表（w2h-verify 可解析格式）

| 1 | 0.00s | 7.00s | 7.00s |
| 2 | 6.60s | 13.60s | 7.00s |
| 3 | 13.20s | 20.20s | 7.00s |
| 4 | 19.80s | 26.80s | 7.00s |
| 5 | 26.40s | 33.40s | 7.00s |
| 6 | 33.00s | 40.00s | 7.00s |

## Asset Audit（基于 SVG 文件内容逐一核验）

捕获资产全部为真实站点 SVG（无截图、无字体文件）：
1. `capture/assets/svgs/logo-4cf5203a.svg` — lucide layout-dashboard，品牌侧栏激活图标 → 用作品牌 mark（Beat 1/6）
2. `capture/assets/svgs/svg-dfffb6f1.svg` — lucide database → 数据集图标（Beat 2/3）
3. `capture/assets/svgs/svg-f1e1bf30.svg` — lucide target → 基准图标（Beat 2/3）
4. `capture/assets/svgs/svg-ba1c8960.svg` — lucide wand-sparkles → 提示词图标（Beat 2/3）
5. `capture/assets/svgs/svg-0671e939.svg` — lucide cpu → 模型图标（Beat 3）
6. `capture/assets/svgs/svg-54444bb5.svg` — lucide radar → 行业雷达图标（Beat 5）
7. `capture/assets/svgs/svg-6c058e2e.svg` — lucide sparkles → AI 报告图标（Beat 5）
8. `capture/assets/svgs/svg-61b64d58.svg` — lucide circle-check → 成功/完成标记（Beat 3/4/5）
9. `capture/assets/svgs/svg-20b8ee9b.svg` — lucide file-chart-line → 报告图标（Beat 5 备用）
10. `capture/assets/svgs/svg-850e0e11.svg` — lucide boxes → 资源/项目图标（Beat 2 备用）

其余 `svg-*.svg`（chevron/search/sun/menu/settings 等）为界面小图标，视频不需要，SKIP。

## 渲染引擎限制（全片强制）

- 禁用 `stroke-dasharray` / `scaleX` / `width` / `height` 动画 → 全部用 opacity / x / y / scale / color
- 线/连接条高度至少 4px；进度条用分段块 opacity 逐段亮起，不用宽度动画
- 嵌套元素用 relative 定位；绝对定位只用于画布层
- 确定性：无 `Math.random` / `Date.now` / `setTimeout` / `repeat:-1`；入场 `tl.fromTo()`

---

## BEAT 1 — 开场 · 工作台总览（global 0.00–7.00s，beat-local 0–7s）

**Concept:** 一句话立题：评测不该是黑盒。用工作台真实指标（74% 完成率、35 实验、$1.863 成本、Tencent HY3 100%）证明这是“可解释的进步”。
**Visual:** 近黑画布 + 极淡网格 + 绿色 radial glow 背景；顶部品牌行（layout-dashboard mark + BenchmarkOps wordmark + openrouter chip）；中央两行大标题（第二行 accent）；下方 4 张 stat 卡 + 右侧模型排行卡。
**Composition + Accents:**
- Composed：bg 层 `#090D0F`；网格 `repeating-linear-gradient` 白 2%；glow `radial-gradient(rgba(213,243,106,0.10), transparent 60%)`
- 品牌行：`<img src="capture/assets/svgs/logo-4cf5203a.svg">`（44px，stroke 继承 accent）+ wordmark 34px/700
- 标题：96px/600 Avenir Next，第一行 `#F2F2E9`，第二行 `#D5F36A`；副题 28px `#A2B0AD`
- Stat 卡：4 张 300×190 Surface 卡；数字 56px/700（74% 用 accent），标签 18px muted
- 排行卡：3 行，模型名 24px、100% 24px accent、coverage/failure 16px faint
- Accents：`capture/assets/svgs/logo-4cf5203a.svg`
**Animation Sequence（beat-local）:**
- 0.00–0.45：整场 dolly `fromTo(scene, {scale:1.05},{scale:1, ease:"power1.out"})`
- 0.15：品牌行 `fromTo(y:40, opacity:0 → 0/1, 0.5s, power3.out)`
- 0.35：标题行1 `fromTo(y:50, opacity:0 → 0/1, 0.6s, power4.out)`
- 0.60：标题行2 同上（accent 色）
- 0.90：副题 `fromTo(y:30, opacity:0 → 0/1, 0.5s, power2.out)`
- 1.10–1.90：stat 卡 4 张 `fromTo(y:70, opacity:0, stagger:0.12, back.out(1.4))`
- 1.50/1.80/2.10/2.40：`tl.set` 数字文本（74% / 35 / 26 / $1.863）
- 2.30–3.20：排行卡 3 行 `fromTo(x:60, opacity:0, stagger:0.15, power3.out)`
- 3.40–6.80：持续漂移 — 网格 x ±30（power1.inOut，2.2s yoyo repeat 1）、stat 卡 y ±8（2.4s yoyo repeat 1）、标题 y -6→0
**Beat Timing:** Transition in at 0.00s · GSAP duration 7.0s

---

## BEAT 2 — 资源中心（global 6.60–13.60s，beat-local 0–7s）

**Concept:** 评测的三件套（数据集/基准/提示词）在同一个资源中心里统一管理、版本化、可审计。
**Visual:** 左侧标题区 + 右侧三张竖向卡片，从左到右：数据集 27、基准 25、提示词 25；底部一条能力标签。
**Composition + Accents:**
- Composed：标题 88px/600（“评测三件套，统一管理”），sub 24px muted（“一个工作区，管好所有评测资产”）
- 卡：360×440 Surface 卡，顶部 44px 图标节点（bg `#1C2A2E`、radius 12px），名称 34px/700，数量 26px accent，能力行 20px muted
- 图标：数据集 `<img src="capture/assets/svgs/svg-dfffb6f1.svg">`、基准 `<img src="capture/assets/svgs/svg-f1e1bf30.svg">`、提示词 `<img src="capture/assets/svgs/svg-ba1c8960.svg">`（30px，`filter: invert(0)` 用 CSS 控制色）
- 底部标签：三个 pill（可复现 / 可审计 / 可对比），accent-soft bg + accent 文字
- Accents：上述 3 个真实 SVG
**Animation Sequence（beat-local）:**
- 0.00–0.45：dolly `fromTo(scene,{scale:1.04},{scale:1, ease:"power1.out"})`
- 0.15：标题 `fromTo(y:60, opacity:0 → 0/1, 0.6s, power4.out)`
- 0.55：sub `fromTo(y:24, opacity:0 → 0/1, 0.5s, power2.out)`
- 0.90–2.10：三张卡 `fromTo(x:±90, opacity:0, stagger:0.18, power3.out)`（左卡 x:-90，中卡 x:0 但 y:70，右卡 x:+90）
- 1.30–2.60：图标 `fromTo(y:20, opacity:0, stagger:0.12, back.out(1.5))`
- 2.30–3.80：卡内能力行 `fromTo(y:16, opacity:0, stagger:0.10)`
- 3.90：底部三个 pill 逐段淡入（可复现 → 可审计 → 可对比，0.25s/段）
- 4.50–6.80：parallax — 左卡 y +10、中卡 y -10、右卡 y +10（1.8s yoyo repeat 1），标题 x -12→12（2.2s yoyo repeat 1）
**Beat Timing:** Transition in at 6.60s · GSAP duration 7.0s

---

## BEAT 3 — 实验运行（global 13.20–20.20s，beat-local 0–7s）

**Concept:** 一次评测 = 数据集 + 基准 + 提示词 + 模型，四要素绑定后异步执行，实时看进度与指标。
**Visual:** 上方标题；中部四节点（图标+名称）→ 箭头 → 运行卡；运行卡内状态 chip、10 段进度条、3 项指标。
**Composition + Accents:**
- Composed：标题 84px/600（“四要素绑定，一键异步评测”）
- 节点：4 个 200×120 Surface 卡，44px 图标节点 + 24px 名称；连线 4px 高、`rgba(213,243,106,0.35)` 的横向条
- 图标：`svg-dfffb6f1.svg`（数据集）、`svg-f1e1bf30.svg`（基准）、`svg-ba1c8960.svg`（提示词）、`svg-0671e939.svg`（模型）
- 运行卡：560×300 Surface 卡；标题 28px（Run: Tencent HY3 (free)）；状态 chip（排队→运行中→已完成，`tl.set` 文本，单一中性 chip）；10 段进度块（每段 40×14px，radius 7px，间隔 8px，静态宽度，opacity 0 起始）；指标 24px（准确率 100% / 延迟 2.1s / 成本 $0.00）
- Accents：`capture/assets/svgs/svg-61b64d58.svg`（circle-check，40px，accent）
**Animation Sequence（beat-local）:**
- 0.00–0.45：dolly `fromTo(scene,{scale:1.04},{scale:1, ease:"power1.out"})`
- 0.15：标题 `fromTo(y:56, opacity:0 → 0/1, 0.6s, power4.out)`
- 0.70–1.90：四节点 `fromTo(y:60, opacity:0, stagger:0.15, back.out(1.5))`
- 1.20–2.20：节点间连线（3 条 4px 横条）`fromTo(opacity:0→1, stagger:0.12)`
- 2.20：运行卡 `fromTo(y:50, opacity:0 → 0/1, 0.6s, power3.out)`
- 2.70–4.20：10 段进度块依次 `fromTo(opacity:0→1, 每段 0.15s)`
- 2.70 / 3.40 / 4.00：状态 chip `tl.set`（排队 → 运行中 → 已完成）
- 3.00 / 3.50 / 4.00：指标 `tl.set` 数值（准确率 100% / 延迟 2.1s / 成本 $0.00）
- 4.10：circle-check `fromTo(y:20, opacity:0 → 1, 0.4s, back.out(1.6))`
- 4.50–6.80：节点 y 交替 ±10（1.8s yoyo repeat 1），chip opacity 0.75↔1（1.2s yoyo repeat 1）
**Beat Timing:** Transition in at 13.20s · GSAP duration 7.0s

---

## BEAT 4 — 对比分析（global 19.80–26.80s，beat-local 0–7s）

**Concept:** 同一数据集上多模型同框对比，不只比分数，还比延迟与成本，让决策有据可依。
**Visual:** 上方标题；下方 4 行模型对比：模型名 + 横向条（静态宽度，分段 opacity 亮起）+ 准确率/延迟/成本三列数值；GPT-4o mini 行高亮为“最优性价比”。
**Composition + Accents:**
- Composed：标题 88px/600（“同框对比，决策有据”）
- 行：4 行 Surface 行卡（高 96px，radius 16px，border `#27383C`）；横向条为静态宽度块（用 6 段 28×16px 块拼接，opacity 0 起始，颜色按数值：100%→`#77D79A`，87%→`#F2C56D`）；数值 28px/700（准确率 accent，延迟/成本 muted）
- 数据：Tencent HY3 (free) 100% · 2.1s · $0.000；GPT-4o mini 100% · 0.22s · $0.014；Claude 3.5 Haiku 100% · 0.13s · $0.078；DeepSeek V3 87% · 3.0s · $0.000
- 高亮：GPT-4o mini 行 border `#D5F36A` + 角标“最优性价比”pill
- Accents：`capture/assets/svgs/svg-61b64d58.svg`（高亮行前勾选标记，32px）
**Animation Sequence（beat-local）:**
- 0.00–0.45：dolly `fromTo(scene,{scale:1.05},{scale:1, ease:"power1.out"})`
- 0.15：标题 `fromTo(y:56, opacity:0 → 0/1, 0.6s, power4.out)`
- 0.80–2.20：4 行 `fromTo(y:50, opacity:0, stagger:0.15, power3.out)`
- 1.10–2.80：每行 6 段条块依次 `fromTo(opacity:0→1, 每段 0.12s)`，行间 stagger 0.3
- 1.60–3.40：数值 `tl.set`（100 / 100 / 100 / 87，0.5s/行）
- 3.20：GPT-4o mini 行 border accent `tl.set` + 勾选标记 `fromTo(y:16, opacity:0→1, 0.4s)`
- 3.60：“最优性价比”pill `fromTo(y:16, opacity:0 → 1, 0.45s, back.out(1.6))`
- 4.00–6.80：行 y 交替 ±8（2.0s yoyo repeat 1），标题 x ±12（2.4s yoyo repeat 1）
**Beat Timing:** Transition in at 19.80s · GSAP duration 7.0s

---

## BEAT 5 — 报告与行业雷达（global 26.40–33.40s，beat-local 0–7s）

**Concept:** 从结果到结论：AI 生成结构化报告；行业雷达把单次实验放进全局 KPI 视图。
**Visual:** 左报告卡 + 右雷达卡；报告卡内 Markdown 行逐行打出，雷达卡内同心环与多边形淡入。
**Composition + Accents:**
- Composed：标题 84px/600（“从结果到结论，一步到位”）
- 报告卡（600×480 Surface 卡）：头部 sparkles 图标 + “AI 报告”34px；6 行等宽字体 24px 打字行（# 评测报告 / 实验：Run: Tencent HY3 (free) / 准确率：100% / 成本：$0.00 / 结论：表现稳定，建议上线）；导出 pill：Markdown / PDF
- 雷达卡（620×480 Surface 卡）：radar 图标 + “行业雷达”34px；3 个同心圆（border 4px `rgba(255,255,255,0.10)`，半径 80/150/220px，静态；4px 规避渲染吞线）+ 6 轴标签（准确率/延迟/成本/覆盖率/失败率/令牌）+ 中央多边形（静态 path，`rgba(213,243,106,0.30)` fill + `#D5F36A` 4px stroke）+ KPI chip 3 个（供应商准确率 100% / 覆盖率 100% / 失败率 0%）
- Accents：`capture/assets/svgs/svg-6c058e2e.svg`、`capture/assets/svgs/svg-54444bb5.svg`
**Animation Sequence（beat-local）:**
- 0.00–0.45：dolly `fromTo(scene,{scale:1.04},{scale:1, ease:"power1.out"})`
- 0.15：标题 `fromTo(y:56, opacity:0 → 0/1, 0.6s, power4.out)`
- 0.80：左卡 `fromTo(x:-80, opacity:0 → 0/1, 0.6s, power3.out)`；右卡 `fromTo(x:80, opacity:0 → 0/1, 0.6s, power3.out)`
- 1.20–2.70：报告行用 `tl.set` 逐行打字（6 行，0.25s/行，等宽字体）
- 1.60–2.60：3 个同心环 `fromTo(opacity:0→1, stagger:0.18)` + 轴标签 `fromTo(y:14, opacity:0, stagger:0.08)`
- 2.60：多边形 `fromTo(opacity:0→1, 0.5s, power2.out)`
- 3.40–4.20：KPI chips `fromTo(y:18, opacity:0, stagger:0.12)`；导出 pill 同上（3.6 起）
- 4.50–6.80：左卡 y +10 / 右卡 y -10（2.0s yoyo repeat 1）
**Beat Timing:** Transition in at 26.40s · GSAP duration 7.0s

---

## BEAT 6 — 收尾 CTA（global 33.00–40.00s，beat-local 0–7s）

**Concept:** 用品牌承诺收束全片：可复现、可审计、可对比，然后给出唯一行动——“开始一次评测”。
**Visual:** 居中品牌 mark + wordmark；三枚承诺 pill；主 CTA 按钮；底部一行技术背书。
**Composition + Accents:**
- Composed：bg 同 Beat 1（`#090D0F` + 网格 + accent glow）
- mark：`<img src="capture/assets/svgs/logo-4cf5203a.svg">`（88px，accent stroke）
- wordmark：96px/700（BenchmarkOps）；tagline 36px muted（把每一次模型迭代，变成可解释的进步）
- 三 pill：可复现 / 可审计 / 可对比（accent-soft bg + accent 文字 26px/700）
- CTA：Primary Button（`#D5F36A` / `#10150E`，32px，padding 20px 44px，radius 12px）
- footer：20px faint（企业级 AI 评测与基准运维平台 · FastAPI · Next.js）
- Accents：`capture/assets/svgs/logo-4cf5203a.svg`
**Animation Sequence（beat-local）:**
- 0.00–0.50：dolly `fromTo(scene,{scale:1.05},{scale:1, ease:"power1.out"})`
- 0.20：mark `fromTo(y:60, opacity:0 → 0/1, 0.6s, back.out(1.4))`
- 0.55：wordmark `fromTo(y:40, opacity:0 → 0/1, 0.6s, power4.out)`
- 1.00：tagline `fromTo(y:24, opacity:0 → 0/1, 0.5s, power2.out)`
- 1.30–2.30：三 pill `fromTo(y:40, opacity:0, stagger:0.14, back.out(1.5))`
- 2.50：CTA `fromTo(y:50, opacity:0 → 0/1, 0.6s, power3.out)`
- 3.00–5.40：CTA 呼吸 `fromTo(opacity:0.85→1, 1.2s, yoyo repeat 2)`
- 3.30：footer `fromTo(y:18, opacity:0 → 0/1, 0.5s)`
- 4.20–6.80：wordmark y -8→0、pill x ±10（2.0s yoyo repeat 1）、glow opacity 0.5↔0.75（2.4s yoyo repeat 1）
**Beat Timing:** Transition in at 33.00s · GSAP duration 7.0s

---

## 生产架构

```
my-video/
├── index.html                    # 根编排：6 个 scene host + s-end，GSAP opacity 交叉淡化
├── DESIGN.md / STORYBOARD.md / SCRIPT.md
├── capture/                      # 捕获的品牌资产（svgs/ + extracted/）
└── compositions/
    ├── beat-1-overview.html
    ├── beat-2-assets.html
    ├── beat-3-experiment.html
    ├── beat-4-compare.html
    ├── beat-5-report-radar.html
    └── beat-6-cta.html
```
