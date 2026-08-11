# 真实场景数据集（Real-World）

这里是从公开渠道下载的**真实评测数据**，已转换为 BenchmarkOps 可直接上传的 JSONL 格式（UTF-8，每行一个 JSON 对象）。下载转换过程见 `prepare_real_world_data.py`，可重复执行。

## 数据集一览

| 文件 | 场景 | 行数 | 字段 | 推荐基准类型/指标 | 数据来源 |
|------|------|------|------|------------------|----------|
| `ceval-qa.jsonl` | 中文考试真题问答（计算机网络 / 语文 / 高数） | 61 | `question`（含 ABCD 选项）、`answer`（选项字母）、`subject` | `qa` / `exact_match_ci` | [C-Eval](https://huggingface.co/datasets/ceval/ceval-exam) |
| `thucnews-classification.jsonl` | 中文新闻文本分类（10 类，每类 12 条） | 120 | `text`、`answer`（类别） | `classification` / `exact_match_ci` | [THUCNews / CNews](https://huggingface.co/datasets/spiritx2023/ThuCnews) |
| `humaneval-coding.jsonl` | Python 代码生成（OpenAI 原始题） | 60 | `prompt`、`answer`（标准解）、`entry_point`、`task_id` | `coding` / `contains` | [HumanEval](https://github.com/openai/human-eval) |

## 数据来源与许可

- **C-Eval**：上海交通大学发布的 13948 道中文考试题（真实考题），数据许可为 [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)，仅限非商业用途。本项目从 hf-mirror 下载 `val` 分片抽样。
- **THUCNews**：清华大学自然语言处理实验室整理的新闻数据，这里用的是公开子集 CNews（10 类）。HF 仓库未标注许可证，请仅用于学习/评测演示，勿用于商业发布。
- **HumanEval**：OpenAI 发布的 Python 函数补全题（164 题），MIT 许可。这里按 `task_id` 顺序取了前 60 题。

原始下载文件缓存在 `_downloads/`（约 28 MB），删除后可重新生成。

## 快速使用

1. 先启动后端和前端（见仓库根目录 `README.md`）：

   ```bash
   cd backend
   uv run uvicorn app.main:app --reload --port 8000
   # 另开终端
   cd frontend
   npm run dev
   ```

2. 一键导入并运行：

   ```bash
   cd sample-data/real-world
   python upload_real_world.py          # 导入 + 自动创建 6 个实验并运行
   # 或
   python upload_real_world.py --no-run # 只导入数据/基准/提示词
   ```

   脚本会：创建项目「真实场景评测 Real-World」→ 灌入模型 → 上传 3 个数据集 → 创建 3 个基准和 3 个提示词 → 每个数据集用前 2 个模型建实验并触发运行。

3. 浏览器打开 http://localhost:3000，进入项目后可查看每个实验的逐行结果，再到 **Compare** 对比准确率/延迟/费用，到 **Reports** 生成报告。

### 真实模型跨网关评测（推荐）

`backend/scripts/run_real_eval.py` 会用**真实模型**（同时路由七牛云 AI 与
OpenRouter 两个网关）跑一遍 C-Eval / THUCNews，并把结果与报告写入
`docs/real-world-eval/`：

```bash
cd backend
python scripts/run_real_eval.py                        # 默认 2 数据集 x 4 模型
python scripts/run_real_eval.py --limit 10             # 冒烟：每数据集限 10 行
python scripts/run_real_eval.py --include-coding       # 追加 HumanEval
```

> 前置：`backend/.env` 中配置 `OPENROUTER_API_KEY` 和/或 `QINIU_API_KEY`；
> 未配置 Key 的网关对应模型会评测失败（防止把 Mock 结果混入真实评测）。
> 注意：真实评测会消耗 API 配额，建议先用 `--limit 3` 验证链路。

## 运行说明

- 未配置 `OPENROUTER_API_KEY` 时自动使用 Mock Provider（离线合成输出），可以完整走通流程，但准确率不是真实模型水平；配置了 Key 后即为真实模型评测。
- `coding` 的 `contains` 指标检查输出是否包含标准参考实现，真实模型几乎不会全文命中，所以 HumanEval 准确率会偏低——这是评分口径导致的，不代表模型不能做题。若想看真实通过率，需要接入支持测试用例判定的指标（平台当前以文本指标为主）。
- 全部数据行数偏小（60–120 行），适合快速跑通流程；想跑更大规模，可改 `prepare_real_world_data.py` 顶部的取样常量重新生成。
