"use client";

import Link from "next/link";
import {
  Activity,
  ArrowRight,
  Boxes,
  CheckCircle2,
  Cpu,
  DollarSign,
  FlaskConical,
  Gauge,
  Plus,
  Target,
  TrendingUp,
} from "lucide-react";
import { useQueries } from "@tanstack/react-query";
import {
  getLeaderboard,
  listExperiments,
  listModels,
  listProjects,
  type PageResult,
  type Experiment,
  type LeaderboardEntry,
  type ModelInfo,
  type Project,
} from "@/lib/api";
import { LineChart, DonutChart } from "@/components/charts";
import { Badge, Button, Card, EmptyState, ErrorState, KpiCard, ProgressBar, SectionTitle, Spinner } from "@/components/ui";

export default function DashboardPage() {
  const queries = useQueries({
    queries: [
      {
        queryKey: ["projects"],
        queryFn: () => listProjects({ limit: 100000 }),
        select: (d: PageResult<Project>) => d.items,
      },
      {
        queryKey: ["experiments"],
        queryFn: () => listExperiments(undefined, { limit: 100000 }),
        select: (d: PageResult<Experiment>) => d.items,
      },
      { queryKey: ["leaderboard"], queryFn: () => getLeaderboard() },
      {
        queryKey: ["models"],
        queryFn: () => listModels({ limit: 100000 }),
        select: (d: PageResult<ModelInfo>) => d.items,
      },
    ],
  });

  const [projectsQ, experimentsQ, leaderboardQ, modelsQ] = queries;
  const projects = (projectsQ.data ?? []) as Project[];
  const experiments = (experimentsQ.data ?? []) as Experiment[];
  const leaderboard = (leaderboardQ.data ?? []) as LeaderboardEntry[];
  const models = (modelsQ.data ?? []) as ModelInfo[];
  const loading = queries.some((query) => query.isLoading);
  const error = queries.find((query) => query.isError)?.error as Error | undefined;

  if (loading) {
    return <div className="grid min-h-[420px] place-items-center text-[var(--ocd-text-muted)]"><Spinner size={24} /></div>;
  }

  if (error) {
    return <ErrorState message={error.message} icon={<Gauge size={28} />} />;
  }

  const completed = experiments.filter((experiment) => experiment.status === "completed");
  const running = experiments.filter((experiment) => experiment.status === "running").length;
  const failed = experiments.filter((experiment) => experiment.status === "failed").length;
  const queued = experiments.length - completed.length - running - failed;
  const totalCost = experiments.reduce((sum, experiment) => sum + (experiment.total_cost ?? 0), 0);
  const accSeries = completed.slice().reverse().map((experiment) => Number((experiment.metrics as { accuracy?: number } | null)?.accuracy ?? 0) * 100);
  const topModels = [...leaderboard].sort((a, b) => b.accuracy - a.accuracy).slice(0, 5);
  const statusSegments = [
    { label: "已完成", value: completed.length, color: "var(--ocd-ok)" },
    { label: "运行中", value: running, color: "var(--ocd-info)" },
    { label: "失败", value: failed, color: "var(--ocd-bad)" },
    { label: "待运行", value: queued, color: "var(--ocd-warn)" },
  ];

  return (
    <div className="space-y-7">
      <section className="reveal grid gap-6 overflow-hidden rounded-[20px] border border-[var(--ocd-border)] bg-[var(--ocd-surface)] p-6 shadow-[var(--ocd-shadow)] lg:grid-cols-[1fr_280px] lg:p-8">
        <div className="relative">
          <div className="mb-5 flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.2em] text-[var(--ocd-accent)]">
            <span className="h-1.5 w-1.5 rounded-full bg-[var(--ocd-accent)] shadow-[0_0_12px_var(--ocd-accent)]" /> 工作区 / 总览
          </div>
          <h1 className="max-w-2xl text-4xl font-semibold leading-[1.05] tracking-[-0.065em] text-[var(--ocd-text)] sm:text-5xl">把每一次模型迭代，<span className="text-[var(--ocd-accent)] drop-shadow-[0_0_18px_var(--ocd-accent-soft)]">变成可解释的进步。</span></h1>
          <p className="mt-5 max-w-xl text-sm leading-6 text-[var(--ocd-text-muted)]">从数据集、基准套件到实验报告，在一个清晰的工作区里掌握评测质量、运行状态与成本变化。</p>
          <div className="mt-4 flex flex-wrap items-center gap-2 font-mono text-[11px] text-[var(--ocd-text-faint)]">
            <span className="rounded-md border border-[var(--ocd-border-soft)] bg-[var(--ocd-surface-2)] px-2 py-1">国产模型优先</span>
            <span className="rounded-md border border-[var(--ocd-border-soft)] bg-[var(--ocd-surface-2)] px-2 py-1">DeepSeek 直连</span>
            <span className="rounded-md border border-[var(--ocd-border-soft)] bg-[var(--ocd-surface-2)] px-2 py-1">可复现</span>
            <span className="rounded-md border border-[var(--ocd-border-soft)] bg-[var(--ocd-surface-2)] px-2 py-1">可审计</span>
          </div>
          <div className="mt-7 flex flex-wrap items-center gap-3">
            <Link href="/evaluation"><Button><Plus size={16} /> 开始新评测</Button></Link>
            <Link href="/projects" className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-[var(--ocd-border)] px-4 py-2 text-sm font-semibold text-[var(--ocd-text-muted)] hover:border-[var(--ocd-accent)] hover:text-[var(--ocd-accent)]">查看项目 <ArrowRight size={15} /></Link>
          </div>
        </div>
        <div className="relative flex min-h-[230px] flex-col justify-between overflow-hidden rounded-2xl border border-[var(--ocd-border-soft)] bg-[var(--ocd-bg)] p-5">
          <div className="pointer-events-none absolute -right-12 -top-16 h-40 w-40 rounded-full bg-[var(--ocd-accent-soft)] blur-3xl" />
          <div className="flex items-start justify-between">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-[var(--ocd-text-faint)]">运行信号</p>
              <p className="mt-2 text-3xl font-semibold tabular-nums tracking-[-0.06em] text-[var(--ocd-text)]">{experiments.length ? `${((completed.length / experiments.length) * 100).toFixed(0)}%` : "—"}</p>
              <p className="mt-1 text-xs text-[var(--ocd-text-muted)]">实验完成率</p>
            </div>
            <span className="relative grid h-10 w-10 place-items-center rounded-xl bg-[var(--ocd-accent-soft)] text-[var(--ocd-accent)]">
              <Activity size={18} />
              <span className="absolute -right-0.5 -top-0.5 h-2 w-2 animate-pulse rounded-full bg-[var(--ocd-accent)] shadow-[0_0_8px_var(--ocd-accent)]" />
            </span>
          </div>
          <div className="space-y-3">
            <div className="flex items-center justify-between text-xs"><span className="text-[var(--ocd-text-faint)]">工作区健康度</span><span className="font-semibold text-[var(--ocd-ok)]">稳定</span></div>
            <div className="h-1.5 overflow-hidden rounded-full bg-[var(--ocd-surface-3)]"><div className="h-full w-[82%] rounded-full bg-[var(--ocd-ok)]" /></div>
            <div className="flex items-center gap-2 text-[11px] text-[var(--ocd-text-faint)]"><CheckCircle2 size={13} className="text-[var(--ocd-ok)]" /> 数据与服务连接正常</div>
          </div>
        </div>
      </section>

      <section className="reveal reveal-delay-1 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <KpiCard label="项目" value={projects.length} icon={<Boxes size={17} />} />
        <KpiCard label="实验总数" value={experiments.length} delta={`${completed.length} 已完成`} icon={<FlaskConical size={17} />} accent="var(--ocd-coral)" />
        <KpiCard label="运行中" value={running} delta={running ? "需要关注" : "当前空闲"} icon={<Activity size={17} />} accent="var(--ocd-info)" />
        <KpiCard label="模型" value={models.length} icon={<Cpu size={17} />} accent="var(--ocd-ok)" />
        <KpiCard label="累计成本" value={`$${totalCost.toFixed(3)}`} icon={<DollarSign size={17} />} accent="var(--ocd-warn)" />
      </section>

      <section className="reveal reveal-delay-2 grid gap-4 lg:grid-cols-[minmax(0,1.55fr)_minmax(300px,0.8fr)]">
        <Card className="p-5 sm:p-6">
          <SectionTitle action={<span className="font-mono text-[10px] text-[var(--ocd-text-faint)]">LATEST RUNS / ACCURACY</span>}>准确率趋势</SectionTitle>
          {accSeries.length > 0 ? <LineChart data={accSeries} color="var(--ocd-accent)" /> : <EmptyState message="暂无已完成的实验。" icon={<TrendingUp size={18} />} />}
        </Card>
        <Card className="p-5 sm:p-6">
          <SectionTitle action={<Target size={15} className="text-[var(--ocd-accent)]" />}>实验状态</SectionTitle>
          <div className="flex min-h-[220px] items-center justify-center"><DonutChart segments={statusSegments} size={188} /></div>
        </Card>
      </section>

      <section className="reveal reveal-delay-3 grid gap-4 lg:grid-cols-2">
        <Card className="p-5 sm:p-6">
          <SectionTitle action={<Link href="/experiments" className="inline-flex items-center gap-1 text-xs font-semibold text-[var(--ocd-accent)] hover:text-[var(--ocd-text)]">查看全部 <ArrowRight size={13} /></Link>}>模型表现排行</SectionTitle>
          {topModels.length === 0 ? <EmptyState message="暂无可排名的实验。" icon={<Cpu size={18} />} /> : (
            <ul className="space-y-1">
              {topModels.map((model, index) => (
                <li key={model.experiment_id} className="group flex items-center gap-3 rounded-xl px-2 py-3 hover:bg-[var(--ocd-surface-2)]">
                  <span className={`grid h-7 w-7 place-items-center rounded-lg font-mono text-xs ${index === 0 ? "bg-[var(--ocd-accent)] text-[var(--ocd-accent-fg)]" : "bg-[var(--ocd-surface-2)] text-[var(--ocd-text-faint)]"}`}>{String(index + 1).padStart(2, "0")}</span>
                  <div className="min-w-0 flex-1"><div className="flex items-center justify-between gap-3 text-sm"><span className="truncate font-semibold">{model.model_name}</span><span className="font-mono text-xs font-semibold text-[var(--ocd-accent)]">{(model.accuracy * 100).toFixed(1)}%</span></div><div className="mt-2"><ProgressBar value={model.accuracy} color={index === 0 ? "var(--ocd-accent)" : "var(--ocd-ok)"} /></div><div className="mt-1.5 text-[10px] text-[var(--ocd-text-faint)]">coverage {((model.coverage ?? 0) * 100).toFixed(1)}% · failure {((model.failure_rate ?? 0) * 100).toFixed(1)}%</div></div>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card className="p-5 sm:p-6">
          <SectionTitle action={<Link href="/projects" className="inline-flex items-center gap-1 text-xs font-semibold text-[var(--ocd-accent)] hover:text-[var(--ocd-text)]">管理项目 <ArrowRight size={13} /></Link>}>最近项目</SectionTitle>
          {projects.length === 0 ? <EmptyState message="暂无项目。" icon={<Boxes size={18} />} /> : (
            <ul className="divide-y divide-[var(--ocd-border-soft)]">
              {projects.slice(0, 5).map((project) => (
                <li key={project.id}><Link href={`/projects/${project.id}`} className="flex items-center gap-3 py-3.5 hover:translate-x-1"><span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-[var(--ocd-surface-2)] text-[var(--ocd-accent)]"><Boxes size={16} /></span><span className="min-w-0 flex-1"><span className="block truncate text-sm font-semibold">{project.name}</span><span className="mt-1 block truncate text-xs text-[var(--ocd-text-faint)]">{project.description || "尚未添加描述"}</span></span><Badge status={project.status}>{project.status}</Badge><ArrowRight size={14} className="text-[var(--ocd-text-faint)]" /></Link></li>
              ))}
            </ul>
          )}
        </Card>
      </section>
    </div>
  );
}
