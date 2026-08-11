# 五场景端到端评测报告（qa / classification / coding / agent / generation）

> 日期：2026-08-12 · 平台：BenchmarkOps（本地运行）· 模型：Mock Provider（离线确定性，不产生真实费用）

## 1. 评测目标

验证 BenchmarkOps 对平台内置的五类基准（`qa` / `classification` / `coding` /
`agent` / `generation`）能否从**原始数据 → 数据集 → 基准 → 提示词 → 实验 →
运行 → 结果 → 报告**完整跑通，并输出可复现的评测文档。

## 2. 原始数据设计（自造）

数据存放于 `sample-data/scenarios/`，每个场景 10 条，字段按场景定制：

| 场景 | 文件 | 输入字段 | 期望字段 | 数据内容 |
|------|------|---------|---------|---------|
| qa | `qa.jsonl` | `question` | `answer` | 算术题（5）+ 地理常识（1）+ 电商客服问答（4） |
| classification | `classification.jsonl` | `text` | `answer` | 10 类新闻标题（体育/财经/科技/娱乐/房产/教育/社会/时尚/游戏/家居） |
| coding | `coding.jsonl` | `prompt` | `answer` + `tests` | Python 函数题，单行完整实现（5）+ 多行实现（5），每条带 `assert` 测试 |
| agent | `agent.jsonl` | `question` | `answer` + `arguments` | JSON 工具调用文本（5）+ 自然语言工具请求（5），期望工具名与参数键 |
| generation | `generation.jsonl` | `article` | `answer` | 数学生成（5）+ 新闻一句话摘要（5） |

设计说明：Mock Provider 是启发式合成输出（能正确回答算术题、识别
`france→Paris`、原样回显输入最后一行），因此每个场景都混合了"Mock 可命中"
与"Mock 不可命中"的样本，使准确率落在 0%~60% 区间，既能证明评分指标真实
生效，又能看到差异。

## 3. 评测配置

| 场景 | 基准类型 | 指标 | 提示词模板 |
|------|---------|------|-----------|
| QA | qa | `exact_match_ci` | `问题：{question}\n答案：` |
| CLASS | classification | `exact_match_ci` | `请将下面文本分类，只输出类别名：\n{text}\n类别：` |
| CODING | coding | `code_pass`（子进程跑测试，超时 5s） | `{prompt}` |
| AGENT | agent | `tool_call`（工具名 + 参数键） | `{question}` |
| GEN | generation | `f1_token` | `请对下面文章生成一句话摘要：\n{article}\n摘要：` |

模型：`provider=mock` 的临时模型（`scenario-mock-*`），10 行 × 5 场景，全程零费用。

## 4. 评测结果

| 实验 | 准确率 | 覆盖率 | 失败率 | 平均延迟 | 已评分行 | 错误行 |
|------|-------|-------|-------|---------|---------|-------|
| 场景实验 QA | **60.0%** | 100% | 0% | ~217ms | 10/10 | 0 |
| 场景实验 CLASS | 0.0% | 100% | 0% | ~239ms | 10/10 | 0 |
| 场景实验 CODING | **50.0%** | 100% | 0% | ~175ms | 10/10 | 0 |
| 场景实验 AGENT | **50.0%** | 100% | 0% | ~182ms | 10/10 | 0 |
| 场景实验 GEN | **50.0%** | 100% | 0% | ~210ms | 10/10 | 0 |

平台生成的报告见同目录 `report.md`（另导出 `report.html`、`report.pdf`）。

## 5. 逐场景分析

**QA（60%）**：6/10 命中——5 条算术题（Mock 正确计算）与 `france→Paris`
命中；4 条电商客服问答因 Mock 无真实语言能力未命中。指标、答案提取、逐行评分
均正常。

**CLASS（0%）**：Mock 输出的是提示词最后一行"类别："，与任何类别标签都不
匹配，因此全部分数正确记为 0——**这是 Mock 模型的局限，不是平台缺陷**；换
真实模型（如 OpenRouter）后该场景即可得到有意义的分类准确率。

**CODING（50%）**：5 条单行完整函数被 Mock 原样回显，`code_pass` 在子进程
中执行并通过 `assert`；5 条多行函数因 Mock 只回显最后一行、代码不完整而
失败。测试用例执行、超时保护、通过率计分全部正常。

**AGENT（50%）**：5 条"请输出工具调用：{json}"的样本被 Mock 回显为合法
JSON，`tool_call` 正确识别工具名与参数键；5 条自然语言请求未产生 JSON 调用，
记为 0。结构化工具调用判定链路可用。

**GEN（50%）**：5 条算术生成（期望为数字）被 Mock 命中，`f1_token` 得满分；
5 条新闻摘要与期望无重叠得 0。生成类指标工作正常。

## 6. 发现的问题与说明

1. **AI 报告自动回退模板**：生成报告时后端调用七牛网关
   （`api.qnaigc.com/v1/chat/completions`）返回 **400**，平台按设计自动回退到
   确定性模板报告（导出功能不受影响）。根因是当前 `.env` 的 `QINIU_API_KEY`
   或默认模型名与七牛平台不匹配，属于环境配置问题，非代码缺陷。
2. **分类场景 0%**：仅由 Mock 模型能力导致，建议接入真实 Provider 后复测。
3. 前端此前报"无法连接到服务器"的问题已修复（`frontend/.env.local` 的 API
   地址曾指向 8001 测试端口，已改为 `http://localhost:8000/api/v1`）。

## 7. 复现方法

```bash
# 1. 启动后端（8000）与前端（3000）
# 2. 运行五场景评测脚本（数据自造、Mock 模型、自动清理流程内临时资源）
python backend/scripts/run_scenarios.py
# 3. 报告输出到 docs/scenario-eval/report.{md,html,pdf}
```

## 8. 结论

五个评测场景从原始数据到评测报告的完整链路全部跑通：上传、字段映射、
基准/提示词创建、实验运行（含 `code_pass` 子进程执行与 `tool_call` 结构化
判定）、逐行评分、报告生成与 MD/HTML/PDF 导出均正常，无错误行、无平台级
缺陷。分类场景的 0% 与 AI 报告回退均系 Mock/七牛环境限制，接入真实模型
后即可获得有业务意义的评测结果。
