# P0/P1/P2 功能交付说明

本文档汇总本轮完成的优化（P0 并发与多租户、P1 指标与报告增强、P2 CI/CD 与成本治理），
以及对应的使用方式。

## P0：真实并发评测 + 多租户

### 并发评测（原有能力验证并保留）
- `EVAL_MAX_WORKERS`：同时运行的实验数量（进程内信号量，已生效）。
- `free_model_concurrency`：单个实验内逐行并发的行数上限。
- ARQ + Redis 分布式队列、任务持久化、重启恢复、取消，均已具备。

### 多租户（新增）
- 组织（Organization）+ 角色化 API Key（owner / admin / member / viewer）。
- 所有业务资源（项目、数据集、基准、提示词、实验、报告、导入任务、审计）按组织隔离。
- 无 Key 时保持原 demo 模式（全开放、无隔离）；全局 `API_TOKEN` 保持兼容。

使用方式：
1. `POST /api/v1/organizations` 创建组织，返回一次性 Owner Key（`bmops_...`）。
2. 后续请求带 `Authorization: Bearer <key>`。
3. 前端「设置」页新增「组织与 API Key」区块：创建组织、管理 Key、设置月度预算。

新增接口：
- `POST /organizations`、`GET /organizations/me`、`PATCH /organizations/{id}`
- `POST/GET /organizations/{id}/api-keys`、`DELETE /organizations/{id}/api-keys/{key_id}`

## P1：指标扩展 + 对比与报告增强

### 新指标（见 docs/metrics.md）
- `code_pass`：把模型输出与测试用例在子进程运行，按通过率计分（coding）。
- `semantic_similarity`：无外部依赖的语义相似度（qa / generation）。
- `tool_call`：Agent JSON 工具调用名称与参数判定（agent）。

### 对比分析
- `GET /analytics/experiments/{id}/subgroups?group_field=category`：按数据集字段分组看准确率/失败。
- `GET /analytics/compare/failures?experiment_a=&experiment_b=`：A 独错 / B 独错 / 都错。
- `GET /analytics/model-routing?project_id=`：按性价比推荐模型路由。

### 报告
- 导出支持 Markdown / HTML / PDF：`GET /reports/{id}/export`（`?format=html`）与
  `GET /reports/{id}/export/pdf`（PDF 使用 reportlab，纯 Python，Windows 可用）。

### 定时报告（持续评测订阅）
- 模型 + 后台调度器（每分钟扫描），支持 daily / weekly / monthly 与 md / html / pdf。
- 接口：`POST/GET/PATCH/DELETE /scheduled-reports`、`POST /scheduled-reports/{id}/run`。
- 前端：项目详情 → 报告页签 → 「定时报告」区块。

## P2：CI/CD 集成 + 行业包 + 成本治理

### Webhook
- 实验完成 / 失败时向订阅 URL POST 事件（含 HMAC-SHA256 签名头 `X-BenchmarkOps-Signature`）。
- 接口：`POST/GET/PATCH/DELETE /webhooks`、`POST /webhooks/{id}/test`。
- 前端：项目详情 → 报告页签 → 「Webhook」区块。

### CLI（backend/scripts/bmops.py）
```bash
python backend/scripts/bmops.py run <experiment_id> --wait
python backend/scripts/bmops.py check-regression --experiment <id> --baseline 0.90 --threshold 0.05
python backend/scripts/bmops.py export-report <report_id> --format pdf
python backend/scripts/bmops.py pack apply industry-packs/finance_customer_service.json
python backend/scripts/bmops.py webhook test <webhook_id>
```
环境变量：`BENCHMARKOPS_API`、`BENCHMARKOPS_TOKEN`。

### 回归门槛
- `.github/workflows/llm-regression.yml`：手动触发，运行实验并检查准确率是否跌破基线。
- CLI 中准确率低于 `baseline - threshold` 时退出码非 0（CI 可拦截）。

### 行业包
- `industry-packs/finance_customer_service.json`：金融客服示例包（基准 + 提示词模板）。
- CLI `pack apply` 一键创建项目 / 基准 / 提示词。

### 成本预算
- 组织可设置 `monthly_budget_usd`；当月评测累计费用达到预算后，拒绝启动新的实验运行。
- 前端：设置页 → 组织区块；后端检查位于实验 run 入口（含 retry）。

## 验收
- 后端：`pytest`（450 passed, 7 skipped, 11 deselected）。
- 前端：`tsc --noEmit` 与 `npm run build` 通过。
- 端到端：`python backend/scripts/acceptance_e2e.py --base <api>` 覆盖 24 项
  （组织/隔离/数据集/基准/实验/分组/排行/报告/导出/定时报告/Webhook/预算/路由/租户隔离）。
