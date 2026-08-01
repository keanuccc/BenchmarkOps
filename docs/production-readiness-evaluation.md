# BenchmarkOps 生产化评测工程分析与优化方案

日期：2026-07-22  
范围：数据集工程、基准标准工程、答案匹配与提示词规则、最近一次低正确率运行分析、端到端验证方案。

## 1. 结论摘要

当前项目已经具备一条可运行的评测主链路：

`Project -> Dataset -> Benchmark -> Prompt -> Model -> Experiment -> Run -> Results/Reports`

但它仍然更接近 demo / v1 平台，而不是生产级评测平台。核心差距不在“能不能跑”，而在以下四点：

1. 数据集缺少显式契约。现在主要靠字段名启发式拆 `input` 和 `expected`，对真实业务里多任务、多答案、多维度标注、元数据切片、数据版本治理支持不足。
2. Benchmark 缺少“标准工程”模型。现在是 `type + metric + metric_config`，还不能表达版本化标准、任务协议、指标集合、权重、阈值、分组口径和通过规则。
3. 答案匹配不能只靠 exact match。实际模型输出会有前缀、单位、解释、同义表达、格式噪音，需要“标准化抽取 + 确定性指标 + 语义裁判 + 人工复核”的分层评测。
4. 最近一次低准确率不是单一模型能力问题。`exp_last.txt` 记录的实验 `eb6beca6-ec86-4302-8290-36853f8ba563` 存库准确率是 `0.0033`，但用当前工作区代码对同一批 300 条结果重新评分，准确率可到 `0.8933`。主要原因是运行时旧答案抽取/匹配逻辑没有正确处理 `答案：亚洲` 这类中文前缀；剩余错误主要来自答案粒度不一致或模型确实答错。

## 2. 当前工程现状

### 2.1 数据集工程

相关文件：

- `backend/app/models/dataset.py`
- `backend/app/schemas/dataset.py`
- `backend/app/services/dataset_parser.py`
- `backend/app/services/dataset_service.py`
- `backend/app/api/v1/routes/datasets.py`

当前模型：

- `Dataset` 保存 `project_id`、`name`、`description`、`format`、`version`、`row_count`、`tags`、`stats`、`column_schema`。
- `DatasetRow` 保存 `dataset_id`、`idx`、`input`、`expected`。
- 支持 `csv`、`json`、`jsonl`。
- `split_input_expected()` 会优先识别显式 `expected`，否则把 `answer`、`label`、`output`、`target`、`ground_truth` 放入 expected，其余字段作为 input。

这套设计适合快速导入 `{"question": "...", "answer": "..."}` 这类 QA 样例。但生产业务的数据集通常会有：

- 多输入字段：用户问题、上下文、历史对话、图片/文件引用、工具状态。
- 多输出字段：标准答案、可接受答案列表、评分 rubric、禁用答案、解释依据。
- 样本元数据：业务线、语言、难度、场景、风险等级、来源、标注人、更新时间。
- 数据治理：版本、hash、原始文件、导入批次、错误行、字段映射、schema 演进。
- 评测切片：按业务域、任务类型、难度、模型族、语言、客户场景分组统计。

### 2.2 Benchmark / 标准工程

相关文件：

- `backend/app/models/benchmark.py`
- `backend/app/schemas/benchmark.py`
- `backend/app/services/benchmark_service.py`
- `backend/app/evaluation/metrics.py`
- `backend/app/evaluation/runner.py`

当前模型：

- `Benchmark` 只有 `project_id`、`name`、`description`、`type`、`metric`、`metric_config`。
- 支持类型：`qa`、`classification`、`coding`、`generation`、`agent`。
- 默认指标：
  - `qa` -> `exact_match_ci`
  - `classification` -> `exact_match_ci`
  - `coding` -> `contains`
  - `generation` -> `f1_token`
  - `agent` -> `contains`
- 当前指标注册在 `metrics.py`，包括 `exact_match`、`exact_match_ci`、`contains`、`f1_token`、`numeric_match`、`llm_judge`。

这说明工程已经有可插拔指标意识，但还不是生产中的“基准标准”。实际标准至少需要表达：

- 任务定义：输入字段、输出字段、可接受输出格式。
- 数据选择：使用哪些 dataset version、哪些 slice、抽样比例。
- 指标集合：多个 metric、权重、阈值、聚合方式。
- 通过规则：例如总分 >= 0.85，安全类错误为 0，核心业务 slice 不低于 0.9。
- 报告口径：主指标、辅助指标、失败分类、对比维度。
- 审计与复现：标准版本、发布状态、变更记录、创建人、审批记录。

### 2.3 实验运行链路

相关文件：

- `backend/app/models/experiment.py`
- `backend/app/services/experiment_service.py`
- `backend/app/evaluation/runner.py`
- `backend/app/evaluation/task_queue.py`

当前流程：

1. 创建 Experiment，绑定 dataset、benchmark、prompt、model。
2. `ExperimentService.create()` 会快照 prompt、benchmark、model 的部分内容。
3. `run_experiment()` 加载 dataset rows。
4. 每行渲染 prompt，调用 provider。
5. 清洗模型输出，取 expected，调用 metric。
6. 写入 `ExperimentResult`，聚合 accuracy、latency、tokens、cost。

生产风险：

- `benchmark_snapshot` 目前没有完整保存 `type/name/version`，`llm_judge` 需要 benchmark type 时可能回退不准确。
- `duplicate()` 没有复制 snapshots，复制实验后复现性会受 live 配置影响。
- runner 会把所有 rows 读入内存，数据集变大后会放大内存压力。
- SQLite + 进程内队列适合 v1，本地和小规模 demo 可用；生产应切到 Postgres + 持久化队列。

## 3. 数据集工程如何生产化

### 3.1 最小可落地设计

不要一开始就做完整数据平台。建议在现有模型上加一个显式 `DatasetContract`，让数据导入从“猜字段”变成“有契约地解析”。

建议契约结构：

```json
{
  "task_type": "qa",
  "input_fields": ["question", "context"],
  "expected_fields": ["answer"],
  "metadata_fields": ["domain", "difficulty", "language"],
  "required_fields": ["question", "answer"],
  "field_types": {
    "question": "string",
    "context": "string",
    "answer": "string",
    "difficulty": "string"
  },
  "answer_policy": {
    "multi_reference": false,
    "case_sensitive": false,
    "allow_semantic_equivalence": true
  }
}
```

数据库可以先不大拆表，先在 `Dataset` 增加或复用一个 JSON 字段保存：

- `task_type`
- `field_mapping`
- `schema`
- `source_filename`
- `content_hash`
- `import_status`
- `import_errors`
- `schema_version`

### 3.2 导入流程

建议改成：

1. 上传文件。
2. 解析一次，不在 route 和 service 各解析一遍。
3. 根据 `DatasetContract` 做字段映射和校验。
4. 分批写入 `DatasetRow`，例如每 500 或 1000 行一批。
5. 生成 stats、schema、hash、错误样本摘要。
6. 导入完成后 dataset 进入 `ready` 状态；有错误进入 `failed` 或 `partial`。

必须校验：

- 每行是否是 object。
- 必填 input 字段是否存在。
- expected 是否存在。
- prompt 变量是否能从 input 中取到。
- expected 结构是否和 metric 兼容。
- idx 是否连续唯一。
- 数据集行数是否和 stats 一致。

### 3.3 数据集版本治理

生产中不要覆盖修改已有数据集。推荐：

- dataset 是逻辑集合。
- dataset version 是不可变快照。
- experiment 绑定 dataset version，而不是绑定会变的 live dataset。
- 每次导入新文件生成新 version。
- 用 `content_hash` 防止重复导入。

最小实现可以先保留当前 `Dataset.version`，但要求新导入生成新 Dataset 记录或显式新版本记录，旧实验继续指向旧版本。

## 4. Benchmark 标准工程如何实现

### 4.1 核心对象

推荐引入四个概念：

1. `BenchmarkSpec`
   - 版本化标准定义。
   - 包含 task type、输入输出契约、指标套件、通过规则、报告口径。

2. `MetricSuite`
   - 多指标组合。
   - 每个 metric 有 name、config、weight、threshold、aggregation。

3. `TaskAdapter`
   - 按 `qa/classification/generation/coding/agent` 拆分。
   - 负责行级校验、输出解析、metric 调用前的数据准备。

4. `RunSnapshot`
   - 实验创建时完整快照 dataset manifest、benchmark spec、prompt、model。
   - 保证之后 prompt 或 benchmark 修改不会改变历史实验含义。

### 4.2 BenchmarkSpec 示例

```json
{
  "version": 3,
  "status": "published",
  "task_type": "qa",
  "input_schema": {
    "required": ["question"],
    "optional": ["context"]
  },
  "output_schema": {
    "format": "single_answer",
    "answer_field": "answer"
  },
  "metric_suite": [
    {
      "name": "exact_match_ci",
      "weight": 0.6,
      "config": {
        "normalize_whitespace": true,
        "strip_answer_prefix": true
      }
    },
    {
      "name": "llm_judge",
      "weight": 0.4,
      "config": {
        "judge_provider": "qiniu",
        "judge_model": "deepseek/deepseek-v4-flash",
        "semantic_rules": "same meaning is correct, broader/narrower category is not automatically correct"
      }
    }
  ],
  "pass_policy": {
    "primary_score_min": 0.85,
    "critical_slice_min": 0.9
  },
  "reporting_policy": {
    "primary_metric": "primary_score",
    "slice_fields": ["domain", "difficulty", "language"]
  }
}
```

### 4.3 评分结果结构

不要只保存 `accuracy`。建议保存：

```json
{
  "primary_score": 0.8933,
  "pass": true,
  "metrics_by_name": {
    "exact_match_ci": 0.86,
    "llm_judge": 0.94
  },
  "metrics_by_slice": {
    "domain=geography": {
      "primary_score": 0.91,
      "rows": 120
    },
    "difficulty=hard": {
      "primary_score": 0.78,
      "rows": 40
    }
  },
  "rows_total": 300,
  "rows_scored": 300,
  "rows_failed": 0
}
```

这样可以区分：

- 模型真的错。
- 输出格式错。
- 标准答案粒度和业务目标不一致。
- 某个业务 slice 退化。

## 5. 答案匹配问题如何解决

### 5.1 分层匹配管线

建议采用四层：

1. 标准化与抽取
   - 去掉 `答案：`、`Answer:`、`Final Answer:` 等前缀。
   - 取最终答案行。
   - 去掉单位、括号解释、标点、空白噪音。
   - 数字统一格式。

2. 确定性指标
   - `exact_match_ci`：适合短答案、分类标签。
   - `numeric_match`：适合数值题。
   - `contains`：适合关键词命中，但误判风险高。
   - `f1_token`：适合摘要、生成类初筛。

3. 语义裁判
   - `llm_judge` 适合语义等价、不完全同字面答案。
   - 必须带清晰 rubric，避免 judge 过宽。
   - judge 输出只能是 `MATCH` 或 `NO_MATCH`，便于机器解析。

4. 人工复核与规则回流
   - 对低置信度、业务关键、judge 和 deterministic metric 冲突的样本进入人工复核。
   - 人工结论回写为新规则、新参考答案或数据集修订。

### 5.2 不要把所有不一致都算“语义等价”

本项目最近实验里有典型例子：

- expected：`热带雨林`
- output：`热带`

这不是简单同义词问题。`热带` 是更宽泛类别，是否算对取决于业务标准。如果题目要求“气候带类别”，可能 `热带` 过粗；如果题目只要求“大类”，可能可以接受。因此必须由 BenchmarkSpec 的 rubric 决定。

### 5.3 多答案与别名

数据集 expected 应支持：

```json
{
  "answer": "亚洲",
  "aliases": ["亚细亚洲", "Asia"],
  "unacceptable": ["东亚"],
  "match_policy": "exact_or_alias"
}
```

对于开放式任务：

```json
{
  "rubric": [
    {"criterion": "事实正确", "weight": 0.5},
    {"criterion": "覆盖关键点", "weight": 0.3},
    {"criterion": "无幻觉", "weight": 0.2}
  ],
  "reference": "..."
}
```

## 6. 提示词规则

### 6.1 短答案 / QA / 分类任务

推荐规则：

1. 明确角色和任务。
2. 明确输出格式。
3. 最后一行固定使用 `答案：`。
4. 不要求模型输出推理过程。
5. 明确未知时输出固定词，例如 `无法判断`。

模板：

```text
你是一名严谨的答题助手。请阅读问题，只输出最终答案。

规则：
1. 最后一行必须以“答案：”开头。
2. “答案：”后只写一个最简短答案，不写解释、单位换算过程或额外选项。
3. 如果无法从题目判断，输出“答案：无法判断”。

问题：{question}
```

如果需要模型内部推理，不要要求输出 Chain-of-Thought。可以写：

```text
请在内部完成必要推理，但不要输出推理过程。最后一行只输出“答案：...”。
```

### 6.2 结构化输出任务

对分类、抽取、agent 结果，优先使用 JSON：

```text
请只输出合法 JSON，不要输出 Markdown。

字段：
- label: 字符串，必须是 ["正面", "负面", "中性"] 之一
- confidence: 0 到 1 的数字

输入：{text}
```

对应 evaluator 不应再用 `exact_match_ci` 比整段文本，而应解析 JSON 后比较 `label` 字段。

### 6.3 生成类任务

生成类不要用单一 exact match。提示词应写清：

- 必须覆盖哪些事实。
- 禁止编造哪些内容。
- 长度范围。
- 输出结构。
- 评分 rubric。

示例：

```text
请根据文章生成摘要。

要求：
1. 80 到 120 字。
2. 覆盖事件主体、原因、结果。
3. 不得添加原文没有的信息。
4. 只输出摘要正文。

文章：{article}
```

## 7. 最近一次低正确率分析

### 7.1 运行记录

`exp_last.txt` 记录：

- experiment id：`eb6beca6-ec86-4302-8290-36853f8ba563`
- status：`completed`
- metric：`exact_match_ci`
- rows_total：`300`
- cells_done：`300`
- cells_error：`0`
- stored accuracy：`0.0033`
- provider：`qiniu`
- model：`deepseek/deepseek-v4-flash`
- prompt：要求最后一行以 `答案：` 开头

数据库中 `experiment_results` 统计：

- 300 条结果全部有输出。
- 299 条存库 score 是 `0.0`。
- 1 条存库 score 是 `1.0`。

### 7.2 关键证据

用当前工作区代码对同一批已存结果重算：

- stored accuracy：`0.0033333333333333335`
- recomputed accuracy：`0.8933333333333333`
- rows：`300`

样例：

```text
expected: 亚洲
output: 答案：亚洲
current extracted prediction: 亚洲
current exact_match_ci score: 1.0
stored score: 0.0
```

这说明最近一次运行时的评分逻辑没有正确处理模型按 prompt 输出的 `答案：...` 前缀。当前工作区的 `_extract_answer()` 已能处理该模式。

### 7.3 剩余错误类型

当前代码重算后仍有 32 条不命中，主要类型：

1. 模型确实答错  
   例：一杯水题 expected `62.5`，模型输出 `125`。

2. 答案粒度不一致  
   例：expected `热带雨林`，模型输出 `热带`。

3. 参考答案本身需要更明确的业务标准  
   例：expected `20 世纪 60 年代`，模型输出 `20世纪`。是否正确取决于题目要求的是世纪还是年代。

4. 提示词与题目要求有冲突或不够精确  
   如果题目问“发生的世纪”，expected 却是“20 世纪 60 年代”，标准答案粒度和问题本身不一致。

### 7.4 日志中的其他问题

`backend_run.err.log` 还出现过：

- 多次 provider `429 Too Many Requests`。
- 一次后台任务异常：`TypeError: unsupported operand type(s) for +=: 'float' and 'NoneType'`，来自历史代码中 `total_cost += res.cost` 未处理 None 的情况。
- 一次 Windows socket buffer 错误。

这些是运行可靠性问题，需要纳入生产化优化。但它们不是这次 `completed + cells_error=0 + accuracy=0.0033` 的主要原因。

## 8. 分阶段实施路线

### 阶段 1：先修复评测可信度

目标：同一批结果重新评分可解释，短答案不因格式噪音误判。

实施项：

- 固化 `_extract_answer()` 的中文/英文前缀、单位、括号、空白、数字测试。
- 给 `exact_match_ci`、`numeric_match`、`contains`、`f1_token` 增加边界测试。
- 在结果页展示 `raw_output`、`cleaned_prediction`、`expected_canonical`、`score_reason`。
- 增加“重算分数”工具，用当前 metric 对历史 results 重算并生成差异报告。

验收：

- 最近实验重算差异能解释。
- QA 短答案 golden dataset 达到预期分数。
- 格式噪音不会导致大面积误判。

### 阶段 2：数据集契约和实验前校验

目标：坏数据不静默进入实验。

实施项：

- 增加 `DatasetContract`。
- 导入时生成 field mapping、schema、stats、hash。
- `validate()` 检查字段、类型、expected、prompt variables、metric 兼容性。
- Experiment 创建或运行前调用 validate。

验收：

- 缺失 `{question}` 的数据集不能直接跑。
- 没有 expected 的评测数据会被标记为不可评分。
- 多参考答案结构能被 metric 正确识别。

### 阶段 3：BenchmarkSpec 和 MetricSuite

目标：支持不同业务标准，而不是只有一个 metric。

实施项：

- 扩展 `Benchmark.metric_config` 为 versioned spec。
- 增加 metric suite 编排层。
- 支持 weighted score、threshold、slice aggregation。
- 完整快照 benchmark type/name/version/spec。
- 修复 duplicate experiment 的 snapshot 语义。

验收：

- 一个 benchmark 可以同时跑 exact match 和 llm judge。
- 报告展示 primary score、pass/fail、slice score。
- 修改 benchmark 后旧实验可复现。

### 阶段 4：任务适配器

目标：不同任务类型有不同评测协议。

实施项：

- `qa`：短答案抽取、多答案、别名、语义等价。
- `classification`：label 解析、混淆矩阵、宏/微平均。
- `generation`：rubric judge、事实一致性、覆盖率。
- `coding`：代码执行、单测、编译、安全沙箱。
- `agent`：工具调用轨迹、任务完成度、错误恢复。

验收：

- 每种 task type 有最小 golden dataset。
- 每种 task type 有独立行级 score reason。

### 阶段 5：生产运行底座

目标：任务可靠、可恢复、可观测。

实施项：

- SQLite 切 Postgres。
- 进程内队列切 Celery/RQ/Arq 等持久化队列。
- 增加 retry/backoff/cancel/timeout。
- provider 级别限流和熔断。
- 实验运行日志和审计事件入库。

验收：

- worker 重启后任务可恢复或明确失败。
- provider 429 不导致整体不可解释。
- 并发运行不会重复写结果。

## 9. 端到端测试方案

### 9.1 后端离线 E2E

命令：

```powershell
cd D:\code\benchmarkv1\backend
uv run pytest tests/test_workflow.py -q
```

目的：

- Mock provider。
- 创建 project/dataset/benchmark/prompt/experiment。
- 运行实验。
- 校验 results 和 accuracy。

### 9.2 答案匹配关键测试

命令：

```powershell
cd D:\code\benchmarkv1\backend
uv run pytest tests/test_runner_extract_answer.py tests/test_llm_judge.py -q
```

目的：

- 验证前缀清洗。
- 验证 CoT 最后一行抽取。
- 验证 LLM judge 解析。

### 9.3 并发与任务状态

命令：

```powershell
cd D:\code\benchmarkv1\backend
uv run pytest tests/test_run_race.py tests/test_runner_no_long_lock.py -q
```

目的：

- 验证并发 run 不重复写。
- 验证 runner 不持有长事务锁。

### 9.4 前端 UI E2E

命令：

```powershell
cd D:\code\benchmarkv1\backend
$env:OPENROUTER_API_KEY=""
uv run uvicorn app.main:app --port 8000
```

```powershell
cd D:\code\benchmarkv1\frontend
npm run dev
```

```powershell
cd D:\code\benchmarkv1\frontend\e2e
python -m pytest -v
```

注意：这套 UI E2E 会通过页面创建数据，适合在独立测试数据库或临时环境中跑。

### 9.5 真实模型 E2E

命令：

```powershell
cd D:\code\benchmarkv1\backend
uv run pytest tests/test_e2e_real_free_model.py -m e2e
```

注意：

- 需要真实 provider key。
- free model 不保证 100%。
- 该测试断言高于阈值，而不是满分。

## 10. 本次验证结果

本次已执行：

```powershell
cd D:\code\benchmarkv1\backend
uv run pytest tests/test_run_race.py -q -p no:cacheprovider
```

结果：

- `1 passed`
- 1 个 Starlette/httpx deprecation warning

本次已执行：

```powershell
cd D:\code\benchmarkv1\backend
uv run pytest tests/test_workflow.py tests/test_runner_extract_answer.py tests/test_llm_judge.py tests/test_runner_no_long_lock.py -q -p no:cacheprovider
```

结果：

- `27 passed`
- 1 个 Starlette/httpx deprecation warning

本次还修复了一个测试夹具问题：

- 文件：`backend/tests/test_run_race.py`
- 原因：测试 monkeypatch 的 `get_provider` lambda 不接收参数，但当前 runner 会调用 `get_provider(model_provider)`。
- 修复：改为 `lambda _name=None: MockProvider()`。

## 11. 优先级清单

P0：

- 保留并完善当前答案抽取测试。
- 历史实验支持重算分数。
- 在实验结果中记录 cleaned prediction 和 score reason。
- 修复 benchmark snapshot 缺 type、duplicate 不复制 snapshot。

P1：

- 增加 DatasetContract 和实验前 validate。
- 增加 MetricSuite。
- 增加多答案、别名、numeric tolerance、semantic judge 配置。

P2：

- 引入 TaskAdapter。
- 对 classification/generation/coding/agent 做专用评测协议。
- 增加 slice metrics、pass policy、报告口径。

P3：

- Postgres。
- 持久化队列。
- 任务恢复、取消、审计、限流、告警。

