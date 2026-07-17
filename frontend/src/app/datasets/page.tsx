"use client";

import { useEffect, useState } from "react";
import {
  listDatasets,
  listProjects,
  uploadDataset,
  deleteDataset,
  previewDataset,
  type Dataset,
  type DatasetRow,
  type Project,
} from "@/lib/api";
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Modal,
  SectionTitle,
  Spinner,
} from "@/components/ui";
import { Database, Upload, Trash2, ArrowLeft, Eye } from "lucide-react";

export default function DatasetsPage() {
  const [items, setItems] = useState<Dataset[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectMap, setProjectMap] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);

  const [uploadOpen, setUploadOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [projectId, setProjectId] = useState("");

  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewRows, setPreviewRows] = useState<DatasetRow[] | null>(null);
  const [previewName, setPreviewName] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      const [ds, ps] = await Promise.all([
        listDatasets(""),
        listProjects(),
      ]);
      setItems(ds);
      setProjects(ps);
      setProjectMap(Object.fromEntries(ps.map((p) => [p.id, p.name])));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  function openUpload() {
    setFile(null);
    setName("");
    setDescription("");
    setProjectId(projects[0]?.id ?? "");
    setUploadOpen(true);
  }

  async function submit() {
    if (!file || !projectId) return;
    setSubmitting(true);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("project_id", projectId);
      if (name) form.append("name", name);
      await uploadDataset(form);
      setUploadOpen(false);
      await refresh();
    } finally {
      setSubmitting(false);
    }
  }

  async function openPreview(d: Dataset) {
    setPreviewName(d.name);
    setPreviewRows(null);
    setPreviewOpen(true);
    setPreviewLoading(true);
    try {
      setPreviewRows(await previewDataset(d.id));
    } finally {
      setPreviewLoading(false);
    }
  }

  async function remove(id: string) {
    await deleteDataset(id);
    await refresh();
  }

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">数据集</h1>
          <p className="mt-1 text-sm text-[var(--ocd-text-muted)]">
            各项目下上传的评测数据集。
          </p>
        </div>
        <Button onClick={openUpload}>
          <Upload size={15} /> 上传数据集
        </Button>
      </header>

      {loading ? (
        <EmptyState message="Loading…" icon={<Spinner size={20} />} />
      ) : items.length === 0 ? (
        <EmptyState message="暂无数据集。上传一项以开始。" icon={<Database size={28} />} />
      ) : (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead
              className="border-b text-left text-xs uppercase tracking-wider text-[var(--ocd-text-faint)]"
              style={{ borderColor: "var(--ocd-border)" }}
            >
              <tr>
                <th className="px-4 py-3">名称</th>
                <th className="px-4 py-3">格式</th>
                <th className="px-4 py-3">行数</th>
                <th className="px-4 py-3">项目</th>
                <th className="px-4 py-3">标签</th>
                <th className="px-4 py-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((d) => (
                <tr
                  key={d.id}
                  className="border-b last:border-0"
                  style={{ borderColor: "var(--ocd-border-soft)" }}
                >
                  <td className="px-4 py-3 font-medium">{d.name}</td>
                  <td className="px-4 py-3">
                    <Badge>{d.format}</Badge>
                  </td>
                  <td className="px-4 py-3 text-[var(--ocd-text-muted)]">
                    {d.row_count.toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-[var(--ocd-text-muted)]">
                    {projectMap[d.project_id] ?? d.project_id}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      {d.tags.map((t) => (
                        <span
                          key={t}
                          className="rounded px-1.5 py-0.5 text-xs"
                          style={{
                            background: "var(--ocd-surface-2)",
                            color: "var(--ocd-text-muted)",
                          }}
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-2">
                      <Button variant="ghost" onClick={() => openPreview(d)}>
                        <Eye size={14} /> 预览
                      </Button>
                      <Button variant="danger" onClick={() => remove(d.id)}>
                        <Trash2 size={14} />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      <Modal open={uploadOpen} onClose={() => setUploadOpen(false)} title="上传数据集">
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

          <Field label="文件">
            <input
              type="file"
              className="w-full rounded-lg bg-[var(--ocd-bg)] px-3 py-2 text-sm text-[var(--ocd-text)]"
              style={{ borderColor: "var(--ocd-border)", borderWidth: 1 }}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              required
            />
          </Field>

          <Field label="名称 (可选)">
            <input
              className="w-full rounded-lg bg-[var(--ocd-bg)] px-3 py-2 text-sm text-[var(--ocd-text)]"
              style={{ borderColor: "var(--ocd-border)", borderWidth: 1 }}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="根据文件名自动生成"
            />
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
            <Button variant="secondary" onClick={() => setUploadOpen(false)} type="button">
              取消
            </Button>
            <Button type="submit" disabled={submitting || !file}>
              {submitting ? <Spinner size={14} /> : "上传"}
            </Button>
          </div>
        </form>
      </Modal>

      <Modal open={previewOpen} onClose={() => setPreviewOpen(false)} title={`Preview · ${previewName}`}>
        {previewLoading ? (
          <div className="flex justify-center py-8">
            <Spinner size={20} />
          </div>
        ) : !previewRows || previewRows.length === 0 ? (
          <p className="py-6 text-center text-sm text-[var(--ocd-text-muted)]">暂无行数据。</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead
                className="border-b text-left text-xs uppercase tracking-wider text-[var(--ocd-text-faint)]"
                style={{ borderColor: "var(--ocd-border)" }}
              >
                <tr>
                  <th className="px-3 py-2">#</th>
                  <th className="px-3 py-2">输入</th>
                  <th className="px-3 py-2">期望</th>
                </tr>
              </thead>
              <tbody>
                {previewRows.map((r) => (
                  <tr key={r.id} className="border-b last:border-0" style={{ borderColor: "var(--ocd-border-soft)" }}>
                    <td className="px-3 py-2 text-[var(--ocd-text-muted)]">{r.idx}</td>
                    <td className="px-3 py-2 font-mono text-xs text-[var(--ocd-text-muted)]">
                      {JSON.stringify(r.input)}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-[var(--ocd-text-muted)]">
                      {r.expected ? JSON.stringify(r.expected) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
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
