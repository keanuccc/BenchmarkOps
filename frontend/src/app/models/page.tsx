"use client";

import { useEffect, useState } from "react";
import { listModels, seedModels, type ModelInfo } from "@/lib/api";
import { Button, Card, Badge, EmptyState, Spinner } from "@/components/ui";
import { Cpu } from "lucide-react";

export default function ModelsPage() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [seeding, setSeeding] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      setModels(await listModels());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function onSeed() {
    setSeeding(true);
    try {
      await seedModels();
      await refresh();
    } finally {
      setSeeding(false);
    }
  }

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">模型中心</h1>
          <p className="mt-1 text-sm text-[var(--ocd-text-muted)]">
            LLM 统一注册表。定价为每 1K 令牌(USD)。
          </p>
        </div>
        <Button onClick={onSeed} disabled={seeding}>
          {seeding ? <Spinner size={14} /> : <Cpu size={15} />} 初始化模型
        </Button>
      </header>

      {loading ? (
        <EmptyState message="Loading…" icon={<Spinner size={20} />} />
      ) : models.length === 0 ? (
        <EmptyState
          message='暂无模型。点击"初始化模型"加载常用模型。'
          icon={<Cpu size={28} />}
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {models.map((m) => (
            <Card key={m.id} className="space-y-3 p-4">
              <div className="flex items-start justify-between">
                <div>
                  <p className="font-semibold">{m.name}</p>
                  <Badge>{m.provider}</Badge>
                </div>
                {m.is_active ? (
                  <Badge status="active">启用中</Badge>
                ) : (
                  <Badge status="archived">已停用</Badge>
                )}
              </div>

              <p className="font-mono text-xs text-[var(--ocd-text-muted)]">{m.model_id}</p>

              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <p className="text-xs uppercase tracking-wider text-[var(--ocd-text-faint)]">
                    上下文
                  </p>
                  <p className="text-[var(--ocd-text-muted)]">
                    {m.context_length?.toLocaleString() ?? "—"}
                  </p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wider text-[var(--ocd-text-faint)]">
                    输入 / 输出
                  </p>
                  <p className="text-[var(--ocd-text-muted)]">
                    ${m.pricing?.input_per_1k ?? "?"} / ${m.pricing?.output_per_1k ?? "?"}
                  </p>
                </div>
              </div>

              <div className="flex flex-wrap gap-1">
                {(m.capabilities ?? []).map((c) => (
                  <span
                    key={c}
                    className="rounded px-1.5 py-0.5 text-xs"
                    style={{
                      background: "var(--ocd-surface-2)",
                      color: "var(--ocd-text-muted)",
                    }}
                  >
                    {c}
                  </span>
                ))}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
