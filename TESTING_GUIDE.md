# BenchmarkOps 手动测试指南

> 目标：带你从头到尾跑通「项目 → 模型 → 数据集 → 基准 → 提示词 → 实验 → 运行 → 对比 → 报告」全链路，
> 并理解每一环在做什么、数据长什么样。
>
> 适用环境：本机已 `npm run dev`（前端 3000）+ `uv run uvicorn app.main:app`（后端 8000），
> 且 `.env` 里 `OPENROUTER_API_KEY` 为空（即使用**确定性 Mock provider**，可完全离线运行）。

---

## 0. 先理解这套系统的「一句话模型」

BenchmarkOps 是一个 **LLM 评测平台**。你要评测「某个模型在某个任务上表现多好」：

```
项目(Project)
 ├─ 模型(Model)        —— 被评测的对象（如 GPT-4o / Claude）
 ├─ 数据集(Dataset)    —— 评测题目（JSONL，每行一道题）
 ├─ 基准(Benchmark)    —— 评分规则（题型 + 评分指标，如 QA + exact_match）
 ├─ 提示词(Prompt)     —— 把每道题包装成发给模型的指令模板
 └─ 实验(Experiment)   —— 把上面 4 样「绑一起跑一次」= 一次评测运行
       └─ 跑完得到：accuracy / cost / tokens / latency，可多模型对比、生成报告
```

**一次实验 = 数据集 × 基准 × 提示词 × 模型**（四个下拉框必填）。

---

## 1. 准备数据

下面所有数据都已按后端真实字段格式准备好，可直接复制使用。

### 1.1 数据集（JSONL，每行一道题）

把下面内容存成文件 `my-qa.jsonl`：

```jsonl
{"question": "2+2等于几？", "answer": "4"}
{"question": "3乘以3等于几？", "answer": "9"}
{"question": "10减6等于几？", "answer": "4"}
{"question": "15除以3等于几？", "answer": "5"}
{"question": "7加8等于几？", "answer": "15"}
```

> 为什么用算术题？因为无 API key 时走 **Mock provider**，它只会对算术题算出正确结果、
> 含 "france" 返回 "Paris"，其余情况回显 prompt 最后一行（即答不对）。
> 用算术题你能看到 **accuracy 接近 100%** 的真实评测结果；若用中文知识题，Mock 基本答错，
> accuracy 会很低——这同样正常，只是用来演示「评分确实在跑」。
>
> 项目自带示例数据在 `sample-data/qa-sample.jsonl`（中文知识题，跑 Mock 时 accuracy 偏低）。

> 字段约定：每行的键会直接作为「提示词模板变量」。本题用 `question` + `answer`，
> 所以提示词模板里可以用 `{question}` 取到每道题的问题。

### 1.2 基准（Benchmark）

| 字段 | 值 | 说明 |
|------|-----|------|
| 名称 | `QA 精确匹配` | 任意 |
| 类型 | `qa` | 可选：qa / coding / agent / classification / generation |
| 指标 | `exact_match_ci`（或留空=自动） | qa 类型默认指标就是 exact_match_ci（大小写不敏感精确匹配） |

> 评测时，对每道题：`score = (模型输出.lower() == 标准答案.lower()) ? 1.0 : 0.0`，
> 最终 accuracy = 所有题得分的平均。

### 1.3 模型（Model）

不用自己造。进入「模型」页点 **初始化模型** 即可种子 8 个真实模型：

```
GPT-4o mini, GPT-4o, Claude 3.5 Sonnet, Claude 3.5 Haiku,
Gemini 1.5 Pro, DeepSeek V3, Qwen 2.5 72B, GLM-4
```

> 关键：未配置 `OPENROUTER_API_KEY` 时，平台用 **Mock provider** 代替这些模型实际推理，
> 所以你点「运行」会秒回、可离线、结果确定。配置 key 后才会真正调用对应模型（消耗额度/计费）。

### 1.4 提示词（Prompt）

| 字段 | 值 |
|------|-----|
| 名称 | `直接回答` |
| 模板 | `请回答下面的问题，只输出答案，不要解释：{question}` |

> `{question}` 会被自动识别为模板变量，运行时由数据集每行的 `question` 字段填充。
> 例如第 1 行会渲染成：「请回答下面的问题，只输出答案，不要解释：2+2等于几？」

---

## 2. 一步一步测试（UI 操作）

打开浏览器 **http://localhost:3000**。

### 步骤 1：新建项目
- 点左侧/顶部 **项目** → **新建项目**
- 项目名称：`我的第一次评测`，描述可空 → **创建**

### 步骤 2：初始化模型
- 点 **模型** → **初始化模型**（约数秒，出现 8 个模型及「上下文」列即成功）
- 这是幂等的，重复点不会重复创建。

### 步骤 3：导入数据集
- 回到项目（点 **项目** → 你的项目名），进入 **数据集** Tab
- 点 **导入**：填名称 `算术题`，选择文件 `my-qa.jsonl` → **导入**
- 成功后能看到 `算术题 (5)`（5 = 行数 row_count）

### 步骤 4：创建基准
- 进入 **基准** Tab → **创建**
- 名称 `QA 精确匹配`，类型选 `qa`，指标留「自动」→ **创建**

### 步骤 5：创建提示词
- 进入 **提示词** Tab → 填名称 `直接回答`、模板 `请回答下面的问题，只输出答案，不要解释：{question}` → **创建**

### 步骤 6：创建并运行实验
- 进入 **实验** Tab
- 填实验名称 `算术题-首跑`，四个下拉分别选：数据集=算术题、基准=QA 精确匹配、提示词=直接回答、模型=GPT-4o mini
- 点 **创建实验**
- 卡片出现后点 **运行**（Mock 模式下几秒内变 `completed`）
- 完成后卡片显示：`acc: 100.0%`、`cost`、`tok`、`ms`

### 步骤 7：再跑一个模型做对比
- 同样方式再建一个实验，模型换成 `Claude 3.5 Haiku`，点 **运行**
- 现在你有两个 `completed` 实验，可勾选它们的复选框 → 点 **对比选中 (2) →**
- 对比页展示两模型在 accuracy / latency / cost / tokens 维度的并排对比

> 更快的对比入口：任意项目下点顶部 **实验**（全局实验页），或勾选 ≥2 个实验后点 **对比全部 →**。

### 步骤 8：生成报告
- 进入项目 **报告** Tab → **生成报告**，选刚才的实验 → 生成
- 报告为 Markdown，可点 **导出** 下载 `.md`

---

## 3. 理解每一步的「后台发生了什么」

| UI 动作 | 后端接口 | 说明 |
|---------|----------|------|
| 新建项目 | `POST /api/v1/projects/` | 创建项目容器 |
| 初始化模型 | `POST /api/v1/models/seed` | 种子 8 个默认模型 |
| 导入数据集 | `POST /api/v1/datasets/upload` | 解析 JSONL，统计 row_count |
| 创建基准 | `POST /api/v1/benchmarks/` | 记录题型+指标（缺省用类型默认指标） |
| 创建提示词 | `POST /api/v1/prompts/` | 提取 `{变量}`，存储模板 |
| 创建实验 | `POST /api/v1/experiments/` | 仅登记「绑定关系」，不跑 |
| 运行 | `POST /api/v1/experiments/{id}/run` | 真正逐行：渲染提示词→调模型→按基准打分→汇总 |
| 对比 | `POST /api/v1/analytics/compare` | 多实验维度聚合对比 |
| 报告 | `POST /api/v1/reports/generate` | 基于实验结果生成 Markdown |

> 读接口（GET）均无需鉴权；写接口（POST/PATCH/DELETE）若配置了 `API_TOKEN` 才需要 Bearer。
> 当前 `.env` 未配置，全部开放。

---

## 4. 你可能观察到的「正常现象」

1. **accuracy 不是 100%**：用了中文知识题 + Mock provider → Mock 不会真推理，多半答错。换算术题即可接近满分。
2. **cost 是小数但极小**：Mock 用伪 token 数（按字符数/4）和模型定价算出来的「演示计费」，非真实扣费。
3. **运行瞬间完成**：Mock 是本地确定性计算，没有真实网络请求。
4. **不同模型分数一样**：Mock 输出只取决于 (model_id, prompt) 的哈希，与「模型能力」无关——它只是用来打通流程。要看到真实差异，配 `OPENROUTER_API_KEY` 后重跑。

---

## 5. 想看「真实能力对比」时

编辑 `backend/.env`，填入：

```
OPENROUTER_API_KEY=sk-or-xxxx
```

重启后端（`uvicorn app.main:app`）。之后「运行」会真实调用 OpenRouter 网关上的对应模型，
accuracy/cost/latency 反映真实表现，多模型对比才有意义。


---

## 6. 统一验收命令（自动化验证）

以下命令供其他开发窗口在提交代码后运行，确保端到端链路完整可用。

### 6.1 后端非 E2E 测试基线

```powershell
cd D:\code\benchmarkv1\backend
uv run pytest tests/test_workflow.py tests/test_runner_extract_answer.py tests/test_llm_judge.py tests/test_runner_no_long_lock.py tests/test_run_race.py tests/test_answer_prefix_noise_e2e.py -q -p no:cacheprovider
```

**预期结果：** 29 passed, 1 warning (Starlette/httpx deprecation)

**覆盖内容：**
- `test_workflow.py` — 全链路 Mock provider + 数据集上传限制 + 实验创建校验
- `test_runner_extract_answer.py` — 答案前缀清洗、CoT 最后一行抽取、单位/标点剥离
- `test_llm_judge.py` — LLM-as-Judge 指标解析
- `test_runner_no_long_lock.py` — Runner 不持有长事务锁
- `test_run_race.py` — 并发 Run CAS 防双写
- `test_answer_prefix_noise_e2e.py` — **新增**：Provider 输出带 `答案：` 前缀噪音时，Runner 的 `_extract_answer()` 仍能正确清洗并评分

### 6.2 前端 UI E2E 测试

前置条件：需要启动隔离的后端和前端服务（不与用户正在使用的 8000/3000 端口冲突）。

```powershell
# 1. 启动隔离后端 (Mock provider, 临时 DB)
$env:OPENROUTER_API_KEY=' '
$env:QINIU_API_KEY=' '
$env:DEFAULT_PROVIDER='mock'
$env:DATABASE_URL='sqlite+aiosqlite:///./backend/benchmarkops_e2e_codex.db'
uv run uvicorn app.main:app --host 127.0.0.1 --port 8002

# 2. 启动隔离前端 (指向 8002)
cd frontend
npm run build
set NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8002/api/v1 && node_modules\.bin\next.cmd start -p 3002

# 3. 运行 E2E
cd frontend\e2e
$env:BASE_URL='http://127.0.0.1:3002'
python -m pytest -v
```

**预期结果：** 5 passed (test_flow.py x2 + test_edge.py x3)

**覆盖流程：**
- 模型初始化 → 项目创建 → 数据集导入 → 基准创建 → 提示词创建 → 实验创建与运行 → 结果查看 → 对比 → 报告生成与导出
- 边界测试：空名称项目不创建、超大行数数据集拒绝、实验必填项校验、防双写

### 6.3 注意事项

1. **数据隔离：** UI E2E 通过 `E2E-` / `EDGE-` 前缀命名资源，与现有业务数据互不影响
2. **临时数据库：** 隔离后端使用 `benchmarkops_e2e_codex.db`，不会污染主数据库
3. **端口占用：** 8002/3002 必须未被占用；如冲突可修改端口号
4. **CI 环境：** CI 使用 `npm run build && npm run start` + `BASE_URL=http://127.0.0.1:3000 pytest -v`，无需手动启停服务
