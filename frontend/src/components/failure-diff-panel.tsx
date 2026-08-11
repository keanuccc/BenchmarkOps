"use client";

import { useEffect, useState } from "react";
import {
  compareFailures,
  type CompareFailuresResponse,
} from "@/lib/api";
import { Badge, Card, EmptyState, SectionTitle, Spinner } from "@/components/ui";
import { GitCompareArrows } from "lucide-react";

function FailureList({
  title,
  badge,
  items,
  labelA,
  labelB,
}: {
  title: string;
  badge: string;
  items: CompareFailuresResponse["a_only_wrong"];
  labelA: string;
  labelB: string;
}) {
  if (items.length === 0) {
    return (
      <div className="text-sm text-neutral-500">
        {title}：无
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Badge>{badge}</Badge>
        <span>{title}：{items.length} 条</span>
      </div>
      {items.map((item) => (
        <div key={item.row_idx} className="border border-neutral-800 rounded-lg p-3 text-xs space-y-1">
          <div className="flex items-center justify-between">
            <span className="font-mono text-neutral-400">row #{item.row_idx}</span>
            <span>
              {labelA} {item.a_score.toFixed(2)} / {labelB} {item.b_score.toFixed(2)}
            </span>
          </div>
          <p className="text-neutral-300">
            输入：{JSON.stringify(item.input).slice(0, 180)}
          </p>
          <p className="text-red-400/90">A 输出：{String(item.a_output).slice(0, 220)}</p>
          <p className="text-emerald-400/90">B 输出：{String(item.b_output).slice(0, 220)}</p>
        </div>
      ))}
    </div>
  );
}

export function FailureDiffPanel({
  experimentA,
  experimentB,
}: {
  experimentA: { id: string; name: string };
  experimentB: { id: string; name: string };
}) {
  const [data, setData] = useState<CompareFailuresResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    compareFailures(experimentA.id, experimentB.id)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch(() => {
        if (!cancelled) setData(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [experimentA.id, experimentB.id]);

  return (
    <Card className="p-5 space-y-4">
      <SectionTitle>
        <span className="flex items-center gap-2">
          <GitCompareArrows size={14} /> 错误案例对比
        </span>
      </SectionTitle>
      {loading ? (
        <div className="flex justify-center py-6">
          <Spinner />
        </div>
      ) : !data ? (
        <EmptyState message="对比失败：两个实验必须有逐行结果且实验 id 不同。" />
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          <FailureList
            title={`仅 ${experimentA.name} 答错`}
            badge="A ✗"
            items={data.a_only_wrong}
            labelA="A"
            labelB="B"
          />
          <FailureList
            title={`仅 ${experimentB.name} 答错`}
            badge="B ✗"
            items={data.b_only_wrong}
            labelA="A"
            labelB="B"
          />
          <FailureList
            title="两者都答错"
            badge="A ✗ B ✗"
            items={data.both_wrong}
            labelA="A"
            labelB="B"
          />
        </div>
      )}
    </Card>
  );
}
