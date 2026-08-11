"use client";

import { useEffect, useState } from "react";
import { API_BASE_URL, getHealth, getApiTokenStatus, updateApiToken, getDbConfig, getMigrationStatus, createBackup, listBackups, type HealthResponse, type ApiTokenStatus, type DbConfigInfo, type MigrationStatusData, type DbBackupEntry } from "@/lib/api";
import { setApiToken as setLocalToken } from "@/lib/api";
import { Card, Badge, EmptyState, Spinner, SectionTitle, Button } from "@/components/ui";
import { useToast } from "@/components/notifications";
import { OrganizationManager } from "@/components/organization-manager";
import { Settings, Server, KeyRound, Shield, Eye, EyeOff, CheckCircle, XCircle, Database, HardDrive, GitBranch, Download, Trash2 } from "lucide-react";

// Backup endpoints live under /db (outside the /api/v1 prefix). Derive the
// backend base from the same API_BASE_URL used by the typed client.
const BACKUP_BASE_URL = API_BASE_URL.replace(/\/api\/v1$/, "");

export default function SettingsPage() {
  const { addToast } = useToast();
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tokenStatus, setTokenStatus] = useState<ApiTokenStatus | null>(null);
  const [tokenLoading, setTokenLoading] = useState(false);
  const [tokenForm, setTokenForm] = useState({ token: "", confirmPassword: "" });
  const [tokenFeedback, setTokenFeedback] = useState<{ ok: boolean; msg: string } | null>(null);
  const [showToken, setShowToken] = useState(false);
  const [dbConfig, setDbConfig] = useState<DbConfigInfo | null>(null);
  const [migrationStatus, setMigrationStatus] = useState<MigrationStatusData | null>(null);
  const [backupLoading, setBackupLoading] = useState(false);
  const [backups, setBackups] = useState<DbBackupEntry[]>([]);
  const [backupFeedback, setBackupFeedback] = useState<{ ok: boolean; msg: string } | null>(null);

  useEffect(() => {
    Promise.all([
      getHealth(),
      getApiTokenStatus().catch(() => null),
      getDbConfig().catch(() => null),
      getMigrationStatus().catch(() => null),
    ])
      .then(([h, t, db, mig]) => {
        setHealth(h);
        setTokenStatus(t);
        setDbConfig(db);
        setMigrationStatus(mig);
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : "加载数据失败,请检查后端是否在线。");
      })
      .finally(() => setLoading(false));
  }, []);

  async function handleSaveToken() {
    if (!tokenForm.token.trim()) {
      setTokenFeedback({ ok: false, msg: "请输入 API Token" });
      return;
    }
    if (tokenForm.token !== tokenForm.confirmPassword) {
      setTokenFeedback({ ok: false, msg: "两次输入的 Token 不一致" });
      return;
    }
    setTokenLoading(true);
    setTokenFeedback(null);
    try {
      const result = await updateApiToken(tokenForm.token);
      setTokenStatus(result);
      setLocalToken(tokenForm.token);
      setTokenForm({ token: "", confirmPassword: "" });
      addToast("success", "API Token 已保存。");
      setTokenFeedback(null);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "保存失败";
      setTokenFeedback({ ok: false, msg });
    } finally {
      setTokenLoading(false);
    }
  }

  async function handleRemoveToken() {
    setTokenLoading(true);
    try {
      await updateApiToken("");
      setTokenStatus({ enabled: false, masked: "" });
      setLocalToken(null);
      addToast("success", "API Token 已移除。");
      setTokenFeedback(null);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "移除失败";
      setTokenFeedback({ ok: false, msg });
    } finally {
      setTokenLoading(false);
    }
  }

  async function handleBackup() {
    setBackupLoading(true);
    setBackupFeedback(null);
    try {
      await createBackup();
      // Refresh backup list
      const list = await listBackups();
      setBackups(list);
      addToast("success", `备份创建成功 (${list.length} 个文件)`);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "备份失败";
      addToast("error", msg);
      setBackupFeedback({ ok: false, msg });
    } finally {
      setBackupLoading(false);
    }
  }

  async function handleDeleteBackup(filename: string) {
    if (!confirm(`确定删除备份 ${filename}？`)) return;
    try {
      const res = await fetch(`${BACKUP_BASE_URL}/db/backup/${filename}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error("删除失败");
      setBackups((prev) => prev.filter((b) => b.filename !== filename));
      setBackupFeedback({ ok: true, msg: `备份 ${filename} 已删除` });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "删除失败";
      setBackupFeedback({ ok: false, msg });
    }
  }

  function formatTime(ts: number): string {
    return new Date(ts * 1000).toLocaleString("zh-CN");
  }

  if (loading) {
    return <EmptyState message="Loading…" icon={<Spinner size={20} />} />;
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">设置</h1>
        <p className="mt-1 text-sm text-[var(--ocd-text-muted)]">
          后端连接、认证配置与环境参数。
        </p>
      </header>

      {error && (
        <Card className="p-5">
          <p className="text-sm" style={{ color: "var(--ocd-bad)" }}>
            {error}
          </p>
        </Card>
      )}

      {/* --- API Token Management --- */}
      <Card className="p-5">
        <SectionTitle>
          <span className="flex items-center gap-2">
            <Shield size={14} /> 认证 Token
          </span>
        </SectionTitle>

        {tokenStatus ? (
          <div className="space-y-4">
            <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Row label="状态" value={
                tokenStatus.enabled
                  ? <Badge status="active">已启用</Badge>
                  : <Badge status="pending">未启用（演示模式）</Badge>
              } />
              <Row label="Token 值" value={
                tokenStatus.enabled ? (
                  <span className="font-mono text-xs">
                    {showToken ? tokenStatus.masked : "••••••••••••"}
                    <button
                      onClick={() => setShowToken(!showToken)}
                      className="ml-2 inline-flex items-center gap-1 text-[var(--ocd-text-muted)] hover:text-[var(--ocd-text)]"
                      title={showToken ? "隐藏" : "显示"}
                    >
                      {showToken ? <EyeOff size={12} /> : <Eye size={12} />}
                    </button>
                  </span>
                ) : (
                  <span className="text-[var(--ocd-text-faint)]">—</span>
                )
              } />
            </dl>

            {/* Token form — only editable once auth is enabled; otherwise the
                backend refuses bootstrap changes over HTTP (see settings.py). */}
            {tokenStatus.enabled ? (
              <div className="rounded-lg p-4" style={{ background: "var(--ocd-surface-2)" }}>
                <p className="mb-3 text-sm font-medium">修改 API Token</p>
                <div className="grid gap-3 sm:grid-cols-2">
                  <input
                    type={showToken ? "text" : "password"}
                    placeholder="输入新的 API Token"
                    className="w-full rounded-lg bg-[var(--ocd-bg)] px-3 py-2 text-sm text-[var(--ocd-text)]"
                    style={{ borderColor: "var(--ocd-border)", borderWidth: 1 }}
                    value={tokenForm.token}
                    onChange={(e) => setTokenForm((f) => ({ ...f, token: e.target.value }))}
                  />
                  <input
                    type={showToken ? "text" : "password"}
                    placeholder="确认新 Token"
                    className="w-full rounded-lg bg-[var(--ocd-bg)] px-3 py-2 text-sm text-[var(--ocd-text)]"
                    style={{ borderColor: "var(--ocd-border)", borderWidth: 1 }}
                    value={tokenForm.confirmPassword}
                    onChange={(e) => setTokenForm((f) => ({ ...f, confirmPassword: e.target.value }))}
                  />
                </div>
                <div className="mt-3 flex items-center gap-3">
                  <Button
                    onClick={handleSaveToken}
                    disabled={tokenLoading || !tokenForm.token}
                  >
                    {tokenLoading ? <Spinner size={14} /> : "保存 Token"}
                  </Button>
                  <Button variant="danger" onClick={handleRemoveToken} disabled={tokenLoading}>
                    移除 Token
                  </Button>
                </div>
              </div>
            ) : (
              <div className="rounded-lg p-4" style={{ background: "var(--ocd-surface-2)" }}>
                <p className="mb-3 text-sm font-medium">配置 API Token 以启用认证</p>
                <p className="text-xs text-[var(--ocd-text-faint)]">
                  出于安全考虑，平台不允许在认证未启用时通过网页设置 Token。
                  请由管理员在服务器 backend/.env 中配置 API_TOKEN 并重启后端；
                  启用后即可在此页面修改或移除 Token。
                </p>
              </div>
            )}

            {tokenFeedback && (
              <div
                className="flex items-center gap-2 rounded-lg p-3 text-sm"
                style={{
                  background: tokenFeedback.ok
                    ? "color-mix(in oklch, var(--ocd-ok) 12%, transparent)"
                    : "color-mix(in oklch, var(--ocd-bad) 12%, transparent)",
                  color: tokenFeedback.ok ? "var(--ocd-ok)" : "var(--ocd-bad)",
                }}
              >
                {tokenFeedback.ok ? <CheckCircle size={16} /> : <XCircle size={16} />}
                {tokenFeedback.msg}
              </div>
            )}

            <p className="text-xs text-[var(--ocd-text-faint)]">
              保存后，所有写操作（POST/PATCH/DELETE）将需要携带此 Token。
              读操作（GET）保持公开以便演示浏览。
              Token 保存在浏览器 sessionStorage 中，关闭标签页后清除。
              修改后的 Token 写入后端的 .env 文件，重启后端仍生效。
            </p>
          </div>
        ) : (
          <p className="text-sm text-[var(--ocd-text-faint)]">暂无 Token 状态信息。</p>
        )}
      </Card>

      {/* --- Organizations (multi-tenant) --- */}
      <OrganizationManager />

      {/* --- Backend Connection --- */}
      <Card className="p-5">
        <SectionTitle>
          <span className="flex items-center gap-2">
            <Server size={14} /> 后端连接
          </span>
        </SectionTitle>
        {health ? (
          <dl className="divide-y" style={{ borderColor: "var(--ocd-border-soft)" }}>
            <Row label="状态" value={<Badge status={health.status}>{health.status}</Badge>} />
            <Row label="应用" value={health.app} />
            <Row label="环境" value={health.env} />
            <Row label="数据库" value={<Badge status={health.database}>{health.database}</Badge>} />
            <Row
              label="供应商模式"
              value={<Badge status={health.provider_mode === "real" ? "active" : "pending"}>{health.provider_mode}</Badge>}
            />
          </dl>
        ) : (
          <p className="text-sm text-[var(--ocd-text-faint)]">暂无健康数据。</p>
        )}
      </Card>

      {/* --- Provider Mode --- */}
      <Card className="p-5">
        <SectionTitle>
          <span className="flex items-center gap-2">
            <KeyRound size={14} /> 供应商模式
          </span>
        </SectionTitle>
        <p className="text-sm text-[var(--ocd-text-muted)]">
          当前模式:{" "}
          <Badge status={health?.provider_mode === "real" ? "active" : "pending"}>
            {health?.provider_mode ?? "unknown"}
          </Badge>
        </p>
        <p className="mt-2 text-sm text-[var(--ocd-text-faint)]">
          当供应商模式为 <code className="text-[var(--ocd-text-muted)]">mock</code> 时,
          后端使用合成供应商。在后端配置环境变量{" "}
          <code className="text-[var(--ocd-text-muted)]">OPENROUTER_API_KEY</code>
          或 <code className="text-[var(--ocd-text-muted)]">QINIU_API_KEY</code>{" "}
          即可启用真实模型供应商。
        </p>
      </Card>

      {/* --- Appearance --- */}
      <Card className="p-5">
        <SectionTitle>
          <span className="flex items-center gap-2">
            <Settings size={14} /> 外观
          </span>
        </SectionTitle>
        <p className="text-sm text-[var(--ocd-text-muted)]">
          主题(深色 / 浅色)可在侧边栏切换。默认主题为深色。
        </p>
      </Card>

      {/* --- Database Management --- */}
      <Card className="p-5">
        <SectionTitle>
          <span className="flex items-center gap-2">
            <Database size={14} /> 数据库管理
          </span>
        </SectionTitle>

        {dbConfig ? (
          <div className="space-y-4">
            <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Row label="后端" value={<Badge status={dbConfig.is_sqlite ? "pending" : "active"}>{dbConfig.backend}</Badge>} />
              <Row label="连接池" value={`${dbConfig.pool_size ?? "—"} / max_overflow:${dbConfig.max_overflow}`} />
              <Row label="WAL 模式" value={<Badge status={dbConfig.wal_enabled ? "active" : "pending"}>{dbConfig.wal_enabled ? "已启用" : "未启用"}</Badge>} />
              <Row label="迁移版本" value={
                migrationStatus ? (
                  <span>
                    当前: <strong>{migrationStatus.current_version ?? "0"}</strong>
                    {migrationStatus.pending.length > 0 && (
                      <span className="ml-2 text-xs" style={{ color: "var(--ocd-warn)" }}>
                        ({migrationStatus.pending.length} 待升级)
                      </span>
                    )}
                  </span>
                ) : "—"
              } />
            </dl>

            {/* Migration details */}
            {migrationStatus && (
              <div className="rounded-lg p-3 text-sm" style={{ background: "var(--ocd-surface-2)" }}>
                <p className="mb-2 font-medium text-[var(--ocd-text-muted)]">已应用的迁移</p>
                {migrationStatus.applied.map((m) => (
                  <div key={m.version} className="flex items-center gap-2 py-0.5">
                    <Badge status="active">v{m.version}</Badge>
                    <span className="text-[var(--ocd-text-faint)]">{m.name}</span>
                  </div>
                ))}
                {migrationStatus.pending.length > 0 && (
                  <>
                    <p className="mt-2 mb-1 font-medium text-[var(--ocd-text-muted)]">待应用的迁移</p>
                    {migrationStatus.pending.map((m) => (
                      <div key={m.version} className="flex items-center gap-2 py-0.5">
                        <Badge status="pending">v{m.version}</Badge>
                        <span className="text-[var(--ocd-text-faint)]">{m.name}</span>
                      </div>
                    ))}
                  </>
                )}
              </div>
            )}

            {/* Backup section */}
            {dbConfig.is_sqlite && (
              <div className="rounded-lg p-4" style={{ background: "var(--ocd-surface-2)" }}>
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium">SQLite 备份</p>
                  <Button onClick={handleBackup} disabled={backupLoading || !dbConfig.is_sqlite}>
                    {backupLoading ? <Spinner size={14} /> : "创建备份"}
                  </Button>
                </div>

                {backups.length > 0 && (
                  <div className="mt-3 space-y-2">
                    <table className="w-full text-xs">
                      <thead className="text-left text-[var(--ocd-text-faint)]">
                        <tr>
                          <th className="pb-2 pr-2">文件名</th>
                          <th className="pb-2 pr-2">大小</th>
                          <th className="pb-2 pr-2">修改时间</th>
                          <th className="pb-2 text-right">操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {backups.map((b) => (
                          <tr key={b.filename} className="border-b last:border-0" style={{ borderColor: "var(--ocd-border-soft)" }}>
                            <td className="py-2 pr-2 font-mono">{b.filename}</td>
                            <td className="py-2 pr-2">{b.size_mb} MB</td>
                            <td className="py-2 pr-2">{formatTime(b.modified)}</td>
                            <td className="py-2 text-right">
                              <div className="flex items-center justify-end gap-2">
                                <a
                                  href={`${BACKUP_BASE_URL}/db/backup/${b.filename}`}
                                  download={b.filename}
                                  className="inline-flex items-center gap-1 text-[var(--ocd-accent)] hover:underline"
                                  title="下载备份"
                                >
                                  <Download size={12} />
                                </a>
                                <button
                                  onClick={() => handleDeleteBackup(b.filename)}
                                  className="inline-flex items-center gap-1 text-[var(--ocd-bad)] hover:underline"
                                  title="删除备份"
                                >
                                  <Trash2 size={12} />
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {backupFeedback && (
                  <div
                    className="mt-3 flex items-center gap-2 rounded-lg p-2 text-xs"
                    style={{
                      background: backupFeedback.ok
                        ? "color-mix(in oklch, var(--ocd-ok) 12%, transparent)"
                        : "color-mix(in oklch, var(--ocd-bad) 12%, transparent)",
                      color: backupFeedback.ok ? "var(--ocd-ok)" : "var(--ocd-bad)",
                    }}
                  >
                    {backupFeedback.ok ? <CheckCircle size={14} /> : <XCircle size={14} />}
                    {backupFeedback.msg}
                  </div>
                )}

                <p className="mt-2 text-xs text-[var(--ocd-text-faint)]">
                  备份文件存储在 backend/backups/ 目录下。生产环境建议配置定时备份任务。
                </p>
              </div>
            )}

            {!dbConfig.is_sqlite && (
              <p className="text-xs text-[var(--ocd-text-faint)]">
                PostgreSQL 备份请使用 pg_dump/pg_restore 工具。
              </p>
            )}
          </div>
        ) : (
          <p className="text-sm text-[var(--ocd-text-faint)]">暂无数据库信息。</p>
        )}
      </Card>

      {/* --- PostgreSQL Switch Guide --- */}
      <Card className="p-5">
        <SectionTitle>
          <span className="flex items-center gap-2">
            <GitBranch size={14} /> 数据库切换指南
          </span>
        </SectionTitle>
        <div className="space-y-3 text-sm">
          <p className="text-[var(--ocd-text-muted)]">
            当前使用 <code className="text-[var(--ocd-text)]">SQLite</code>（v1 默认）。
            升级到 PostgreSQL 只需修改 .env 中的 DATABASE_URL：
          </p>
          <pre className="rounded-lg p-3 text-xs overflow-x-auto" style={{ background: "var(--ocd-surface-2)" }}>
{`# 将 SQLite URL 替换为 PostgreSQL URL：
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/benchmarkops`}
          </pre>
          <p className="text-xs text-[var(--ocd-text-faint)]">
            切换后首次启动会自动创建表并运行迁移。注意：SQLite 数据不会自动迁移，
            需要使用 <code>pg_dump</code> / <code>pg_restore</code> 或手动导出导入。
          </p>
        </div>
      </Card>

      {/* --- CORS --- */}
      <Card className="p-5">
        <SectionTitle>CORS</SectionTitle>
        <p className="text-sm text-[var(--ocd-text-faint)]">
          后端允许来自已配置前端来源（origin）的跨域请求。请确保浏览器能访问 API 基础地址
          (NEXT_PUBLIC_API_BASE_URL),且后端 CORS 白名单中包含此前端的来源。
        </p>
      </Card>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div
      className="flex items-center justify-between py-2.5 text-sm"
      style={{ borderColor: "var(--ocd-border-soft)" }}
    >
      <dt className="text-[var(--ocd-text-muted)]">{label}</dt>
      <dd className="font-medium text-[var(--ocd-text)]">{value}</dd>
    </div>
  );
}
