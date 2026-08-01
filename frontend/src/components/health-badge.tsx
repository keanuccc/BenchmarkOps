"use client";

import { useEffect, useState } from "react";
import { getHealth, type HealthResponse } from "@/lib/api";

export function HealthBadge({ compact = false }: { compact?: boolean }) {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    getHealth()
      .then((h) => alive && setHealth(h))
      .catch(() => alive && setError(true));
    return () => {
      alive = false;
    };
  }, []);

  const ok = health?.status === "ok";
  const color = error ? "bg-red-500" : ok ? "bg-emerald-500" : "bg-amber-500";
  const label = error
    ? "后端离线"
    : ok
      ? "后端已连接"
      : "连接中…";

  if (compact) {
    return (
      <span
        className="rounded px-1.5 py-0.5 font-mono text-[10px]"
        style={{ background: "var(--ocd-surface-2)", color: "var(--ocd-text-muted)" }}
      >
        {error ? "offline" : health?.provider_mode ?? "mock"}
      </span>
    );
  }

  return (
    <div className="flex items-center gap-2 text-xs text-slate-500">
      <span className={`inline-block h-2 w-2 rounded-full ${color}`} />
      <span>{label}</span>
      {health && (
        <span className="ml-auto rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-500">
          {health.provider_mode}
        </span>
      )}
    </div>
  );
}
