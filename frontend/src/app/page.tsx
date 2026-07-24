"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Boxes,
  FlaskConical,
  Cpu,
  Target,
  Database,
  TrendingUp,
  Gauge,
  DollarSign,
  ArrowRight,
  Plus,
  Activity,
} from "lucide-react";
import {
  listProjects,
  listExperiments,
  getLeaderboard,
  listModels,
  type Project,
  type Experiment,
  type LeaderboardEntry,
  type ModelInfo,
} from "@/lib/api";
import { Card, KpiCard, Badge, ProgressBar, EmptyState, ErrorState, Spinner } from "@/components/ui";
import { LineChart, DonutChart } from "@/components/charts";

export default function DashboardPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      listProjects(),
      listExperiments(),
      getLeaderboard(),
      listModels(),
    ])
      .then(([p, e, l, m]) => {
        setProjects(p);
        setExperiments(e);
        setLeaderboard(l);
        setModels(m);
      })
      .catch((e: unknown) => {
        setLoadError(e instanceof Error ? e.message : "加载数据失败,请检查后端是否在线。");
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="grid place-items-center py-24 text-[var(--ocd-text-muted)]">
        <Spinner size={22} />
      </div>
    );
  }

  if (loadError) {
    return <ErrorState message={loadError} icon={<Gauge size={28} />} />;
  }

  const completed = experiments.filter((e) => e.status === "completed");
  const running = experiments.filter((e) => e.status === "running").length;
  const failed = experiments.filter((e) => e.status === "failed").length;
  const totalCost = experiments.reduce((s, e) => s + (e.total_cost ?? 0), 0);

  const accSeries = completed
    .slice()
    .reverse()
    .map((e) => Number((e.metrics as any)?.accuracy ?? 0) * 100);

  const statusSegments = [
    { label: "已完成", value: completed.length, color: "var(--ocd-ok)" },
    { label: "运行中", value: running, color: "var(--ocd-info)" },
    { label: "失败", value: failed, color: "var(--ocd-bad)" },
    {
      label: "待运行",
      value: experiments.length - completed.length - running - failed,
      color: "var(--ocd-warn)",
    },
  ];

  const topModels = [...leaderboard].sort((a, b) => b.accuracy - a.accuracy).slice(0, 5);

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">仪表盘</h1>
          <p className="mt-1 text-sm text-[var(--ocd-text-muted)]">
            评测运营实时总览
          </p>
        </div>
        <Link href="/projects">
          <div
            className="inline-flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-medium text-white"
            style={{ background: "var(--ocd-accent)" }}
          >
            <Plus size={15} /> 新建项目
          </div>
        </Link>
      </header>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard label="项目" value={projects.length} icon={<Boxes size={18} />} />
        <KpiCard
          label="实验"
          value={experiments.length}
          delta={`${completed.length} 已完成 · ${running} 运行中`}
          icon={<FlaskConical size={18} />}
        />
        {running > 0 && (
          <Link href="/experiments">
            <KpiCard
              label="运行中"
              value={running}
              icon={<Activity size={18} />}
              accent="var(--ocd-info)"
            />
          </Link>
        )}
        <KpiCard
          label="模型"
          value={models.length}
          icon={<Cpu size={18} />}
        />
        <KpiCard
          label="总花费"
          value={`$${totalCost.toFixed(3)}`}
          icon={<DollarSign size={18} />}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="p-5 lg:col-span-2">
          <div className="mb-3 flex items-center gap-2">
            <TrendingUp size={15} className="text-[var(--ocd-accent)]" />
            <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--ocd-text-muted)]">
              准确率趋势
            </h2>
          </div>
          {accSeries.length > 0 ? (
            <LineChart data={accSeries} color="var(--ocd-c2)" />
          ) : (
              <EmptyState message="暂无已完成的实验。" />
          )}
        </Card>

        <Card className="flex flex-col p-5">
          <div className="mb-3 flex items-center gap-2">
            <Gauge size={15} className="text-[var(--ocd-accent)]" />
            <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--ocd-text-muted)]">
              实验状态
            </h2>
          </div>
          <div className="flex flex-1 items-center">
            <DonutChart segments={statusSegments} size={170} />
          </div>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-5">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-[var(--ocd-text-muted)]">
            按准确率排名的模型
          </h2>
          {topModels.length === 0 ? (
            <EmptyState message="暂无可排名的实验。" />
          ) : (
            <ul className="space-y-3">
              {topModels.map((m, i) => (
                <li key={m.experiment_id} className="flex items-center gap-3">
                  <span className="w-4 text-sm font-semibold text-[var(--ocd-text-faint)]">
                    {i + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between text-sm">
                      <span className="font-medium">{m.model_name}</span>
                      <span className="font-semibold">
                        {(m.accuracy * 100).toFixed(1)}%
                      </span>
                    </div>
                    <div className="mt-1.5">
                      <ProgressBar value={m.accuracy} color="var(--ocd-c2)" />
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="p-5">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--ocd-text-muted)]">
              最近项目
            </h2>
            <Link
              href="/projects"
              className="flex items-center gap-1 text-xs text-[var(--ocd-accent)] hover:underline"
            >
              全部 <ArrowRight size={12} />
            </Link>
          </div>
          {projects.length === 0 ? (
            <EmptyState message="暂无项目。" />
          ) : (
            <ul className="space-y-2">
              {projects.slice(0, 5).map((p) => (
                <li key={p.id}>
                  <Link
                    href={`/projects/${p.id}`}
                    className="flex items-center justify-between rounded-lg border px-4 py-3 transition-colors hover:bg-[var(--ocd-surface-2)]"
                    style={{ borderColor: "var(--ocd-border-soft)" }}
                  >
                    <div>
                      <p className="text-sm font-medium">{p.name}</p>
                      <p className="text-xs text-[var(--ocd-text-faint)]">
                        {p.description}
                      </p>
                    </div>
                    <Badge status={p.status}>{p.status}</Badge>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
