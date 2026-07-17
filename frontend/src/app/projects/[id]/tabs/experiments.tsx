"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  listExperiments,
  createExperiment,
  runExperiment,
  retryExperiment,
  duplicateExperiment,
  deleteExperiment,
  listDatasets,
  listBenchmarks,
  listPrompts,
  listModels,
  type Experiment,
  type Dataset,
  type Benchmark,
  type Prompt,
  type ModelInfo,
} from "@/lib/api";
import { Button, Card, EmptyState, StatusBadge } from "@/components/ui";

export function ExperimentsTab({
  projectId,
  onChange,
}: {
  projectId: string;
  onChange: () => void;
}) {
  const [items, setItems] = useState<Experiment[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [benchmarks, setBenchmarks] = useState<Benchmark[]>([]);
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [form, setForm] = useState({
    name: "",
    dataset_id: "",
    benchmark_id: "",
    prompt_id: "",
    model_id: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [compareIds, setCompareIds] = useState<Set<string>>(new Set());

  const refresh = useCallback(async () => {
    setItems(await listExperiments(projectId));
  }, [projectId]);

  useEffect(() => {
    refresh();
    Promise.all([
      listDatasets(projectId),
      listBenchmarks(projectId),
      listPrompts(projectId),
      listModels(),
    ]).then(([d, b, p, m]) => {
      setDatasets(d);
      setBenchmarks(b);
      setPrompts(p);
      setModels(m);
    });
  }, [projectId, refresh]);

  // Poll while any experiment is running/pending.
  useEffect(() => {
    const active = items.some((e) => e.status === "running" || e.status === "pending");
    if (!active) return;
    const t = setInterval(refresh, 1000);
    return () => clearInterval(t);
  }, [items, refresh]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const { name, dataset_id, benchmark_id, prompt_id, model_id } = form;
    if (!name || !dataset_id || !benchmark_id || !prompt_id || !model_id) {
      setError("所有字段均为必填项");
      return;
    }
    try {
      await createExperiment({ project_id: projectId, ...form });
      setForm({ name: "", dataset_id: "", benchmark_id: "", prompt_id: "", model_id: "" });
      refresh();
      onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    }
  }

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLSelectElement | HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const toggleCompare = (id: string) =>
    setCompareIds((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  const selectCls = "mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm";

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <p className="mb-3 text-sm font-medium text-slate-700">
          新建实验 — 绑定 数据集 + 基准 + 提示词 + 模型
        </p>
        <form onSubmit={handleCreate} className="space-y-3">
          <input
            value={form.name}
            onChange={set("name")}
            placeholder="实验名称"
            className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
          <div className="grid gap-3 md:grid-cols-4">
            <div>
              <label className="text-xs text-slate-500">数据集</label>
              <select value={form.dataset_id} onChange={set("dataset_id")} className={selectCls}>
                <option value="">选择…</option>
                {datasets.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name} ({d.row_count})
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-slate-500">基准</label>
              <select value={form.benchmark_id} onChange={set("benchmark_id")} className={selectCls}>
                <option value="">选择…</option>
                {benchmarks.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name} ({b.metric})
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-slate-500">提示词</label>
              <select value={form.prompt_id} onChange={set("prompt_id")} className={selectCls}>
                <option value="">选择…</option>
                {prompts.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-slate-500">模型</label>
              <select value={form.model_id} onChange={set("model_id")} className={selectCls}>
                <option value="">选择…</option>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <Button type="submit">创建实验</Button>
          {error && <p className="text-xs text-red-600">{error}</p>}
        </form>
      </Card>

      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">{items.length} 个实验</p>
        <div className="flex items-center gap-2">
          {compareIds.size > 0 && (
            <Link href={`/experiments/compare?project_id=${projectId}&ids=${[...compareIds].join(",")}`}>
              <Button variant="secondary">
                对比选中 ({compareIds.size}) →
              </Button>
            </Link>
          )}
          {items.length >= 2 && (
            <Link href={`/experiments/compare?project_id=${projectId}`}>
              <Button variant="ghost">对比全部 →</Button>
            </Link>
          )}
        </div>
      </div>

      {items.length === 0 ? (
        <EmptyState message="暂无实验。先在上方创建,然后运行。" />
      ) : (
        <div className="space-y-2">
          {items.map((e) => (
            <Card key={e.id} className="p-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    className="accent-[var(--ocd-accent)]"
                    checked={compareIds.has(e.id)}
                    onChange={() => toggleCompare(e.id)}
                    aria-label={`选择 ${e.name} 进行对比`}
                  />
                  <div>
                  <Link
                    href={`/experiments/${e.id}`}
                    className="font-medium hover:underline"
                  >
                    {e.name}
                  </Link>
                  <div className="mt-1 flex items-center gap-3 text-xs text-slate-500">
                    <StatusBadge status={e.status} />
                    {e.status === "completed" && (
                      <>
                        <span>acc: {(Number(e.metrics.accuracy) * 100).toFixed(1)}%</span>
                        <span>cost: ${e.total_cost.toFixed(4)}</span>
                        <span>{e.total_tokens} tok</span>
                        <span>{e.runtime_ms}ms</span>
                      </>
                    )}
                    {e.status === "failed" && (
                      <span className="text-red-600">{e.error}</span>
                    )}
                  </div>
                </div>
                </div>
                <div className="flex gap-2">
                  {(e.status === "pending" || e.status === "failed") && (
                    <Button
                      onClick={async () => {
                        await runExperiment(e.id);
                        refresh();
                      }}
                    >
                      运行
                    </Button>
                  )}
                  {e.status === "completed" && (
                    <Button
                      variant="secondary"
                      onClick={async () => {
                        await retryExperiment(e.id);
                        refresh();
                      }}
                    >
                      重试
                    </Button>
                  )}
                  {e.status === "running" && (
                    <Button variant="secondary" disabled>
                      运行中…
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    onClick={async () => {
                      await duplicateExperiment(e.id);
                      refresh();
                      onChange();
                    }}
                  >
                    复制
                  </Button>
                  <Button
                    variant="danger"
                    onClick={async () => {
                      await deleteExperiment(e.id);
                      refresh();
                      onChange();
                    }}
                  >
                    删除
                  </Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
