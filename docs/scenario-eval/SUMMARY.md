# BenchmarkOps 测试优化总报告

> 汇总日期：2026-08-12 · 覆盖 14 轮测试优化 · 最终回归全绿

## 1. 结论

经过 14 轮端到端测试与优化，BenchmarkOps 全功能面验证通过：后端 465 passed，
前端 E2E 8/8，双真实网关（Qiniu/OpenRouter）可用，共修复 9 个真实问题 +
2 个小问题。平台达到可稳定交付状态。

## 2. 覆盖范围

| 维度 | 内容 |
|------|------|
| 五类基准 | qa / classification / coding / agent / generation（自造真实场景数据，从原始数据到报告） |
| 数据格式 | JSONL / CSV / TSV / XLSX（含中文/BOM/引号） |
| 进阶链路 | 多轮对话/few-shot、敏感字段脱敏、数据集版本化、异步导入、多答案/别名、并发、取消、Webhook、定时调度、llm_judge、多租户、prep、压力、审计 |
| 真实网关 | Qiniu（deepseek-v4-flash 80%）与 OpenRouter（gpt-4o-mini 50%）实测 |
| CLI | run --wait / check-regression / export-report / pack apply / webhook test |
| 前端 | Playwright 完整 UI 流程、4 边界、3 新功能交互（组织/定时报告/Webhook） |
| 报告 | Markdown/HTML/PDF（中文渲染修复）、AI 报告（双网关） |
| 安全 | API_TOKEN 鉴权、多租户隔离、SSE 隔离、脱敏防旁路泄漏 |

## 3. 修复清单（11 项）

1. 取消实验接口 500（跨 session 更新 ORM 对象）
2. 敏感数据旁路泄漏：结果/失败案例/对比/报告统一脱敏，升级文本级 PII
3. PDF 报告中文乱码（reportlab 注册 CJK 字体）
4. SSE datetime 序列化崩溃（实验详情页永远 Loading）
5. AI 报告默认模型与网关不匹配（Qiniu 400，按 provider 选模型）
6. seed 模型网关路由错误（provider 统一 openrouter + 存量修复脚本）
7. multi_answer 模式 aliases 被忽略（exact_match_ci 支持别名命中）
8. /db/backup/list 被 {filename} 路由遮蔽
9. API_TOKEN 模式下创建组织可匿名调用
10. AI 报告 generated_by 标记错误（显示实际 provider）
11. 定时报告 format 字段仅记录（已文档化，导出按需转换）

## 4. 测试资产

- 后端脚本：scripts/run_scenarios.py、run_advanced_a/b/c/d/e.py、
  run_real_provider.py、fix_model_providers.py、acceptance_e2e.py、bmops.py
- 前端 E2E：frontend/e2e/（test_flow / test_edge / test_new_features）
- 单测：新增 40+ 项（脱敏、PDF 中文、SSE 隔离、别名、报告模型、备份路由等）
- 文档：docs/scenario-eval/（SCENARIOS / ADVANCED_LINKS / SUMMARY）
- 原始数据：sample-data/scenarios/（五场景真实风格数据）

## 5. 已知项

- 定时报告 format 字段为交付偏好标记（导出端点按需转换）；
- 被旧实验引用的 legacy 重复模型保留（引用保护，可在模型中心停用）；
- 七牛网关仅支持其平台模型（deepseek-v4-flash 等），选其他 seed 模型会 400。

## 6. 复现

```bash
# 后端测试
cd backend && .\.venv\Scripts\python.exe -m pytest -q
# 五场景 + 进阶链路（Mock，离线）
python scripts/run_scenarios.py
python scripts/run_advanced_a.py
python scripts/run_advanced_b.py
python scripts/run_advanced_c.py
python scripts/run_advanced_d.py
python scripts/run_advanced_e.py
# 真实 Provider（需 .env Key，极小费用）
python scripts/run_real_provider.py
# 前端 E2E（8001 Mock + 3001 前端）
cd frontend/e2e && BASE_URL=http://localhost:3001 pytest -v
```


## 7. 用户视角验收（第十六轮，真实 3000 前端）

- 全场景评测项目在 UI 完整可见：5 数据集 / 5 基准 / 5 提示词 / 5 实验，无前端错误日志；
- 实验详情页：准确率与逐行结果显示正常；
- 对比页：准确率图表、模型路由建议正常；勾选恰好 2 个实验时错误案例对比正常出现；
- 用户打开 http://localhost:3000 即可直接查看全部测试成果。
