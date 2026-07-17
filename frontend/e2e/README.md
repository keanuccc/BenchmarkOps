# BenchmarkOps 前端端到端测试 (Python + Playwright)

通过真实浏览器驱动整个 UI 流程,覆盖从「初始化模型」到「生成并导出报告」的完整链路。

## 前置条件

1. **后端在跑**(Mock provider,免费、确定性):
   ```bash
   cd backend
   OPENROUTER_API_KEY= uvicorn app.main:app --port 8000
   ```
   `.env` 里 `OPENROUTER_API_KEY` 留空即自动启用 Mock provider,
   experiment 可完整跑通且结果确定,无需真实 API key、不花钱。

2. **前端 dev server 在跑**(默认 3000):
   ```bash
   cd frontend
   npm run dev        # http://localhost:3000
   ```

3. **安装 Playwright + 浏览器**:
   ```bash
   cd frontend/e2e
   pip install -r requirements.txt
   python -m playwright install chromium
   ```

## 运行

```bash
cd frontend/e2e
pytest -v
```

自定义前端地址(复用其他端口已运行的 dev server):

```bash
BASE_URL=http://localhost:3001 pytest -v
```

## 覆盖的流程

| 步骤 | 操作 |
|------|------|
| 模型 | 模型中心 → 初始化模型 |
| 项目 | 项目页 → 新建项目 |
| 数据集 | 项目详情 → 数据集 tab → 导入 JSONL (3 行) |
| 基准 | 基准 tab → 创建 (qa 类型, 默认 metric) |
| 提示词 | 提示词 tab → 创建 (含 {question} 变量) |
| 实验 | 实验 tab → 创建 → 运行(轮询至 completed) |
| 结果 | 实验详情页 → 查看准确率 |
| 对比 | 实验 tab → 对比全部 |
| 报告 | 报告 tab → 生成报告 → 导出 |

另含一个校验测试:新建项目时名称为空不应创建。

## 边界 / 异常测试 (`test_edge.py`)

| 测试 | 触发的守卫 |
|------|------|
| `test_upload_rejects_too_many_rows` | 上传行数超过 `max_dataset_rows`(100000)→ 后端 422,UI 显示 `rows exceeds limit`,不创建数据集 |
| `test_experiment_requires_all_fields` | 实验表单缺字段 → UI 显示 `所有字段均为必填项` |
| `test_experiment_run_writes_single_batch` | 运行实验 → 干净完成且只写入一份逐行结果(对应后端 CAS 防双写,`test_run_race`) |

## CI

`.github/workflows/e2e.yml` 在每次 push / PR 到 `main` 时自动运行:

1. 用 `uv` 起后端(Mock provider,无需 API key)
2. `npm ci` + `npm run build` + `npm run start` 起前端生产模式(3000)
3. 安装 Playwright + Chromium(含系统依赖)
4. 跑整套 E2E 测试

本地无需手动起服务即可对照 CI 行为:用 `npm run build && npm run start` 代替 `npm run dev`,
再 `BASE_URL=http://127.0.0.1:3000 pytest -v`。

## 说明

- 测试**不**自己启停 dev server,默认复用已在 3000 端口运行的服务,避免和你的会话冲突。
- 测试数据用 `E2E-` / `EDGE-` 前缀命名,与现有数据隔离;测试结束不强制清理(简单优先)。
- 若 dev server 崩溃,先 `rm -rf frontend/.next && npm run dev` 重启,再跑本套件。
- CI 与本地均依赖后端 `OPENROUTER_API_KEY` 为空以启用 Mock provider。
