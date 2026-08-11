# 进阶链路测试报告（第二轮：继续跑，继续测试优化）

> 日期：2026-08-12 · 平台：BenchmarkOps（本地运行）· 模型：Mock Provider

## 1. 测试范围

在第一轮五场景（qa/classification/coding/agent/generation）基础上，继续验证
平台更深的链路：

| 分组 | 链路 | 脚本 |
|------|------|------|
| A | 多轮对话 + few-shot（structured_chat）、敏感字段脱敏、数据集版本化、异步导入、多答案/部分得分 | `backend/scripts/run_advanced_a.py` |
| B | 并发实验、取消运行、Webhook 真实触发、定时报告真实调度、llm_judge_rubric | `backend/scripts/run_advanced_b.py` |

## 2. 结果汇总

### 链路 A：21/21 PASS

- 结构化对话：`messages`/`examples` 随行保存、渲染链路正常，实验完成且算术样本命中（66.7%）；
- 敏感字段脱敏：字段级（`phone` → `[REDACTED]`）+ 文本级（问题文本内嵌手机号/邮箱也会被掩码）；预览与实验结果（`mask_sensitive=true`）均生效；
- 数据集版本化：v1 → v2（8 行）→ 回滚激活 v1（5 行），版本列表与行数一致；
- 异步导入：任务终态 `succeeded`，数据集可见；
- 多答案：`multi_answer=set + partial_credit` 生效（命中一半得 0.5，未命中 0）。

### 链路 B：14/14 PASS

- 并发：3 个实验同时提交，1.1s 全部完成（行级+实验级并发生效），无数据库锁错误；
- 取消：慢速实验运行中取消成功，状态 `cancelled` 且结果被清空；
- Webhook：实验完成事件真实送达本地接收端（含准确率载荷）；
- 定时报告：把 `next_run_at` 置为过去后，后台调度器在 60s 周期内自动执行（`last_status=success`）；
- llm_judge_rubric：Mock judge 输出非 JSON 时平台未崩溃，实验以 `partial` 收尾并保留逐行结果。

## 3. 本轮发现并修复的问题

### 3.1 【真实 Bug】取消实验接口返回 500（已修复）

`POST /experiments/{id}/cancel` 在实验运行中调用时返回 500：

```text
sqlalchemy.exc.InvalidRequestError: Instance '<Experiment ...>' is not persistent within this Session
```

根因：路由先用请求 session 取出 `exp` 对象，再打开新 session 调用
`repo.update(exp, ...)`，跨 session 更新 ORM 对象导致 `refresh` 抛异常。

修复：`backend/app/api/v1/routes/experiments.py` 取消端点改为在新 session 内
重新获取对象并校验状态后再更新。修复后取消返回 200、状态变为 `cancelled`、
结果被清空（手动复现验证 + 脚本回归）。

### 3.2 【增强】敏感字段脱敏升级为文本级 PII 掩码（已实现）

原实现只对"声明为敏感字段的键"整值替换，问题文本里内嵌的手机号/邮箱会
原样泄漏到预览、实验结果、失败案例与报告中。

增强：`backend/app/services/redaction.py`
- 字段级：声明字段 → `[REDACTED]`（递归支持 dict/list）；
- 文本级：任何字符串值中的手机号（`1[3-9]\d{9}`）与邮箱会被掩码；
- 语义保持：未声明敏感字段的数据集原样通过（不改变既有契约）。

统一接入所有输出路径：
- 实验结果 `mask_sensitive=true`（含模型输出 output，新增）；
- 失败案例与实验对比（`analytics_service`，新增）；
- 报告生成上下文（`report/generator.build_context`，新增）。

### 3.3 【确认】非问题项

- 异步导入任务终态为 `succeeded`（脚本枚举已兼容）；
- 实验结果脱敏是显式参数 `mask_sensitive=true`（前端分页接口已正确携带），
  默认返回原始数据供内部使用——属设计而非缺陷。

## 4. 交付物

- 测试脚本：`backend/scripts/run_advanced_a.py`、`backend/scripts/run_advanced_b.py`
  （可直接复用，数据自造、Mock 模型、临时模型自清理）；
- 单元测试：`backend/tests/test_redaction_pii.py`（新增 6 项）；
- 全量回归：`pytest` 456 passed / 7 skipped / 11 deselected。

---

## 第三轮：多租户 / prep 工作台 / 压力边界 / 审计（22/22 PASS）

> 日期：2026-08-12 · 脚本：`backend/scripts/run_advanced_c.py`

### 3-1 多租户端到端（11 项）

- 组织 A/B 各自创建项目、数据集互不可见；
- 跨组织读/写返回 404；
- viewer Key 写操作 403、读自己组织正常；
- B 组织可正常创建自己的项目。

### 3-2 prep 准备工作台（3 项）

- `POST /prep/analyze`：原始文件列分析与映射建议；
- `POST /prep/transform`：按配置输出平台契约与拆分预览；
- `POST /prep/dry-run`：内存中对样本行直接评分（mock provider），不落库。

### 3-3 压力与边界（6 项）

- 200 行数据集上传 + 实验运行完成（`cells_done=200`）；
- 空文件拒绝（422）；
- 无效 JSONL 拒绝（422）；
- 40 万行超行数上限拒绝（422）；
- 上下文溢出（小 context 模型 + 超长输入）被逐行标记 `context_overflow`，
  实验以 `partial` 收尾而非崩溃。

### 3-4 审计日志（2 项）

- 数据集上传后 `GET /datasets/{id}/audit` 返回事件；
- 事件 action 为 `create`（平台对上传/导入统一记为 create）。

### 本轮结论

多租户隔离、prep 工作台、压力与边界、审计链路全部正常，未发现新的平台级
缺陷。累计三轮进阶测试：A 21/21、B 14/14、C 22/22，全量回归 456 passed。

---

## 第四轮：PDF 中文渲染 / 删除完整性 / 错误响应 / 500 行压力（12/12 PASS）

> 日期：2026-08-12 · 脚本：`backend/scripts/run_advanced_d.py`

### 4-1 【真实 Bug 已修复】PDF 报告中文全部乱码

此前只验证了 PDF 文件头，未检查内容；本轮用 pypdf 提取文本发现报告里的中文
全部变成方块（`■`）。

根因：reportlab 内置 Helvetica 不支持 CJK，导出器未注册中文字体。

修复（`backend/app/report/exporter.py`）：
- 启动时自动注册系统中文字体（Windows：微软雅黑/黑体/宋体；Linux：Noto Sans
  CJK / 文泉驿），找不到时回退 Helvetica（测试自动跳过中文断言）；
- 标题、正文、表格、代码块、行内代码全部使用已注册的 CJK 字体。

验证：真实报告重新导出后，`pypdf` 可提取出"评测报告""准确率"等中文，无方块；
新增单测 `test_pdf_chinese_renders_with_cjk_font`。

### 4-2 删除完整性（6 项）

- 删除项目后：项目/数据集/实验/报告均 404；
- 数据库 8 张相关表（datasets、datasets_rows、benchmarks、prompts、experiments、
  experiment_results、reports、import_jobs）零残留行（无孤儿数据）。

### 4-3 错误响应一致性（3 项）

- 404 / 422 / 401 均返回统一结构 `{"error": {"code", "message"}}`；
- 读接口不强制鉴权（设计），错误 Key 在写接口上返回 401。

### 4-4 500 行压力（2 项）

- 500 行数据集上传 + 实验 1.0s 完成、500 行结果齐全；
- 报告生成 + PDF 中文导出端到端正常。

### 累计

四轮进阶测试：A 21/21、B 14/14、C 22/22、D 12/12；全量回归
**457 passed / 7 skipped / 11 deselected**。发现并修复 3 个真实问题：
取消接口 500（第二轮）、敏感数据旁路泄漏与文本级 PII（第二轮）、PDF 中文乱码
（第四轮）。

---

## 第五轮：真实浏览器前端 E2E（Playwright，5/5 PASS）+ SSE 崩溃修复

> 日期：2026-08-12 · 环境：8001 Mock 后端 + 3001 前端（独立编译缓存）

### 5-1 【真实 Bug 已修复】实验详情页永远 Loading（SSE datetime 崩溃）

用 Playwright 打开实验详情页时页面主体空白、只显示导航。排查链路：

1. 详情页只依赖 SSE 推送初始化，没有初始数据请求；
2. SSE 对已完成实验应推送一条 terminal progress 事件，但实际返回
   `event: error / stream error`；
3. 根因：`sse.py` 中 `json.dumps(data)` 遇到 `updated_at`（datetime 对象）
   抛 `TypeError: Object of type datetime is not JSON serializable`，
   生成器走异常分支发 stream error，前端收不到事件、永远 Loading。

修复：
- 后端 `sse.py`：`updated_at` 序列化前转 `isoformat()`；
- 前端实验详情页：`useEffect` 先执行一次初始 `refresh()`，不再完全依赖 SSE。

验证：curl 已完成实验的 stream 返回完整 progress 事件（含 ISO 时间）；
新增单测 `test_sse_completed_experiment_emits_json_progress`。

### 5-2 Playwright 前端 E2E（5/5 PASS）

复用仓库 `frontend/e2e`（Python + Playwright）：

- `test_full_e2e_flow`：初始化模型 → 项目 → 数据集 → 基准 → 提示词 → 实验
  → 运行 → 结果 → 对比 → 报告导出，真实浏览器全流程 PASS；
- `test_project_create_validation`：空名称不创建；
- `test_upload_rejects_too_many_rows`：超行数上传在 UI 上被拒绝；
- `test_experiment_requires_all_fields`：实验表单必填校验；
- `test_experiment_run_writes_single_batch`：运行只写一批结果（无 CAS 重复）。

测试资产修复（非平台缺陷）：
- `helpers.py` 导航改用 `a[href=...]` 定位（宽泛文本会点到统计卡片）；
- 实验详情文案断言改为分页格式"逐行结果"；
- 两个 dev server 共用一个 `.next` 缓存导致页面 chunk 指向旧后端——改为
  独立清理缓存后启动测试实例。

### 累计

五轮测试：25/25、A 21/21、B 14/14、C 22/22、D 12/12、前端 E2E 5/5。
发现并修复 4 个真实问题：取消接口 500、敏感数据旁路泄漏、PDF 中文乱码、
SSE datetime 崩溃。全量回归 **458 passed / 7 skipped / 11 deselected**。

---

## 第六轮：Qiniu 400 真实链路诊断与修复（AI 报告恢复）

> 日期：2026-08-12

### 6-1 根因

此前 AI 报告一直回退模板，日志显示七牛网关返回 400。直接调用七牛 API 逐模型
探测：

| 模型 | 结果 |
|------|------|
| `deepseek/deepseek-v4-flash`、`deepseek-v3`、`deepseek-v4-flash` | 200（Key 有效） |
| `glm-4`、`qwen-max` | 400 `no available channels for model` |

真正的根因：AI 报告默认模型是 OpenRouter 的 `openai/gpt-4o-mini`，而默认
Provider 是七牛——把 OpenRouter 模型名发给七牛，必然 400。**Key 本身有效**。

### 6-2 修复

`backend/app/services/report_service.py` 的 `resolve_report_model_id()` 改为
按实际 Provider 选择默认模型：
- 七牛 → `deepseek/deepseek-v4-flash`（实测可用）；
- OpenRouter → 保持 `openai/gpt-4o-mini`；
- `REPORT_MODEL_ID` 显式配置始终优先。

### 6-3 验证

- 真实环境生成报告：`generated_by=qiniu`，内容为 AI 生成的完整报告
  （执行摘要、准确率 89.17%、延迟/成本分析），不再是模板回退；
- 新增单测 `test_report_model_resolution.py`（3 项），更新既有断言；
- 全量回归 **461 passed / 7 skipped / 11 deselected**。

提示：七牛通道下实验模型同样只能使用其平台模型（如
`deepseek/deepseek-v4-flash`）；选其他 seed 模型会返回 400，属于模型名
不匹配而非 Key 问题。

---

## 第七轮：真实 Provider 评测链路 + 新功能前端 UI 冒烟

> 日期：2026-08-12 · 脚本：backend/scripts/run_real_provider.py

### 7-1 真实模型实验（10 条 QA，实际调用网关）

| Provider | 模型 | 结果 |
|----------|------|------|
| Qiniu | deepseek/deepseek-v4-flash | completed，80%，0 错误，\ |
| OpenRouter | openai/gpt-4o-mini | completed，50%，0 错误，\.0559 |

首次验证 OpenRouter Key 可用；逐行输出、成本、令牌、延迟记录正常。
（准确率差异来自期望答案的表述匹配口径，非链路问题。）

### 7-2 新功能前端 UI 冒烟（Playwright，真实 3000/8000）

- 设置页：组织与 API Key（多租户）、创建新组织、使用已有 Key 区块渲染正常；
- 项目详情 → 报告页签：定时报告（持续评测订阅）与 Webhook（CI/CD 回调）面板渲染正常。

### 本轮结论

未发现新的平台缺陷。累计七轮：Mock/真实 Provider、五场景、十类进阶链路、
浏览器 E2E 与 UI 冒烟全部通过；真实问题累计修复 5 个。

---

## 第八轮：seed 模型网关路由修复 + CLI 端到端验证

> 日期：2026-08-12

### 8-1 【真实 Bug 已修复】seed 模型在 qiniu 默认网关下全部 400

复现：seed 的 OpenRouter 风格模型（openai/gpt-4o-mini、deepseek/deepseek-chat、
claude-3.5-sonnet 等）provider 为 legacy 名称（openai/anthropic/google...），
这些不是平台已知网关，会被归一化到默认网关 qiniu；把 OpenRouter 模型名发给
七牛必然 400（逐模型探测确认）。

修复：
- model_service.py seed 模型 provider 全部改为 openrouter（模型 id 本身
  就是 OpenRouter 风格）；
- 
epair_integrity.py _PROVIDER_BY_PREFIX 同步映射到 openrouter，
  保证快照修复/去重逻辑一致；
- 新增 scripts/fix_model_providers.py（dry-run 默认，--apply 生效）修复存量
  legacy provider 模型；被旧实验引用的重复 legacy 模型受引用保护保留（可停用）。

验证：修复后 DeepSeek V3（openrouter）真实实验 completed（33.3%，无 400）；
存量 6/8 legacy 模型已修复，全量回归 461 passed。

### 8-2 CLI 端到端验证（真实服务）

| 命令 | 结果 |
|------|------|
| bmops run <id> --wait | 完成并输出结果 JSON，退出 0 |
| bmops check-regression（低于基线） | 正确报 REGRESSION，退出码 1 |
| bmops check-regression（高于基线） | PASS，退出码 0 |
| bmops export-report --format pdf | 导出 131KB PDF |
| bmops pack apply 金融客服包 | 创建项目 + 3 基准 + 3 提示词 |
| bmops webhook test | 正常执行并返回送达结果 |

### 本轮结论

seed 模型网关路由是真实环境 400 的又一根因，已修复；CLI 六条命令全部可用。
累计八轮，真实问题修复 6 个。

---

## 第九轮：数据格式边界（CSV/TSV/XLSX）+ 答案别名修复（13/13 PASS）

> 日期：2026-08-12 · 脚本：backend/scripts/run_advanced_e.py

### 9-1 数据格式端到端（CSV/TSV/XLSX 全过）

- CSV：含中文、BOM、引号内逗号；TSV：中文列；XLSX：openpyxl 生成；
  三种格式上传后行数正确，实验全部 completed 且结果行数一致。
- 首次实测平台宣称的 CSV/TSV/XLSX 支持，均正常。

### 9-2 【真实 Bug 已修复】multi_answer 模式下 aliases 被忽略

现象：answer_policy 配置 aliases（如 {"巴黎": ["Paris", "paris"]}），模型输出
别名 Paris 仍判错。

根因：exact_match_ci 的 multi_answer=set/all 分支只用 required 答案匹配，
完全没有使用 aliases 候选；且最终判定用 parts==required，别名命中也被否决。

修复（backend/app/evaluation/metrics.py）：
- 新增 _alias_sets()：规范化 aliases（dict 映射或扁平列表）；
- set/all 分支按 required 答案逐一检查其别名命中；
- 最终判定改为基于命中数（matched == len(required)），别名命中计入。

验证：单测 9 项全过；端到端别名实验 scores=[0.0, 1.0, 1.0]（Paris 命中
"巴黎"）；all+partial_credit 组合 0.5 正确。

### 9-3 模型停用行为

停用（is_active=false）模型仍可创建实验（快照语义），运行有明确终态——
行为合理，未修改。

### 本轮结论

数据格式边界全过；修复第 7 个真实问题（multi_answer aliases）。全量回归
464 passed / 7 skipped / 11 deselected。

---

## 第十轮：构建回归 / 模型目录 / 定时 PDF / 1000 行压力（全部通过）

> 日期：2026-08-12

### 10-1 前端生产构建

SSE 与详情页初始加载修复后，npm run build 通过（所有页面静态/动态渲染正常）。

### 10-2 模型目录与预设

- GET /models/presets：8 个内置模型，provider 全部为 openrouter（seed 修复生效，
  legacy provider 为 0）；
- GET /models/openrouter：真实目录 405 个模型（网络链路正常）。

### 10-3 定时报告 PDF

创建 format=pdf 的定时报告 → 立即运行成功（last_status=success）→ 生成的报告
导出 PDF 127KB（%PDF 头正确）。发现一个已知小项：定时报告的 format 字段目前
仅记录、不参与生成（报告始终以 Markdown 存储，导出时由端点按需转 PDF/HTML）。

### 10-4 1000 行压力

1000 行数据集上传（row_count=1000）+ 实验 completed、1000/1000 结果、约 1.0s
（行级并发下吞吐约 1000 行/秒，Mock 模型）。

### 本轮结论

未发现新的平台缺陷（记录 1 个已知小项：定时报告 format 未参与生成）。
累计十轮，真实问题修复 7 个，全量回归 464 passed。

---

## 第十一轮：OpenRouter AI 报告 / DB 备份路由 Bug 修复 / prep CSV / 并发 10

> 日期：2026-08-12

### 11-1 OpenRouter AI 报告真实生成

独立进程将 report_provider=openrouter、report_model_id=openai/gpt-4o-mini 后
生成真实 AI 报告成功（内容完整）。发现小 bug：generated_by 之前固定用
active_provider_name()（默认网关），OpenRouter 生成也被标成 qiniu；已改为
实际 provider.name，验证 generated_by=openrouter。

### 11-2 【真实 Bug 已修复】/db/backup/list 被 /db/backup/{filename} 遮蔽

GET /db/backup/list 返回 400 "Invalid backup filename"——因为
`/backup/{filename}` 路由注册在 `/backup/list` 之前，FastAPI 按注册顺序把
"list" 当成文件名。修复：list 端点移到 download 之前注册。验证：list 200
返回备份列表，download 200，delete 204；新增路由回归单测。

### 11-3 prep 对 CSV 分析/转换

prep/analyze 与 transform 处理含中文/BOM 的 CSV 正常（列分析 + 2 行预览）。

### 11-4 并发 10 实验

10 个实验同时提交，1.6s 全部 completed（100 行/实验），无数据库锁错误。

### 本轮结论

修复第 8 个真实问题（backup/list 路由遮蔽）与第 9 个小问题（generated_by
标记）。全量回归 465 passed / 7 skipped / 11 deselected。

---

## 第十二轮：API_TOKEN 全开模式端到端 + OpenAPI 完整性

> 日期：2026-08-12

### 12-1 API_TOKEN 鉴权端到端（带 token 的临时后端，8002）

- 读接口无 token 开放；写接口无 token / 错 token 均 401，正确 token 201；
- 组织 API Key 与全局 token 共存：org key 可写、错误 token 仍 401；
- SSE 带 token 可连、错 token 401。

### 12-2 【真实 Bug 已修复】API_TOKEN 模式下创建组织可匿名调用

修复前 POST /organizations/ 无鉴权，配置 API_TOKEN 后仍可匿名创建组织
（绕过鉴权的写操作）。修复：创建组织端点挂 require_auth——demo 无 token
模式保持开放（多租户/鉴权单测 11 项通过），token 模式下必须凭证。

### 12-3 OpenAPI 完整性

/openapi.json 共 86 条路径；organizations、scheduled-reports、webhooks、
db/backup/list、model-routing 全部注册正确、无路由冲突。

### 本轮结论

修复第 9 个真实问题（组织创建匿名写）。全量回归 465 passed / 7 skipped /
11 deselected。累计 12 轮：修复 9 个真实问题 + 2 个小问题。

---

## 第十三轮：测试残留清理 + 前端 E2E 最终回归（5/5 PASS）

> 日期：2026-08-12

### 13-1 数据库清理

删除 11 个未被实验引用的临时 Mock 模型（测试残留）；被引用模型保留（引用
保护设计）。

### 13-2 前端 E2E 最终回归

在 seed 模型 provider 改为 openrouter 后，E2E 的 Mock 后端（无 key）下实验
无法使用 seed 模型（合理行为：模型需要真实 key）。E2E 测试适配为显式创建
offline mock 模型并在实验表单中选择它。适配后 5/5 PASS（全流程 + 4 个边界）。

### 13-3 服务状态

8000 后端与 3000 前端恢复运行正常；临时环境全部清理。

### 本轮结论

最终回归健康：后端 465 passed（上轮确认，本轮无后端改动），前端 E2E 5/5，
服务正常。累计十三轮，真实问题修复 9 个 + 小问题 2 个。

---

## 第十四轮：新功能前端真实交互（组织管理/定时报告/Webhook，3/3 PASS）

> 日期：2026-08-12 · 脚本：frontend/e2e/test_new_features.py

### 14-1 组织管理全流程

设置页创建组织 → Owner Key 明文展示（bmops_ 前缀）→ 组织信息显示 →
在组织下通过 UI 创建项目成功 → localStorage 中 org key 已保存。

### 14-2 定时报告面板

项目报告页签：填写名称、勾选实验、创建 → 列表出现条目（创建按钮与
checkbox 均需在面板内定位，页面存在多个同名控件）。

### 14-3 Webhook 面板

创建 Webhook（名称/URL）→ 列表出现 → 发送测试请求 → 前端提示送达失败
（指向不可达地址，交互链路正常）。

### 本轮结论

新功能 UI 此前只验证渲染，本轮完成真实点击交互，全部正常；未发现平台缺陷
（测试定位问题已适配）。服务已恢复 8000/3000，临时环境清理完毕。
