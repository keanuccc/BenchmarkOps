"use client";

import { useEffect, useState } from "react";
import { getHealth, getApiTokenStatus, updateApiToken, type HealthResponse, type ApiTokenStatus } from "@/lib/api";
import { setApiToken as setLocalToken } from "@/lib/api";
import { Card, Badge, EmptyState, Spinner, SectionTitle, Button } from "@/components/ui";
import { Settings, Server, KeyRound, Shield, Eye, EyeOff, CheckCircle, XCircle } from "lucide-react";

export default function SettingsPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tokenStatus, setTokenStatus] = useState<ApiTokenStatus | null>(null);
  const [tokenLoading, setTokenLoading] = useState(false);
  const [tokenForm, setTokenForm] = useState({ token: "", confirmPassword: "" });
  const [tokenFeedback, setTokenFeedback] = useState<{ ok: boolean; msg: string } | null>(null);
  const [showToken, setShowToken] = useState(false);

  useEffect(() => {
    Promise.all([
      getHealth(),
      getApiTokenStatus().catch(() => null),
    ])
      .then(([h, t]) => {
        setHealth(h);
        setTokenStatus(t);
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
      setTokenFeedback({ ok: true, msg: "API Token 已保存，写入成功。" });
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
      setTokenFeedback({ ok: true, msg: "API Token 已移除。" });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "移除失败";
      setTokenFeedback({ ok: false, msg });
    } finally {
      setTokenLoading(false);
    }
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

            {/* Token form — only visible when auth is disabled or token exists */}
            <div className="rounded-lg p-4" style={{ background: "var(--ocd-surface-2)" }}>
              <p className="mb-3 text-sm font-medium">
                {tokenStatus.enabled ? "修改 API Token" : "配置 API Token 以启用认证"}
              </p>
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
                {tokenStatus.enabled && (
                  <Button variant="danger" onClick={handleRemoveToken} disabled={tokenLoading}>
                    移除 Token
                  </Button>
                )}
              </div>
            </div>

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
