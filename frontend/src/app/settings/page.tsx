"use client";

import { useEffect, useState } from "react";
import { getHealth, type HealthResponse } from "@/lib/api";
import { Card, Badge, EmptyState, Spinner, SectionTitle } from "@/components/ui";
import { Settings, Server, KeyRound } from "lucide-react";

export default function SettingsPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const h = await getHealth();
        setHealth(h);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load health.");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) {
    return <EmptyState message="Loading…" icon={<Spinner size={20} />} />;
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">设置</h1>
        <p className="mt-1 text-sm text-[var(--ocd-text-muted)]">
          后端连接与环境配置。
        </p>
      </header>

      {error && (
        <Card className="p-5">
          <p className="text-sm" style={{ color: "var(--ocd-bad)" }}>
            {error}
          </p>
        </Card>
      )}

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
          即可启用真实模型供应商。
        </p>
      </Card>

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
