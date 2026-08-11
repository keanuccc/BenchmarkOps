"use client";

import { useEffect, useState } from "react";
import { getModelRouting, type ModelRoutingEntry } from "@/lib/api";
import { Badge, Card, EmptyState, SectionTitle, Spinner } from "@/components/ui";
import { Route } from "lucide-react";

export function ModelRoutingCard({ projectId }: { projectId?: string }) {
  const [items, setItems] = useState<ModelRoutingEntry[] | null>(null);

  useEffect(() => {
    if (!projectId) {
      setItems([]);
      return;
    }
    let cancelled = false;
    getModelRouting(projectId)
      .then((d) => {
        if (!cancelled) setItems(d);
      })
      .catch(() => {
        if (!cancelled) setItems([]);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  return (
    <Card className="p-5 space-y-3">
      <SectionTitle>
        <span className="flex items-center gap-2">
          <Route size={14} /> 模型路由建议
        </span>
      </SectionTitle>
      {items === null ? (
        <div className="flex justify-center py-4">
          <Spinner />
        </div>
      ) : items.length === 0 ? (
        <EmptyState message="暂无已完成实验可分析。选一个项目并运行评测后，这里会给出性价比推荐。" />
      ) : (
        <div className="space-y-2">
          {items.map((row) => (
            <div
              key={row.model_id}
              className="flex items-center justify-between border border-neutral-800 rounded-lg px-3 py-2 text-sm"
            >
              <div className="flex items-center gap-2">
                <span className="font-medium">{row.model_name}</span>
                {row.recommended && <Badge>推荐</Badge>}
              </div>
              <div className="flex items-center gap-3 text-xs text-neutral-400">
                <span>准确率 {(row.accuracy * 100).toFixed(1)}%</span>
                <span>${row.total_cost.toFixed(4)}</span>
                <span>{row.avg_latency_ms.toFixed(0)}ms</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
