# 评测指标指南（Metrics Guide）

BenchmarkOps 的评分指标通过装饰器注册，新增指标只需要一个文件、一个
`@register("name")` 函数，评测引擎会自动发现并在 `/benchmarks/metrics/available`
中列出。

## 指标函数契约

```python
from app.evaluation.metrics import register

@register("my_metric")
def my_metric(
    prediction: str,          # 模型输出（已清洗）
    expected: str | None,     # 期望答案的扁平字符串
    *,
    expected_raw: dict | list | None = None,  # 原始期望字段（可含结构信息）
    **kwargs,                 # benchmark metric_config / metric_suite 项配置
) -> float:                   # 返回 [0, 1]
    ...
```

- 同步函数或 `async` 协程都可以，引擎统一调度。
- `expected_raw` 是数据集行的原始 `expected` 对象，需要多答案、测试用例等
  结构化信息时从这里读取。
- `kwargs` 来自基准的 `metric_config`（或 `metric_suite` 中该项的 `config`），
  例如 `{"timeout_seconds": 5}`。
- 分数必须落在 `[0, 1]`，否则引擎按 `MetricEvaluationError` 处理。

## 内置指标

| 指标 | 适用类型 | 说明 |
|------|---------|------|
| `exact_match` / `exact_match_ci` | qa / classification | 精确匹配（忽略大小写可选） |
| `contains` | coding / agent | 输出是否包含期望片段 |
| `f1_token` | generation | token 级 F1 重叠 |
| `numeric_match` | qa | 数字答案匹配 |
| `fuzzy_match` / `fuzzy_match_ci` | qa / generation | 编辑距离阈值匹配 |
| `llm_judge` / `llm_judge_rubric` | 任意 | LLM 裁判 / 多维度加权评分 |
| `semantic_similarity` | qa / generation | 字符级语义相似度（无需外部 API） |
| `tool_call` | agent | JSON 工具调用名称 + 参数键判定 |
| `code_pass` | coding | 子进程运行测试用例，按通过率计分 |

## 新增指标：coding 测试用例判定（code_pass）

`code_pass` 把模型输出与测试用例拼成一个脚本，在隔离子进程中执行，按通过
比例计分。测试用例来源：

1. 数据集行的 `expected.tests`（推荐，逐行不同）；
2. 基准 `metric_config.tests`（整组共用）。

```jsonl
{"prompt": "实现 add(a, b) 函数", "answer": "def add(a, b):\n    return a + b\n", "tests": ["assert add(1, 2) == 3", "assert add(2, 2) == 4"]}
```

基准配置：

```json
{"type": "coding", "metric": "code_pass", "metric_config": {"timeout_seconds": 5}}
```

注意：`code_pass` 会在服务端执行用户/模型提供的代码，请仅在可信环境使用，
并保持子进程超时限制（默认 5 秒）。

## 新增指标：Agent 工具调用判定（tool_call）

`tool_call` 从模型输出中提取 JSON 工具调用（支持 ```json 代码块、纯 JSON、
OpenAI function-calling 格式），校验：

- `expected`：期望的工具名；
- `expected.arguments`（可选）：必须出现的参数键。

```jsonl
{"prompt": "查询订单 DD123 的状态", "answer": "search_orders", "arguments": {"order_id": "DD123"}}
```

工具名匹配且参数齐全 = 1.0；工具名匹配但缺参数 = 0.5；工具不匹配 = 0。

## 自定义指标示例：行业专用指标

```python
# app/evaluation/metrics_industry.py
from app.evaluation.metrics import register

@register("finance_key_entities")
def finance_key_entities(
    prediction: str,
    expected: str | None,
    *,
    expected_raw: dict | list | None = None,
    **kwargs,
) -> float:
    """检查输出是否覆盖期望的金融实体（公司名 / 金额 / 日期）。"""
    if not expected:
        return 0.0
    entities = [e for e in str(expected).split("|") if e.strip()]
    if not entities:
        return 0.0
    hit = sum(1 for e in entities if e.strip().lower() in prediction.lower())
    return hit / len(entities)
```

文件创建后在 `app/evaluation/metrics.py` 末尾追加：

```python
from app.evaluation import metrics_industry  # noqa: E402,F401
```

重启后端即可在 `/benchmarks/metrics/available` 看到新指标。
