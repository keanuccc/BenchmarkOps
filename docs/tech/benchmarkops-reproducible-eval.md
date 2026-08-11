# 把 AI 评测做成可信工程：BenchmarkOps 的可复现性、脱敏与审计设计

> AI 评测平台最容易被质疑的不是"测不准"，而是"结果不可信"。本文拆解 BenchmarkOps
> 在**可复现、数据安全、审计追溯**三个方向上的设计取舍。

## 1. 可复现性：评测结果为什么常常不可复现

一次模型评测的结果由五个要素决定：**数据集内容、基准（评分协议）、提示词、
模型（含 Provider 路由）、运行参数**。任何一个要素在评测后发生变更，历史结果就
失去可比性——比如数据集被原地修改、模型 Provider 从 A 网关切到 B 网关、提示词
模板被后人改了。

BenchmarkOps 的做法是"**快照 + 版本**"：

- **数据集不可原地修改**。上传后只能通过 `POST /datasets/{id}/versions` 创建
  新版本（追加或替换），旧版本保留可回滚；实验创建时记录 `dataset_version`，
  后续永远按当时的版本读取数据。
- **实验创建时快照模型路由**。模型表里保存 Provider、model_id、pricing，
  实验运行时再把这些信息固化到实验记录上——即使之后把默认网关从七牛切到
  OpenRouter，历史实验的 Provider 路由不会跟着漂移。
- **提示词版本化**。提示词模板有版本号，实验创建时同样快照。
- **每行数据保留 SHA-256 content_hash**，从存储层保证"这一行就是当时那一行"。

一句话总结：**评测记录的不是"现在跑一遍会得到什么"，而是"当时那组输入在当时的
环境里跑出了什么"**。

## 2. 数据安全：敏感字段脱敏

企业场景的真实评测数据往往含个人信息（客服对话、用户 ID、手机号）。把原始数据
直接展示在评测结果页，本身就是安全事故。

实现分三层：

1. **字段级声明**：上传数据集时，通过 `sensitive_fields` 声明哪些列是敏感字段；
2. **预览与结果脱敏**：声明后，数据集预览接口和实验结果接口（
   `?mask_sensitive=true`）返回脱敏后的值；
3. **PII 模式识别兜底**：除了字段声明，redaction 层内置常见 PII 模式
   （手机号、邮箱、身份证号等）的识别与打码，防止"漏声明"的字段裸奔。

配合脱敏的是**审计**：数据集的创建、版本切换、激活、归档、删除、导入都会写入
`audit_events`，谁在什么时候动了哪个数据集，全部可查。

## 3. 鉴权：从 Demo 到生产的门槛

一个容易被忽略的问题：评测平台的接口大多只读，但**触发评测 = 花钱**。

BenchmarkOps 的鉴权设计刻意做了分级：

- 开发 / Demo 模式：`API_TOKEN` 为空，写接口不强制鉴权，方便离线演示；
- 生产模式：`APP_ENV=production` 且未设置 `API_TOKEN` 时**拒绝启动**——用配置
  强制上线前必须设置鉴权；
- SSE 进度流：`EventSource` 无法设置 Authorization 头，因此 `/experiments/{id}/stream`
  改为校验 `?token=` 参数，避免鉴权被"流式接口"绕过。

## 4. 事故复盘：API Key 曾经入库

这个项目真实发生过一次密钥泄露（开发期把 Qiniu API Key 当作示例写进了
`references/openapi.json` 并提交）。处理方式：

1. **立即吊销并重新生成密钥**（本地 `.env` 中已替换）；
2. 从当前工作区删除该文件中的密钥，改为占位符；
3. README 中明确记录事件与处理方式，而不是藏着；
4. `.gitignore` 覆盖 `.env` / `.env.local`，从机制上防止再次提交。

教训：**密钥管理不能靠"记得别提交"，要靠工具链**——`.gitignore`、GitHub
Secret Scanning、提交前钩子（gitleaks）三者缺一不可。

## 5. 这些设计如何被验证

- `tests/test_audit_sensitive.py`：敏感字段脱敏 + 审计事件；
- `tests/test_redaction_pii.py`：PII 模式识别与打码；
- `tests/test_benchmark_spec_snapshot.py`：实验创建时基准/提示词快照；
- `tests/test_auth.py`：生产环境强制鉴权、SSE token 校验；
- 后端 334 个单测 + Playwright E2E 接入 GitHub Actions。

---

相关代码：`backend/app/services/redaction.py`、`backend/app/middleware.py`、
`backend/app/services/analytics_service.py`；文档：`USAGE.md`、
`docs/DATA_PREPARATION_GUIDE.md`。
