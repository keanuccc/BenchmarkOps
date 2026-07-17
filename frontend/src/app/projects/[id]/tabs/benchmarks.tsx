"use client";

import { useEffect, useState } from "react";
import {
  listBenchmarks,
  createBenchmark,
  deleteBenchmark,
  getMetrics,
  type Benchmark,
} from "@/lib/api";
import { Button, Card, EmptyState } from "@/components/ui";

const TYPES = ["qa", "coding", "agent", "classification", "generation"];

export function BenchmarksTab({
  projectId,
  onChange,
}: {
  projectId: string;
  onChange: () => void;
}) {
  const [items, setItems] = useState<Benchmark[]>([]);
  const [metrics, setMetrics] = useState<string[]>([]);
  const [defaults, setDefaults] = useState<Record<string, string>>({});
  const [name, setName] = useState("");
  const [type, setType] = useState("qa");
  const [metric, setMetric] = useState("");

  async function refresh() {
    setItems(await listBenchmarks(projectId));
  }
  useEffect(() => {
    refresh();
    getMetrics().then((m) => {
      setMetrics(m.metrics);
      setDefaults(m.defaults);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    await createBenchmark({
      project_id: projectId,
      name,
      type,
      metric: metric || undefined,
    });
    setName("");
    setMetric("");
    refresh();
    onChange();
  }

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <form onSubmit={handleCreate} className="flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[160px]">
            <label className="block text-xs font-medium text-slate-500">名称</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">类型</label>
            <select
              value={type}
              onChange={(e) => setType(e.target.value)}
              className="mt-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            >
              {TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">
              Metric{" "}
              <span className="text-slate-400">
                (默认: {defaults[type] ?? "—"})
              </span>
            </label>
            <select
              value={metric}
              onChange={(e) => setMetric(e.target.value)}
              className="mt-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            >
              <option value="">自动 ({defaults[type] ?? "—"})</option>
              {metrics.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
          <Button type="submit">创建</Button>
        </form>
      </Card>

      {items.length === 0 ? (
        <EmptyState message="暂无基准。" />
      ) : (
        <div className="space-y-2">
          {items.map((b) => (
            <Card key={b.id} className="flex items-center justify-between p-4">
              <div>
                <p className="font-medium">
                  {b.name}{" "}
                  <span className="ml-1 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">
                    {b.type}
                  </span>
                </p>
                <p className="text-xs text-slate-500">metric: {b.metric}</p>
              </div>
              <Button
                variant="danger"
                onClick={async () => {
                  await deleteBenchmark(b.id);
                  refresh();
                  onChange();
                }}
              >
                删除
              </Button>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
