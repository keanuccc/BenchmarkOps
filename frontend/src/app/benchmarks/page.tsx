"use client";

import { useEffect, useState } from "react";
import {
  listBenchmarks,
  listProjects,
  createBenchmark,
  deleteBenchmark,
  archiveBenchmark,
  unarchiveBenchmark,
  apiErrorMessage,
  getMetrics,
  type Benchmark,
  type Project,
} from "@/lib/api";
import { useToast } from "@/components/notifications";
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Modal,
  SectionTitle,
  Spinner,
} from "@/components/ui";
import { PaginationBar } from "@/components/pagination";
import { Target, Plus, Trash2, Archive, ArchiveRestore } from "lucide-react";

const TYPES = ["qa", "coding", "agent", "classification", "generation"];

export default function BenchmarksPage() {
  const { addToast } = useToast();
  const [items, setItems] = useState<Benchmark[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectMap, setProjectMap] = useState<Record<string, string>>({});
  const [metrics, setMetrics] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const PAGE_SIZE = 20;

  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [projectId, setProjectId] = useState("");
  const [name, setName] = useState("");
  const [type, setType] = useState(TYPES[0]);
  const [metric, setMetric] = useState("");
  const [description, setDescription] = useState("");

  async function refresh() {
    setLoading(true);
    try {
      const [bms, ps] = await Promise.all([
        listBenchmarks(undefined, {
          q: search || undefined,
          offset: (page - 1) * PAGE_SIZE,
          limit: PAGE_SIZE,
        }),
        listProjects(),
      ]);
      setItems(bms.items);
      setTotal(bms.total);
      setProjects(ps.items);
      setProjectMap(Object.fromEntries(ps.items.map((p) => [p.id, p.name])));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, search]);

  function openModal() {
    setName("");
    setDescription("");
    setType(TYPES[0]);
    setMetric(metrics[0] ?? "");
    setProjectId(projects[0]?.id ?? "");
    setOpen(true);
  }

  useEffect(() => {
    getMetrics()
      .then((m) => {
        setMetrics(m.metrics);
        if (!metric) setMetric(m.defaults[type] ?? m.metrics[0] ?? "");
      })
      .catch(() => {});
  }, []);

  async function submit() {
    if (!projectId || !name || !type) return;
    setSubmitting(true);
    try {
      await createBenchmark({
        project_id: projectId,
        name,
        type,
        metric: metric || undefined,
        description: description || undefined,
      });
      setOpen(false);
      await refresh();
      addToast("success", "基准创建成功");
    } catch (err) {
      addToast("error", apiErrorMessage(err, "创建基准失败"));
    } finally {
      setSubmitting(false);
    }
  }

  async function remove(id: string) {
    try {
      await deleteBenchmark(id);
      await refresh();
      addToast("success", "基准已删除");
    } catch (err) {
      addToast("error", apiErrorMessage(err, "删除基准失败"));
    }
  }

  async function toggleArchive(b: Benchmark) {
    try {
      if (b.is_archived) {
        await unarchiveBenchmark(b.id);
        addToast("success", `已恢复「${b.name}」`);
      } else {
        await archiveBenchmark(b.id);
        addToast("success", `已归档「${b.name}」`);
      }
      await refresh();
    } catch (err) {
      addToast("error", apiErrorMessage(err, "归档操作失败"));
    }
  }

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">基准</h1>
          <p className="mt-1 text-sm text-[var(--ocd-text-muted)]">
            各项目的评测协议与评分指标。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            placeholder="搜索名称…"
            className="h-10 w-48 rounded-xl border bg-[var(--ocd-bg)] px-3 text-sm text-[var(--ocd-text)]"
            style={{ borderColor: "var(--ocd-border)" }}
          />
          <Button onClick={openModal}>
            <Plus size={15} /> 新建基准
          </Button>
        </div>
      </header>

      {loading ? (
        <EmptyState message="Loading…" icon={<Spinner size={20} />} />
      ) : items.length === 0 ? (
        <EmptyState message="暂无基准。创建一项以开始。" icon={<Target size={28} />} />
      ) : (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead
              className="border-b text-left text-xs uppercase tracking-wider text-[var(--ocd-text-faint)]"
              style={{ borderColor: "var(--ocd-border)" }}
            >
              <tr>
                <th className="px-4 py-3">名称</th>
                <th className="px-4 py-3">类型</th>
                <th className="px-4 py-3">指标</th>
                <th className="px-4 py-3">项目</th>
                <th className="px-4 py-3">描述</th>
                <th className="px-4 py-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((b) => (
                <tr
                  key={b.id}
                  className="border-b last:border-0"
                  style={{ borderColor: "var(--ocd-border-soft)" }}
                >
                  <td className="px-4 py-3 font-medium">{b.name}</td>
                  <td className="px-4 py-3">
                    <Badge>{b.type}</Badge>
                  </td>
                  <td className="px-4 py-3 text-[var(--ocd-text-muted)]">{b.metric}</td>
                  <td className="px-4 py-3 text-[var(--ocd-text-muted)]">
                    {projectMap[b.project_id] ?? b.project_id}
                  </td>
                  <td className="px-4 py-3 text-[var(--ocd-text-muted)]">
                    {b.description ?? "—"}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-2">
                      <Button
                        variant="ghost"
                        title={b.is_archived ? "取消归档" : "归档"}
                        onClick={() => toggleArchive(b)}
                      >
                        {b.is_archived ? (
                          <ArchiveRestore size={14} />
                        ) : (
                          <Archive size={14} />
                        )}
                      </Button>
                      <Button
                        variant="danger"
                        title="删除"
                        onClick={() => remove(b.id)}
                      >
                        <Trash2 size={14} />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <PaginationBar
            total={total}
            page={page}
            pageSize={PAGE_SIZE}
            onChange={setPage}
          />
        </Card>
      )}

      <Modal open={open} onClose={() => setOpen(false)} title="新建基准">
        <form
          className="space-y-4"
          onSubmit={(ev) => {
            ev.preventDefault();
            submit();
          }}
        >
          <Field label="项目">
            <select
              className="w-full rounded-lg bg-[var(--ocd-bg)] px-3 py-2 text-sm text-[var(--ocd-text)]"
              style={{ borderColor: "var(--ocd-border)", borderWidth: 1 }}
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              required
            >
              <option value="">选择项目…</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </Field>

          <Field label="名称">
            <input
              className="w-full rounded-lg bg-[var(--ocd-bg)] px-3 py-2 text-sm text-[var(--ocd-text)]"
              style={{ borderColor: "var(--ocd-border)", borderWidth: 1 }}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="基准名称"
              required
            />
          </Field>

          <Field label="类型">
            <select
              className="w-full rounded-lg bg-[var(--ocd-bg)] px-3 py-2 text-sm text-[var(--ocd-text)]"
              style={{ borderColor: "var(--ocd-border)", borderWidth: 1 }}
              value={type}
              onChange={(e) => {
                const t = e.target.value;
                setType(t);
                setMetric(metrics[0] ?? "");
              }}
              required
            >
              {TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </Field>

          <Field label="指标">
            <select
              className="w-full rounded-lg bg-[var(--ocd-bg)] px-3 py-2 text-sm text-[var(--ocd-text)]"
              style={{ borderColor: "var(--ocd-border)", borderWidth: 1 }}
              value={metric}
              onChange={(e) => setMetric(e.target.value)}
              required
            >
              {metrics.length === 0 && <option value="">—</option>}
              {metrics.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </Field>

          <Field label="描述 (可选)">
            <textarea
              className="w-full rounded-lg bg-[var(--ocd-bg)] px-3 py-2 text-sm text-[var(--ocd-text)]"
              style={{ borderColor: "var(--ocd-border)", borderWidth: 1 }}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
            />
          </Field>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setOpen(false)} type="button">
              取消
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? <Spinner size={14} /> : "创建"}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-xs uppercase tracking-wider text-[var(--ocd-text-muted)]">
        {label}
      </span>
      {children}
    </label>
  );
}
