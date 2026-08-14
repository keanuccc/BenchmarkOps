# AI 评测报告

## 执行摘要

本报告覆盖 **2** 个实验，总花费 **$0**，共消耗 **7692** 个令牌，累计运行 **104473 毫秒**。

综合准确率最高的是 **DeepSeek V3 (Qiniu) | humaneval-coding** （DeepSeek V3 (Qiniu)），达到 **100.0%**。

## 性能分析

| 实验 | 模型 | 准确率 | 覆盖率 | 失败率 | 平均延迟(毫秒) | 已评分行数 | 失败行数 |
|---|---|---|---|---|---|---|---|
| DeepSeek V4 Flash (Qiniu) | humaneval-coding | deepseek/deepseek-v4-flash | 90.00 | 100.00 | 0.00 | 5192.00 | 10 | 0 |
| DeepSeek V3 (Qiniu) | humaneval-coding | DeepSeek V3 (Qiniu) | 100.00 | 100.00 | 0.00 | 4908.80 | 10 | 0 |

## 成本分析

总花费：**$0**，共 **7692** 个令牌。
最省钱的实验：**DeepSeek V4 Flash (Qiniu) | humaneval-coding** （$0.00，deepseek/deepseek-v4-flash）。
- DeepSeek V4 Flash (Qiniu) | humaneval-coding：$0.00 （5016 个令牌）
- DeepSeek V3 (Qiniu) | humaneval-coding：$0.00 （2676 个令牌）

## 失败分析

在检查的结果中未检测到失败样本。

## 建议

在对准确率敏感的场景中，采用 **DeepSeek V3 (Qiniu)**（DeepSeek V3 (Qiniu) | humaneval-coding）作为基线（实测最高准确率为 100.0%）。
在对成本敏感的路径中，可考虑 **deepseek/deepseek-v4-flash** （$0.00）作为更省钱的替代方案。
排查 **DeepSeek V4 Flash (Qiniu) | humaneval-coding** —— 其失败样本数最多，可能需要调整提示词或数据。

## 下一步行动

1. 逐个实验查看「性能分析」与「失败分析」部分。
2. 在质量关键处推广使用准确率最高的模型。
3. 针对失败率偏高的实验，调优提示词或筛选逻辑。
4. 应用改动后重新生成本报告，以跟踪改进情况。