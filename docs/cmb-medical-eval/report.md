## 执行摘要

本报告基于两个模型（DeepSeek V4 Flash 和 DeepSeek V3）在两组医学问答数据集（单答案 `cmb-medical-qa` 和多答案 `cmb-medical-multi-qa`）上的实验数据。关键发现如下：

- 在单答案任务上，DeepSeek V3 的准确率（90.36%）高于 DeepSeek V4 Flash（86.79%），但 McNemar 检验 p 值为 0.0755（≥0.05），差异不具有统计学显著性。
- 在多答案任务上，DeepSeek V4 Flash 的准确率（69.23%）显著高于 DeepSeek V3（57.99%），p 值为 0.000546（<0.05），差异显著。
- 所有实验均无失败样本（`failure_count = 0`），运行稳定。
- 成本方面，DeepSeek V4 Flash 的 token 消耗量更大，但两个模型均显示零成本（可能为免费调用）。

## 性能分析

### 单答案数据集（`cmb-medical-qa`）

| 模型 | 准确率 | 95% Wilson 置信区间 | 平均延迟 (ms) | 平均每行延迟 (ms) |
|------|--------|---------------------|---------------|-------------------|
| DeepSeek V4 Flash | 86.79% | [82.32%, 90.26%] | 2360.8 | 2364.1 |
| DeepSeek V3 | 90.36% | [86.33%, 93.29%] | 1998.9 | 2002.2 |

- 准确率差异：DeepSeek V3 高出 3.57 个百分点。
- 置信区间有重叠，McNemar 检验 p = 0.0755，差异不显著。
- 在 280 对样本中，DeepSeek V4 Flash 正确而 V3 错误的有 8 例，V3 正确而 V4 错误的有 18 例。

### 多答案数据集（`cmb-medical-multi-qa`）

| 模型 | 准确率 | 95% Wilson 置信区间 | 平均延迟 (ms) | 平均每行延迟 (ms) |
|------|--------|---------------------|---------------|-------------------|
| DeepSeek V4 Flash | 69.23% | [61.91%, 75.70%] | 3262.1 | 3265.4 |
| DeepSeek V3 | 57.99% | [50.45%, 65.17%] | 2346.2 | 2349.3 |

- 准确率差异：DeepSeek V4 Flash 高出 11.24 个百分点。
- 置信区间无重叠，McNemar 检验 p = 0.000546，差异显著，DeepSeek V4 Flash 显著优于 DeepSeek V3。
- 在 169 对样本中，DeepSeek V4 Flash 正确而 V3 错误的有 24 例，V3 正确而 V4 错误的有 5 例。

### 延迟对比

- 在两个数据集上，DeepSeek V3 的延迟均低于 DeepSeek V4 Flash（单答案快约 362 ms/行，多答案快约 916 ms/行）。

## 成本分析

所有实验的 `total_cost` 均为 0.0，但 `cost_unknown` 标记不同：DeepSeek V4 Flash 的两个实验均为 `true`（成本未知），DeepSeek V3 的两个实验均为 `false`（成本已知且为 0）。这可能意味着 DeepSeek V4 Flash 的实际成本未被记录，而 DeepSeek V3 的调用是免费的。从 token 消耗来看：

- 单答案任务：DeepSeek V4 Flash 消耗 51,191 tokens，DeepSeek V3 消耗 29,600 tokens。
- 多答案任务：DeepSeek V4 Flash 消耗 43,166 tokens，DeepSeek V3 消耗 19,733 tokens。

DeepSeek V4 Flash 的 token 使用量约为 DeepSeek V3 的 1.7~2.2 倍，结合延迟更长，在相同定价下成本会更高。但由于成本均为 0，无法直接比较真实花销。

## 失败分析

所有实验的 `failure_count` 均为 0，表明无因提供者错误、指标错误或未处理行导致的失败样本。`sample_failures` 中列出了一些不匹配的示例，但仅用于说明模型输出与正确答案的差异，并非总错误数。例如：

- 在单答案任务中，DeepSeek V4 Flash 有 2 个样本输出为空（因 `finish_reason=length`），导致得分为 0。
- 在多答案任务中，两个模型均存在过度预测的问题（如输出包含多余选项），导致与正确答案不匹配。

总体而言，模型运行稳定，无系统级失败。

## 建议

1. **任务类型选择**：对于单答案选择题，DeepSeek V3 与 V4 Flash 性能差异不显著，但 V3 延迟更低，成本更优；对于多答案选择题，DeepSeek V4 Flash 显著优于 V3，建议优先使用 V4 Flash。
2. **输出截断问题**：DeepSeek V4 Flash 在单答案任务中出现了因 `finish_reason=length` 导致空输出的情况，建议检查模型 max_tokens 设置或调整 prompt 以鼓励完整输出。
3. **成本监控**：目前 DeepSeek V4 Flash 的成本信息缺失，建议启用成本核算，以便进行更完整的性价比分析。
4. **多答案任务优化**：两个模型在多答案任务中均偶有“多选”或“漏选”的情况，可考虑针对输出格式增加约束（如强制输出逗号分隔的选项列表），并针对多答案场景进行微调或 prompt 优化。

## 下一步行动

1. **验证输出截断问题**：对 DeepSeek V4 Flash 在单答案任务中的空输出样本进行复现，调整 `max_tokens` 或 prompt 后重新测试。
2. **扩展多答案测试**：在更多多答案医学数据集上评估 DeepSeek V4 Flash，确认其优势是否泛化。
3. **成本评估**：获取 DeepSeek V4 Flash 的实际定价，结合 token 消耗和延迟，计算并对比两个模型的成本效益。
4. **统计显著性确认**：随着更多数据加入，重新计算 McNemar 检验，以确认单答案任务中差异是否可能变得显著。
5. **错误模式分析**：基于 `sample_failures` 中的错误案例，进行更细粒度的错误类型分类（如知识错误、逻辑错误、格式错误），为模型优化提供方向。