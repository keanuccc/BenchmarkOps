"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  listExperiments,
  compareExperiments,
  getLeaderboard,
  type ComparisonResponse,
} from "@/lib/api";
import { Button, Card, EmptyState } from "@/components/ui";
import { BarChart } from "@/components/charts";
import { FailureDiffPanel } from "@/components/failure-diff-panel";
import { ModelRoutingCard } from "@/components/model-routing-card";
import { SignificancePanel } from "@/components/significance-panel";
import { useQuery } from "@tanstack/react-query";

const SERIES_COLORS = [
  "var(--ocd-c1)",
  "var(--ocd-c2)",
  "var(--ocd-c3)",
  "var(--ocd-c4)",
];

function CompareInner() {
  const searchParams = useSearchParams();
  const projectId = searchParams.get("project_id") ?? undefined;
  const initialIds = searchParams.get("ids")?.split(",").filter(Boolean) ?? null;

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [comparison, setComparison] = useState<ComparisonResponse | null>(null);

  // Fetch experiments and leaderboard via React Query
  const { data: experiments = [] } = useQuery({
    queryKey: ["experiments", projectId ? { projectId } : null],
    queryFn: () => listExperiments(projectId),
    select: (d) => d.items,
  });

  const { data: leaderboard = [] } = useQuery({
    queryKey: ["leaderboard", projectId ? { projectId } : null],
    queryFn: () => getLeaderboard(projectId, { withConfidence: true }),
  });

  // Filter to completed experiments
  const completed = experiments.filter((e) => e.status === "completed");

  // Initialize selection on first load
  useEffect(() => {
    if (completed.length > 0 && selected.size === 0) {
      const sel =
        initialIds && initialIds.every((id) => completed.some((e) => e.id === id))
          ? initialIds
          : completed.map((e) => e.id);
      setSelected(new Set(sel));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [completed]);

  const runCompare = useCallback(async () => {
    if (selected.size < 2) {
      setComparison(null);
      return;
    }
    try {
      setComparison(await compareExperiments([...selected]));
    } catch {
      setComparison(null);
    }
  }, [selected]);

  useEffect(() => {
    runCompare();
  }, [runCompare]);

  function toggle(id: string) {
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  }

  const d = comparison?.dimensions;

  const dims: {
    title: string;
    data: number[];
    fmt: (v: number) => string;
  }[] = d
    ? [
        {
          title: "准确率 (%)",
          data: d.accuracy.map((x) => +(x * 100).toFixed(2)),
          fmt: (v) => `${v}%`,
        },
        {
          title: "平均延迟 (ms)",
          data: d.avg_latency_ms,
          fmt: (v) => `${v.toFixed(0)}ms`,
        },
        {
          title: "总花费 (USD)",
          data: d.total_cost,
          fmt: (v) => `$${v.toFixed(2)}`,
        },
        {
          title: "总令牌数",
          data: d.total_tokens,
          fmt: (v) => v.toLocaleString(),
        },
        {
          title: "coverage (%)",
          data: (d.coverage ?? d.accuracy.map(() => 0)).map((x) => +(x * 100).toFixed(2)),
          fmt: (v) => `${v}%`,
        },
        {
          title: "failure (%)",
          data: (d.failure_rate ?? d.accuracy.map(() => 0)).map((x) => +(x * 100).toFixed(2)),
          fmt: (v) => `${v}%`,
        },
      ]
    : [];

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">对比实验</h1>
        <p className="mt-1 text-sm text-[var(--ocd-text-muted)]">
          选择已完成的实验,对比准确率、花费与延迟。
        </p>
      </header>

      {completed.length === 0 ? (
        <EmptyState message="暂无可对比的已完成实验。" />
      ) : (
        <Card className="p-4">
          <div className="flex flex-wrap gap-3">
            {completed.map((e) => (
              <label
                key={e.id}
                className="flex items-center gap-2 text-sm text-[var(--ocd-text)]"
              >
                <input
                  type="checkbox"
                  className="accent-[var(--ocd-accent)]"
                  checked={selected.has(e.id)}
                  onChange={() => toggle(e.id)}
                />
                {e.name}
              </label>
            ))}
          </div>
          <div className="mt-3">
            <Button onClick={runCompare}>更新图表</Button>
          </div>
        </Card>
      )}

      {d && (
        <div className="grid gap-4 md:grid-cols-2">
          {dims.map((dim, i) => (
            <Card key={dim.title} className="p-4">
              <h3 className="mb-2 text-sm font-semibold text-[var(--ocd-text)]">
                {dim.title}
              </h3>
              <BarChart
                labels={d.labels}
                data={dim.data}
                color={SERIES_COLORS[i % SERIES_COLORS.length]}
                format={dim.fmt}
              />
            </Card>
          ))}
        </div>
      )}

      {selected.size === 2 &&
        (() => {
          const pair = [...selected];
          const a = experiments.find((e) => e.id === pair[0]);
          const b = experiments.find((e) => e.id === pair[1]);
          return a && b ? (
            <>
              <SignificancePanel
                experimentA={a.id}
                experimentB={b.id}
                nameA={a.name}
                nameB={b.name}
              />
              <FailureDiffPanel
                experimentA={{ id: a.id, name: a.name }}
                experimentB={{ id: b.id, name: b.name }}
              />
            </>
          ) : null;
        })()}

      {projectId && <ModelRoutingCard projectId={projectId} />}

      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-[var(--ocd-text-muted)]">
          排行榜
        </h2>
        {leaderboard.length === 0 ? (
          <EmptyState message="暂无排行榜数据。" />
        ) : (
          <Card className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead
                className="border-b text-left text-xs uppercase tracking-wider text-[var(--ocd-text-faint)]"
                style={{ borderColor: "var(--ocd-border)", background: "var(--ocd-surface-2)" }}
              >
                <tr>
                  <th className="px-4 py-3">#</th>
                  <th className="px-4 py-3">实验</th>
                  <th className="px-4 py-3">模型</th>
                  <th className="px-4 py-3">数据集 / 基准</th>
                  <th className="px-4 py-3">准确率</th>
                  <th className="px-4 py-3">95% CI</th>
                  <th className="px-4 py-3">花费</th>
                  <th className="px-4 py-3">延迟</th>
                  <th className="px-4 py-3">令牌数</th>
                </tr>
              </thead>
              <tbody>
                {leaderboard.map((row, i) => (
                  <tr
                    key={row.experiment_id}
                    className={
                      i === 0
                        ? "border-b bg-[var(--ocd-accent-soft)]"
                        : "border-b last:border-0"
                    }
                    style={{ borderColor: "var(--ocd-border-soft)" }}
                  >
                    <td className="px-4 py-3">
                      <span
                        className={
                          i === 0
                            ? "grid h-6 w-6 place-items-center rounded-md bg-[var(--ocd-accent)] font-mono text-xs font-bold text-[var(--ocd-accent-fg)]"
                            : "font-mono text-xs text-[var(--ocd-text-faint)]"
                        }
                      >
                        {i + 1}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-[var(--ocd-text)]">
                      {row.experiment_name}
                    </td>
                    <td className="px-4 py-3 text-[var(--ocd-text-muted)]">
                      {row.model_name}
                    </td>
                    <td className="px-4 py-3 text-[var(--ocd-text-muted)]">
                      {row.dataset_name}
                      {row.dataset_version != null ? ` v${row.dataset_version}` : ""} · {row.benchmark_name}
                    </td>
                    <td
                      className={`px-4 py-3 font-semibold tabular-nums ${
                        i === 0 ? "text-[var(--ocd-accent)]" : "text-[var(--ocd-ok)]"
                      }`}
                    >
                      {(row.accuracy * 100).toFixed(1)}%
                    </td>
                    <td className="px-4 py-3 text-[var(--ocd-text-muted)]">
                      {row.ci_lower != null && row.ci_upper != null
                        ? `${(row.ci_lower * 100).toFixed(1)}–${(row.ci_upper * 100).toFixed(1)}%`
                        : "—"}
                    </td>
                    <td className="px-4 py-3 text-[var(--ocd-text-muted)]">
                      ${row.total_cost.toFixed(4)}
                    </td>
                    <td className="px-4 py-3 text-[var(--ocd-text-muted)]">
                      {row.avg_latency_ms.toFixed(0)}ms
                    </td>
                    <td className="px-4 py-3 text-[var(--ocd-text-muted)]">
                      {row.total_tokens.toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </section>
    </div>
  );
}

export default function ComparePage() {
  return (
    <Suspense fallback={<EmptyState message="Loading…" />}>
      <CompareInner />
    </Suspense>
  );
}
