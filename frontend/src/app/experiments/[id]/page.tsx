"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  getExperiment,
  getExperimentResults,
  runExperiment,
  retryExperiment,
  duplicateExperiment,
  deleteExperiment,
  type Experiment,
  type ExperimentResult,
} from "@/lib/api";
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Spinner,
} from "@/components/ui";
import { Play, RefreshCw, Copy, Trash2, ArrowLeft } from "lucide-react";

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <Card className="p-4">
      <p className="text-xs uppercase tracking-wider text-[var(--ocd-text-muted)]">
        {label}
      </p>
      <p className="mt-1 text-xl font-semibold text-[var(--ocd-text)]">{value}</p>
    </Card>
  );
}

function scoreColor(score: number) {
  if (score >= 1) return "var(--ocd-ok)";
  if (score > 0) return "var(--ocd-warn)";
  return "var(--ocd-bad)";
}

export default function ExperimentDetailPage() {
  const { id } = useParams();
  const router = useRouter();
  const experimentId = id as string;
  const [exp, setExp] = useState<Experiment | null>(null);
  const [results, setResults] = useState<ExperimentResult[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    const e = await getExperiment(experimentId);
    setExp(e);
    try {
      const r = await getExperimentResults(experimentId);
      setResults(r);
    } catch {
      setResults([]);
    }
    setLoading(false);
  }

  useEffect(() => {
    refresh();
  }, [experimentId]);

  // Poll while the experiment is running/pending.
  useEffect(() => {
    const active = exp?.status === "running" || exp?.status === "pending";
    if (!active) return;
    const t = setInterval(refresh, 1000);
    return () => clearInterval(t);
  }, [exp?.status]);

  async function withBusy(fn: () => Promise<unknown>) {
    setBusy(true);
    try {
      await fn();
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  if (loading && !exp) return <EmptyState message="Loading…" icon={<Spinner size={20} />} />;
  if (!exp) return <EmptyState message="未找到实验。" />;

  const acc =
    exp.status === "completed"
      ? `${(Number(exp.metrics.accuracy) * 100).toFixed(1)}%`
      : "—";

  return (
    <div className="space-y-6">
      <header>
        <Link
          href={`/projects/${exp.project_id}`}
          className="inline-flex items-center gap-1 text-xs text-[var(--ocd-text-muted)] hover:underline"
        >
          <ArrowLeft size={12} /> 项目
        </Link>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight">{exp.name}</h1>
            <Badge status={exp.status}>{exp.status}</Badge>
          </div>
          <div className="flex flex-wrap gap-2">
            {exp.status !== "completed" && exp.status !== "running" && (
              <Button onClick={() => withBusy(() => runExperiment(exp.id))} disabled={busy}>
                <Play size={14} /> 运行
              </Button>
            )}
            <Button variant="secondary" onClick={() => withBusy(() => retryExperiment(exp.id))} disabled={busy}>
              <RefreshCw size={14} /> 重试
            </Button>
            <Button variant="secondary" onClick={() => withBusy(() => duplicateExperiment(exp.id))} disabled={busy}>
              <Copy size={14} /> 复制
            </Button>
            <Button
              variant="danger"
              disabled={busy}
              onClick={async () => {
                await deleteExperiment(exp.id);
                router.push("/experiments");
              }}
            >
              <Trash2 size={14} /> 删除
            </Button>
          </div>
        </div>
      </header>

      {exp.error && (
        <Card
          className="border p-4 text-sm"
          style={{ borderColor: "var(--ocd-bad)", color: "var(--ocd-bad)" }}
        >
          {exp.error}
        </Card>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Metric label="准确率" value={acc} />
        <Metric label="花费 (USD)" value={`$${exp.total_cost.toFixed(4)}`} />
        <Metric label="令牌数" value={String(exp.total_tokens)} />
        <Metric label="运行耗时" value={`${exp.runtime_ms}ms`} />
      </div>

      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-[var(--ocd-text-muted)]">
          逐行结果 ({results.length})
        </h2>
        {results.length === 0 ? (
          <EmptyState message="暂无结果。请先运行实验。" />
        ) : (
          <Card className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead
                className="border-b text-left text-[var(--ocd-text-faint)]"
                style={{ borderColor: "var(--ocd-border)", background: "var(--ocd-surface-2)" }}
              >
                <tr>
                  <th className="px-3 py-2">#</th>
                  <th className="px-3 py-2">输入</th>
                  <th className="px-3 py-2">期望</th>
                  <th className="px-3 py-2">输出</th>
                  <th className="px-3 py-2">得分</th>
                  <th className="px-3 py-2">延迟</th>
                  <th className="px-3 py-2">令牌数</th>
                  <th className="px-3 py-2">花费</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r) => (
                  <tr
                    key={r.id}
                    className="border-b last:border-0"
                    style={{ borderColor: "var(--ocd-border-soft)" }}
                  >
                    <td className="px-3 py-2 text-[var(--ocd-text-muted)]">{r.row_idx}</td>
                    <td className="px-3 py-2 font-mono text-[var(--ocd-text)]">
                      {JSON.stringify(r.input)}
                    </td>
                    <td className="px-3 py-2 font-mono text-[var(--ocd-text-muted)]">
                      {r.expected ? JSON.stringify(r.expected) : "—"}
                    </td>
                    <td className="px-3 py-2 font-mono text-[var(--ocd-text)]">
                      {r.output || "—"}
                    </td>
                    <td className="px-3 py-2">
                      <span style={{ color: scoreColor(r.score) }}>
                        {(r.score * 100).toFixed(0)}%
                      </span>
                    </td>
                    <td className="px-3 py-2 text-[var(--ocd-text-muted)]">
                      {r.latency_ms}ms
                    </td>
                    <td className="px-3 py-2 text-[var(--ocd-text-muted)]">
                      {r.tokens}
                    </td>
                    <td className="px-3 py-2 text-[var(--ocd-text-muted)]">
                      ${r.cost.toFixed(4)}
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
