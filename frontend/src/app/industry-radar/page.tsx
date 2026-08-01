"use client";

import { useEffect, useState } from "react";
import {
  listExperiments,
  listModels,
  getLeaderboard,
  type Experiment,
  type ModelInfo,
  type LeaderboardEntry,
} from "@/lib/api";
import {
  Card,
  KpiCard,
  Badge,
  EmptyState,
  ErrorState,
  Spinner,
  SectionTitle,
} from "@/components/ui";
import { LineChart, BarChart, DonutChart, RadarChart } from "@/components/charts";
import { Radar, Activity, Cpu, DollarSign } from "lucide-react";

const C = [
  "var(--ocd-c1)",
  "var(--ocd-c2)",
  "var(--ocd-c3)",
  "var(--ocd-c4)",
  "var(--ocd-c5)",
];

export default function IndustryRadarPage() {
  const [loading, setLoading] = useState(true);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      setLoadError(null);
      try {
        const [exs, ms, lb] = await Promise.all([
          listExperiments(),
          listModels(),
          getLeaderboard(),
        ]);
        setExperiments(exs);
        setModels(ms);
        setLeaderboard(lb);
      } catch (e: unknown) {
        setLoadError(
          e instanceof Error ? e.message : "加载数据失败,请检查后端是否在线。",
        );
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) {
    return <EmptyState message="Loading…" icon={<Spinner size={20} />} />;
  }
  if (loadError) {
    return <ErrorState message={loadError} icon={<Radar size={28} />} />;
  }
  if (experiments.length === 0) {
    return (
      <EmptyState
        message="暂无实验。运行评测以填充雷达图。"
        icon={<Radar size={28} />}
      />
    );
  }

  const providerByModel = new Map(models.map((m) => [m.name, m.provider]));
  const modelByLb = new Map(leaderboard.map((l) => [l.model_name, l]));

  // Group leaderboard by provider (derived from model name).
  const byProvider = new Map<string, number[]>();
  for (const l of leaderboard) {
    const p = providerByModel.get(l.model_name) ?? "unknown";
    if (!byProvider.has(p)) byProvider.set(p, []);
    byProvider.get(p)!.push(l.accuracy);
  }
  const radarItems = Array.from(byProvider.entries()).map(([prov, accs]) => ({
    label: prov,
    value: accs.reduce((a, b) => a + b, 0) / accs.length,
  }));

  // Per-model accuracy bar.
  const barLabels = leaderboard.map((l) => l.model_name);
  const barData = leaderboard.map((l) => l.accuracy);

  // Status donut.
  const statusCounts = new Map<string, number>();
  for (const e of experiments) {
    statusCounts.set(e.status, (statusCounts.get(e.status) ?? 0) + 1);
  }
  const statusSegments = Array.from(statusCounts.entries()).map(
    ([status, value], i) => ({
      label: status,
      value,
      color: C[i % C.length],
    }),
  );

  const completed = experiments.filter((e) => e.status === "completed");
  const avgAcc =
    leaderboard.length > 0
      ? leaderboard.reduce((a, b) => a + b.accuracy, 0) / leaderboard.length
      : 0;
  const totalCost = experiments.reduce((a, e) => a + e.total_cost, 0);
  const modelsCompared = new Set(leaderboard.map((l) => l.model_name)).size;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">行业雷达</h1>
        <p className="mt-1 text-sm text-[var(--ocd-text-muted)]">
          汇总所有实验与模型的整体洞察。
        </p>
      </header>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          label="实验总数"
          value={experiments.length}
          icon={<Activity size={16} />}
        />
        <KpiCard
          label="平均准确率"
          value={`${(avgAcc * 100).toFixed(1)}%`}
          icon={<Radar size={16} />}
        />
        <KpiCard
          label="对比模型数"
          value={modelsCompared}
          icon={<Cpu size={16} />}
        />
        <KpiCard
          label="总花费"
          value={`$${totalCost.toFixed(4)}`}
          icon={<DollarSign size={16} />}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-5">
          <SectionTitle>各供应商准确率</SectionTitle>
          {radarItems.length === 0 ? (
            <p className="text-sm text-[var(--ocd-text-faint)]">暂无数据。</p>
          ) : (
            <div className="grid place-items-center">
              <RadarChart items={radarItems} size={260} />
            </div>
          )}
        </Card>

        <Card className="p-5">
          <SectionTitle>实验状态</SectionTitle>
          <div className="grid place-items-center pt-3">
            <DonutChart segments={statusSegments} />
          </div>
        </Card>

        <Card className="p-5 lg:col-span-2">
          <SectionTitle>各模型准确率</SectionTitle>
          {barData.length === 0 ? (
            <p className="text-sm text-[var(--ocd-text-faint)]">暂无已完成运行。</p>
          ) : (
            <BarChart
              labels={barLabels}
              data={barData}
              height={240}
              format={(v) => `${(v * 100).toFixed(0)}%`}
            />
          )}
        </Card>

        <Card className="p-5 lg:col-span-2">
          <SectionTitle>排行榜</SectionTitle>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead
                className="border-b text-left text-xs uppercase tracking-wider text-[var(--ocd-text-faint)]"
                style={{ borderColor: "var(--ocd-border)" }}
              >
                <tr>
                  <th className="px-3 py-2">模型</th>
                  <th className="px-3 py-2">准确率</th>
                  <th className="px-3 py-2">coverage</th>
                  <th className="px-3 py-2">failure</th>
                  <th className="px-3 py-2">平均延迟</th>
                  <th className="px-3 py-2">花费</th>
                  <th className="px-3 py-2">状态</th>
                </tr>
              </thead>
              <tbody>
                {leaderboard.map((l) => (
                  <tr
                    key={l.experiment_id}
                    className="border-b last:border-0"
                    style={{ borderColor: "var(--ocd-border-soft)" }}
                  >
                    <td className="px-3 py-2 font-medium">{l.model_name}</td>
                    <td className="px-3 py-2 text-[var(--ocd-text-muted)]">
                      {(l.accuracy * 100).toFixed(1)}%
                    </td>
                    <td className="px-3 py-2 text-[var(--ocd-text-muted)]">
                      {((l.coverage ?? 0) * 100).toFixed(1)}%
                    </td>
                    <td className="px-3 py-2 text-[var(--ocd-text-muted)]">
                      {((l.failure_rate ?? 0) * 100).toFixed(1)}%
                    </td>
                    <td className="px-3 py-2 text-[var(--ocd-text-muted)]">
                      {l.avg_latency_ms.toFixed(0)}ms
                    </td>
                    <td className="px-3 py-2 text-[var(--ocd-text-muted)]">
                      ${l.total_cost.toFixed(4)}
                    </td>
                    <td className="px-3 py-2">
                      <Badge status={l.status}>{l.status}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </div>
  );
}
