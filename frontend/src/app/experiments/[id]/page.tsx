"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  getExperiment,
  getExperimentResults,
  runExperiment,
  cancelExperiment,
  retryExperiment,
  duplicateExperiment,
  deleteExperiment,
  ApiRequestError,
  type Experiment,
  type ExperimentResult,
} from "@/lib/api";
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Spinner,
  ProgressBar,
} from "@/components/ui";
import { Play, RefreshCw, Copy, Trash2, ArrowLeft, Square } from "lucide-react";

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
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 50;

  async function refresh() {
    const e = await getExperiment(experimentId);
    setExp(e);
    // Paginate results: load first page only
    try {
      const r = await getExperimentResultsPaginated(experimentId, { offset: 0, limit: PAGE_SIZE });
      setResults(r);
    } catch {
      setResults([]);
    }
    setLoading(false);
  }

  async function loadPage(p: number) {
    setPage(p);
    try {
      const r = await getExperimentResultsPaginated(experimentId, {
        offset: (p - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
      });
      setResults(r);
    } catch {
      setResults([]);
    }
  }

  useEffect(() => {
    refresh();
  }, [experimentId]);

  // Poll while the experiment is running/pending/cancelled (waiting for final state).
  useEffect(() => {
    const active = exp?.status === "running" || exp?.status === "pending" || exp?.status === "queued";
    if (!active) return;
    const t = setInterval(refresh, 1000);
    return () => clearInterval(t);
  }, [exp?.status]);

  async function withBusy(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await refresh();
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "操作失败");
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
            {exp.status === "running" && (
              <Button variant="danger" onClick={() => withBusy(() => cancelExperiment(exp.id))} disabled={busy}>
                <Square size={14} /> 取消
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
                if (!confirm("确定删除该实验？")) return;
                setBusy(true);
                setError(null);
                try {
                  await deleteExperiment(exp.id);
                  router.push("/experiments");
                } catch (err) {
                  setError(err instanceof ApiRequestError ? err.message : "删除失败");
                  setBusy(false);
                }
              }}
            >
              <Trash2 size={14} /> 删除
            </Button>
          </div>
        </div>
      </header>

      {(exp.status === "running" || exp.status === "pending") && (
        <Card className="p-4">
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs uppercase tracking-wider text-[var(--ocd-text-muted)]">
              真实进度
            </p>
            {exp.rows_total ? (
              <p className="text-sm font-semibold text-[var(--ocd-text)]">
                {Math.round((exp.progress / exp.rows_total) * 100)}%
              </p>
            ) : (
              <p className="text-xs text-[var(--ocd-text-muted)]">准备中…</p>
            )}
          </div>
          <div className="mt-3">
            <ProgressBar
              value={exp.rows_total ? exp.progress / exp.rows_total : 0}
            />
          </div>
          <p className="mt-3 text-xs text-[var(--ocd-text-muted)]">
            已评分{" "}
            <span className="font-semibold text-[var(--ocd-ok)]">
              {exp.cells_done}
            </span>{" "}
            · 失败{" "}
            <span className="font-semibold text-[var(--ocd-bad)]">
              {exp.cells_error}
            </span>{" "}
            · 共{" "}
            <span className="font-semibold text-[var(--ocd-text)]">
              {exp.rows_total ?? "—"}
            </span>
          </p>
        </Card>
      )}

  if (exp.error || exp.status === "cancelled") {
        <Card
          className="border p-4 text-sm"
          style={{ borderColor: "var(--ocd-warn)", color: "var(--ocd-warn)" }}
        >
          {exp.status === "cancelled" ? "实验已被用户取消。" : exp.error}
        </Card>
      )}

      {error && (
        <Card
          className="border p-4 text-sm"
          style={{ borderColor: "var(--ocd-bad)", color: "var(--ocd-bad)" }}
        >
          {error}
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
          逐行结果 (第 {((page - 1) * PAGE_SIZE + 1)}–{page * PAGE_SIZE} 条)
        </h2>
        {results.length === 0 ? (
          <EmptyState message="暂无结果。请先运行实验。" />
        ) : (
          <Card className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead
                className="border-b text-left text-[var(--ocd-text-faint)] sticky top-0 z-10"
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
            {/* Pagination */}
            <div className="flex items-center justify-between border-t px-4 py-3 text-xs" style={{ borderColor: "var(--ocd-border-soft)" }}>
              <span className="text-[var(--ocd-text-muted)]">每页 {PAGE_SIZE} 条</span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => loadPage(page - 1)}
                  disabled={page <= 1}
                  className="rounded px-2 py-1 text-[var(--ocd-text-muted)] hover:bg-[var(--ocd-surface-2)] disabled:opacity-30"
                >
                  ← 上一页
                </button>
                <span className="font-medium text-[var(--ocd-text)]">
                  第 {page} 页
                </span>
                <button
                  onClick={() => loadPage(page + 1)}
                  className="rounded px-2 py-1 text-[var(--ocd-text-muted)] hover:bg-[var(--ocd-surface-2)]"
                >
                  下一页 →
                </button>
              </div>
            </div>
          </Card>
        )}
      </section>
    </div>
  );
}
