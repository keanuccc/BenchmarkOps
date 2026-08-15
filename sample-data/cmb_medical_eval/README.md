# CMB 中文医疗问答评测数据

本目录用于保存从公开 **CMB: A Comprehensive Medical Benchmark in Chinese** 下载的
原始数据，以及转换为 BenchmarkOps 平台可直接上传的 JSONL 数据。

## 数据来源

- 项目地址：<https://github.com/FreedomIntelligence/CMB>
- 论文：<https://arxiv.org/abs/2308.08833>
- 许可证：**Apache-2.0**
- 题目原始文件：
  <https://raw.githubusercontent.com/FreedomIntelligence/CMB/main/data/CMB.zip>
  （解压后取 `CMB-Exam/CMB-test/CMB-test-choice-question-merge.json`）
- 答案原始文件：
  <https://raw.githubusercontent.com/FreedomIntelligence/CMB/main/data/CMB-test-choice-answer.json>

## 本目录文件

| 文件 | 说明 |
|------|------|
| `CMB.zip` | 从 GitHub 下载的原始压缩包 |
| `CMB-test-choice-answer.json` | 从 GitHub 下载的原始答案文件 |
| `CMB_unzipped/` | `CMB.zip` 解压后的内容 |
| `prepare_cmb_data.py` | 采样、清洗、转换为 JSONL 的脚本 |
| `cmb-medical-qa.jsonl` | 单项选择题评测数据（280 条） |
| `cmb-medical-multi-qa.jsonl` | 多项选择题评测数据（169 条） |

## 采样与清洗逻辑

CMB 测试集共 11,200 道题，其中包含：

- 单项选择题：9,999 道
- 多项选择题：1,190 道
- C 型选择题：11 道

本次评测同时生成单选和多选两类数据：

- 单项选择题 + C 型选择题：共 10,010 道，按 `exam_class` 每类采样 10 道，共 280 道
- 多项选择题：共 1,190 道，按 `exam_class` 每类采样 10 道（不足 10 道的类全取），共 169 道

题目文本会拼接为：

```text
题干
A. 选项A
B. 选项B
C. 选项C
D. 选项D
E. 选项E
```

标准答案为选项字母（如 `B`）。单选使用 `exact_match_ci` 评分；多选的答案
会转换为字母列表（如 `["A","C","D"]`），并在上传时声明
`answer_policy={"multi_answer": "set", "reject_extra": true}`，要求预测集合与
标准答案集合完全一致，多选错误项会扣分。

## 重新生成数据

```powershell
cd D:\code\benchmarkv1\sample-data\cmb_medical_eval
python prepare_cmb_data.py
```

脚本会重新从解压后的原始文件采样，并覆盖 `cmb-medical-qa.jsonl` 和
`cmb-medical-multi-qa.jsonl`。

## 运行评测

```powershell
cd D:\code\benchmarkv1\backend
uv run python scripts\run_cmb_eval.py
```

结果会写入 `docs\cmb-medical-eval\`。
