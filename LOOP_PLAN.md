# BenchmarkOps Loop 迭代优化计划

## 目标

通过多轮循环审视，从生产环境视角发现并修复所有不合理之处，直到项目在正常生产环境中完美运行。

---

## 第一轮：架构与安全性审查

### 1.1 认证与安全 (高优先级)

**问题**：当前认证系统极度薄弱
- `backend/app/core/security.py` 中 `require_auth` 只是检查 `api_token` 是否为空，为空则跳过
- 没有 JWT、没有角色权限、没有 API key 管理 UI
- 前端 API 调用完全不传递 token（`frontend/src/lib/api.ts` 的 headers 只有 `Content-Type`）
- 健康端点 `/health` 不需要认证，但所有 CRUD 端点都需要——中间没有统一的 auth middleware

**优化方向**：
- 引入 JWT 或至少一个可管理的 API Token
- 在 Settings 页面提供 Token 配置 UI
- 前端 `api.ts` 自动附加 token 到每个请求
- 添加 RBAC 基础（admin / viewer）

### 1.2 数据库架构 (高优先级)

**问题**：
- 生产环境使用 SQLite，不支持并发写入（虽然有 WAL + retry 机制，但本质仍是瓶颈）
- 没有 Alembic 迁移管理——`backend/app/migrations/__init__.py` 是手写迁移，不是标准方案
- 没有数据库备份/恢复机制
- `backend/app/core/database.py` 中的 `busy_timeout=15000` 意味着如果两个进程同时写，一个要等 15 秒

**优化方向**：
- 集成 Alembic 做版本化迁移
- 提供 PostgreSQL 连接字符串的一键切换
- 添加定期备份端点（SQLite → 文件导出）
- 考虑连接池配置优化

### 1.3 后台任务队列 (高优先级)

**问题**：
- `backend/app/evaluation/task_queue.py` 使用 `AsyncioTaskQueue`——进程内线程，应用重启即丢失所有任务
- 没有任务持久化、没有重试机制、没有死信队列
- 没有任务监控 UI——用户不知道任务是否被吞了
- 多个实验同时运行时只有一个全局 semaphore，无法按项目隔离

**优化方向**：
- 短期：任务状态持久化到 DB（queued/running/completed/failed）
- 中期：引入 Celery + Redis 或 ARQ
- 添加任务监控端点和 UI
- 支持任务优先级和取消

---

## 第二轮：用户体验与工作流

### 2.1 实验创建流程 (中优先级)

**问题**：
- `frontend/src/app/experiments/page.tsx` 的新建实验表单需要手动选择 6 个字段
- 下拉菜单没有搜索功能——当项目有 50+ 个数据集时体验很差
- 没有参数配置 UI（temperature、max_tokens 等硬编码在 runner 里）
- 模板复用功能有 bug：`applyTemplate` 函数返回后代码继续执行（return 后还有代码）

**优化方向**：
- 添加带搜索的下拉（Combobox 组件）
- 添加温度/最大 token 等参数的滑块输入
- 修复 applyTemplate 的语法错误（return 后面的代码不会被执行）
- 添加批量创建实验（同一 prompt/dataset/benchmark 换多个模型）

### 2.2 实时进度反馈 (中优先级)

**问题**：
- 实验详情页每 1 秒轮询一次（`frontend/src/app/experiments/[id]/page.tsx` line 74），高频轮询在大量用户时是负担
- 没有 WebSocket/SSE 推送机制
- 进度条只展示"已评分/失败/共多少"，缺少 ETA 估算
- 实验完成后没有通知机制

**优化方向**：
- 改用 Server-Sent Events (SSE) 替代轮询
- 添加 ETA 估算（基于已处理行的平均速度）
- 添加邮件/Webhook 通知
- 仪表盘显示实时运行中的实验数

### 2.3 数据集管理 (中优先级)

**问题**：
- 上传界面缺少文件预览和 schema 验证
- 没有数据集版本管理——同名数据集覆盖后无法回滚
- 大文件（接近 50MB）上传时没有进度条
- CSV 编码检测缺失（Windows 默认 GBK 编码的 CSV 会解析失败）

**优化方向**：
- 上传前预览前 10 行
- 添加数据集版本（version 字段已有但未被正确使用）
- 上传进度条（FormData onUploadProgress）
- 智能编码检测（chardet fallback）

### 2.4 提示词管理 (低优先级)

**问题**：
- 没有提示词预览/测试功能——用户写了 template 不知道实际渲染效果
- 没有提示词版本对比
- 变量检测是手动的，容易遗漏

**优化方向**：
- 添加"测试提示词"按钮，用第一条数据预览渲染结果
- 提示词 diff 视图
- 自动检测 template 中的 `{variable}` 并提示未定义的变量

---

## 第三轮：评估引擎与指标

### 3.1 答案提取 (高优先级)

**问题**：
- `backend/app/evaluation/runner.py` 中 `_extract_answer` 有 ~70 行正则表达式
- 正则覆盖了 10+ 种模式，但每种模式的覆盖率未经测试验证
- 没有单元测试覆盖所有 edge case（中文标点、嵌套括号、多行 CoT 等）
- 不同 benchmark type 共用同一套提取逻辑

**优化方向**：
- 将提取规则按 benchmark type 分类（qa/coding/classification）
- 补充全面的单元测试（至少 30+ edge cases）
- 考虑用 LLM 做答案提取（作为可选策略）
- 添加提取质量诊断（显示提取前后的对比）

### 3.2 评分指标 (中优先级)

**问题**：
- `exact_match_ci` 对 CJK 文本过于严格——"北京" 和 "北京市" 不匹配
- `f1_token` 依赖 jieba，但 jieba 未出现在 requirements.txt 中
- `llm_judge` 没有缓存——相同 prediction+expected 每次都调 LLM
- 没有自定义指标 UI——用户不能添加自己的评分逻辑

**优化方向**：
- 添加 fuzzy match（Levenshtein distance）
- 将 jieba 加入依赖或实现纯 Python 分词
- LLM judge 结果缓存（prediction hash + expected hash → score）
- 添加指标配置 UI（权重调节、自定义阈值）

### 3.3 实验快照 (中优先级)

**问题**：
- `benchmark_snapshot` 只存了 metric 和 metric_config，没有存 spec
- `model_snapshot` 缺了 name 以外的关键信息（如 provider）
- 旧实验没有 snapshot，runner 回退到实时查询——可能导致不一致

**优化方向**：
- 补全所有必要字段的快照
- 添加快照版本（schema_version）
- 对旧实验提供迁移脚本

---

## 第四轮：前端 UI/UX 深度审查

### 4.1 响应式与无障碍 (中优先级)

**问题**：
- 侧边栏固定 248px 宽度，在小屏幕（< 1280px）上可能拥挤
- 没有移动端适配——实验结果表格在小屏幕上无法横向滚动
- 没有键盘导航支持
- 颜色对比度未通过 WCAG 检测

**优化方向**：
- 添加可折叠侧边栏（图标模式）
- 实验结果表格改为卡片布局（移动端）
- 添加 `aria-label` 和键盘快捷键
- 运行 axe-core 无障碍审计

### 4.2 错误处理 (高优先级)

**问题**：
- 前端全局 unhandled rejection guard 只 console.error，不通知用户
- 后端 500 错误统一返回 "Internal server error"，前端只显示一段文字
- 网络断开后没有自动重连机制
- 表单提交失败后用户不知道哪里错了

**优化方向**：
- 添加 toast 通知系统（react-hot-toast 或自建）
- 网络断开时显示 banner + 自动重连
- 后端错误返回更具体的 code（已有部分实现，但前端没利用）
- 表单级联验证错误

### 4.3 性能优化 (中优先级)

**问题**：
- 首页一次性加载 projects + experiments + leaderboard + models——4 个并行请求
- 实验结果列表无分页——10000 行数据直接渲染 table
- 图表库 ECharts 没有懒加载
- 没有 SWR/React Query 做请求缓存和去重

**优化方向**：
- 引入 React Query 或 SWR 做数据获取管理
- 实验结果表格虚拟化（react-window）+ 服务端分页
- 图表按需懒加载
- 首页数据分片加载（先 KPI，后图表）

---

## 第五轮：可观测性与运维

### 5.1 日志与监控 (高优先级)

**问题**：
- 日志格式简单（`%(asctime)s %(levelname)s %(name)s %(message)s`），没有 trace_id
- 没有结构化日志（JSON format）
- 没有 metrics 暴露端点（Prometheus）
- 没有 APM 集成

**优化方向**：
- 添加 request_id / trace_id 贯穿整个请求链路
- 结构化日志（python-json-logger）
- 添加 `/metrics` 端点（prometheus-fastapi-instrumentator）
- 关键操作审计日志（谁在什么时候创建了/删除了什么）

### 5.2 健康检查 (中优先级)

**问题**：
- `/health` 只检查 DB 连通性，不检查 provider 可用性
- 没有 readiness probe——应用启动后可能还在加载 provider 列表
- Kubernetes 风格的 liveness/readiness 分离缺失

**优化方向**：
- 添加 `/ready` 端点（DB + Provider + Task Queue）
- 添加 provider 健康检查（定期 ping OpenRouter/Qiniu API）
- 分离 liveness（进程存活）和 readiness（服务可用）

### 5.3 配置管理 (中优先级)

**问题**：
- 所有配置在 `.env` 文件中，没有 UI 管理
- 敏感信息（API keys）明文存储
- 没有配置验证——错误的配置直到运行时才发现

**优化方向**：
- Settings 页面添加环境变量管理（隐藏 API key 显示）
- 启动时验证关键配置（DB URL、provider keys）
- 添加配置变更通知

---

## 第六轮：业务场景覆盖

### 6.1 典型工作流验证

**场景 1: 学术研究——比较 10 个模型的答题准确率**
- 需要：批量导入数据集、创建多个实验、一键对比
- 缺口：目前需要逐个创建实验，没有"批量对比"工作流

**场景 2: 产品团队——评估 prompt 优化效果**
- 需要：同一模型 + 不同 prompt 的 A/B 测试
- 缺口：没有 A/B test 专用视图，只能手动筛选

**场景 3: 工程团队——回归测试**
- 需要：每次模型更新后自动跑基准测试
- 缺口：没有定时任务、没有 CI/CD 集成

**场景 4: 企业客户——私有数据集评测**
- 需要：RBAC、数据隔离、审计日志
- 缺口：完全没有多租户支持

### 6.2 报告系统 (中优先级)

**问题**：
- 报告生成是静态 Markdown，没有 PDF/HTML 导出
- 没有报告模板自定义
- 报告不能分享/协作评论

**优化方向**：
- 添加 PDF 导出（weasyprint 或 puppeteer）
- 报告模板市场
- 分享链接（带访问控制）

---

## 第七轮：代码质量

### 7.1 类型安全 (低优先级)

**问题**：
- `backend/app/evaluation/metrics.py` 中 `contains` 函数签名 `def contains(prediction: str, expected: str, default=0.0)` — `default` 应该是 keyword-only
- 部分 service 方法返回 `Sequence[Experiment]` 但实际可能是 list 或 tuple
- `frontend/src/app/experiments/page.tsx` 中有未使用的 import

### 7.2 测试覆盖 (中优先级)

**问题**：
- 测试文件散落在 `backend/tests/`，但没有 pytest.ini 或 conftest.py 的统一配置
- 没有 integration test（runner + provider + DB 完整链路）
- 前端没有测试（`api-timeout.test.ts` 是唯一的前端测试）

**优化方向**：
- 完善 conftest.py（fixture 管理 DB session、test client）
- 添加端到端测试（Playwright）
- 前端 component test（Testing Library）

---

## 迭代执行计划

每轮迭代遵循以下流程：
1. **审视**：列出本轮要检查的所有问题
2. **修复**：逐个解决发现的问题
3. **验证**：运行测试 + 手动体验
4. **记录**：将发现的问题和改进写入 changelog

### 建议的执行顺序

```
Round 1 → Round 4 → Round 3 → Round 2 → Round 5 → Round 6 → Round 7
  ↑                              ↑              ↑
 安全/架构基础                  用户体验       可观测性
```

先从安全和架构开始，再修用户体验，最后打磨可观测性和代码质量。
