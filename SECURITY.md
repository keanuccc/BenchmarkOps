# Security Policy

## 报告漏洞

如果发现安全漏洞，请**不要**创建公开 Issue。请直接联系仓库维护者，并在邮件中
包含：影响范围、复现步骤、建议修复方案。

## 已处理事件

### 2026-08：示例 API Key 泄露

- **事件**：开发早期将 Qiniu Cloud AI 的 API Key 以示例形式写入
  `.agents/skills/maas/references/openapi.json` 并提交到公开仓库。
- **处置**：
  1. 相关密钥已在七牛云控制台吊销并重新生成；
  2. 工作区中所有真实 Key 已替换为占位符；
  3. `.gitignore` 覆盖 `.env` / `.env.local`，防止再次提交；
  4. 本文档记录事件，供后续审计。
- **建议**：如果 fork 过本仓库，请检查自己的历史中是否包含该 Key，并立即吊销。

## 密钥管理规范

- 所有 API Key 只允许存在于本地 `backend/.env`（已被 `.gitignore` 忽略），
  禁止写入任何会提交的文件（含文档、示例、测试夹具）。
- 提交前使用 `gitleaks` 或 GitHub Secret Scanning 扫描；CI 已集成
  `.github/workflows/secret-scan.yml`（历史已知泄露在 `.gitleaks.toml` 白名单中，
  完成历史重写后移除）。
- 生产环境必须设置 `API_TOKEN`：`APP_ENV=production` 且未设置时应用拒绝启动。
- SSE 进度流校验 `?token=` 参数；写接口校验 `Authorization: Bearer <token>`。

## 支持的版本

仅维护 `main` 分支的最新版本。
