"use client";

import { useEffect, useState } from "react";
import {
  listDatasets,
  listProjects,
  importDataset,
  waitForImport,
  listDatasetVersions,
  createDatasetVersion,
  activateDatasetVersion,
  deleteDataset,
  archiveDataset,
  unarchiveDataset,
  apiErrorMessage,
  previewDataset,
  type Dataset,
  type DatasetRow,
  type DatasetVersion,
  type ImportJob,
  type Project,
} from "@/lib/api";
import { useToast } from "@/components/notifications";
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Modal,
  Spinner,
} from "@/components/ui";
import { PaginationBar } from "@/components/pagination";
import {
  Database,
  Upload,
  Trash2,
  Eye,
  Archive,
  ArchiveRestore,
  History,
} from "lucide-react";

export default function DatasetsPage() {
  const { addToast } = useToast();
  const [items, setItems] = useState<Dataset[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectMap, setProjectMap] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const PAGE_SIZE = 20;

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

  const [versionsOpen, setVersionsOpen] = useState(false);
  const [versions, setVersions] = useState<DatasetVersion[]>([]);
  const [versionsDataset, setVersionsDataset] = useState<Dataset | null>(null);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [versionMode, setVersionMode] = useState<"replace" | "append">("replace");
  const [versionFile, setVersionFile] = useState<File | null>(null);
  const [versionSubmitting, setVersionSubmitting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [importJob, setImportJob] = useState<ImportJob | null>(null);
  const [structuredChat, setStructuredChat] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      const [ds, ps] = await Promise.all([
        listDatasets(undefined, {
          q: search || undefined,
          offset: (page - 1) * PAGE_SIZE,
          limit: PAGE_SIZE,
        }),
        listProjects(),
      ]);
      setItems(ds.items);
      setTotal(ds.total);
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

  function openUpload() {
    setFile(null);
    setName("");
    setDescription("");
    setProjectId(projects[0]?.id ?? "");
    setImportError(null);
    setImportJob(null);
    setStructuredChat(false);
    setUploadOpen(true);
  }

  async function submit() {
    if (!file || !projectId) return;
    setSubmitting(true);
    setImportError(null);
    setImportJob(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("project_id", projectId);
      if (name) form.append("name", name);
      if (structuredChat) form.append("structured_chat", "true");
      const job = await importDataset(form);
      setImportJob(job);
      const finished = await waitForImport(job.id, { onProgress: setImportJob });
      if (finished.status !== "succeeded") {
        const rows = finished.error_rows ?? [];
        const detail = rows.length
          ? `\n${rows
              .slice(0, 5)
              .map((r) => `第${r.row === null ? "?" : r.row + 1}行: ${r.message}`)
              .join("\n")}`
          : "";
        setImportError(`${finished.error ?? "导入失败"}${detail}`);
        return;
      }
      setUploadOpen(false);
      await refresh();
      addToast("success", "数据集上传成功");
    } catch (err) {
      setImportError(apiErrorMessage(err, "上传数据集失败"));
    } finally {
      setSubmitting(false);
    }
  }

  async function openVersions(d: Dataset) {
    setVersionsDataset(d);
    setVersionsOpen(true);
    setVersionFile(null);
    setVersionMode("replace");
    setVersionsLoading(true);
    try {
      setVersions(await listDatasetVersions(d.id));
    } finally {
      setVersionsLoading(false);
    }
  }

  async function submitVersion() {
    if (!versionsDataset || !versionFile) return;
    setVersionSubmitting(true);
    try {
      const form = new FormData();
      form.append("file", versionFile);
      form.append("mode", versionMode);
      await createDatasetVersion(versionsDataset.id, form);
      setVersions(await listDatasetVersions(versionsDataset.id));
      await refresh();
      addToast("success", versionMode === "replace" ? "已创建替换版本" : "已追加数据");
    } catch (err) {
      addToast("error", apiErrorMessage(err, "创建版本失败"));
    } finally {
      setVersionSubmitting(false);
    }
  }

  async function activateVersion(version: number) {
    if (!versionsDataset) return;
    try {
      const updated = await activateDatasetVersion(versionsDataset.id, version);
      setVersionsDataset(updated);
      setVersions(await listDatasetVersions(versionsDataset.id));
      await refresh();
      addToast("success", `已激活版本 ${version}`);
    } catch (err) {
      addToast("error", apiErrorMessage(err, "激活版本失败"));
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
    try {
      await deleteDataset(id);
      if (items.length === 1 && page > 1) {
        setPage((p) => p - 1);
      } else {
        await refresh();
      }
      addToast("success", "数据集已删除");
    } catch (err) {
      addToast("error", apiErrorMessage(err, "删除数据集失败"));
    }
  }

  async function toggleArchive(d: Dataset) {
    try {
      if (d.is_archived) {
        await unarchiveDataset(d.id);
        addToast("success", `已恢复「${d.name}」`);
      } else {
        await archiveDataset(d.id);
        addToast("success", `已归档「${d.name}」`);
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
          <h1 className="text-2xl font-semibold tracking-tight">数据集</h1>
          <p className="mt-1 text-sm text-[var(--ocd-text-muted)]">
            各项目下上传的评测数据集。
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
          <Button onClick={openUpload}>
            <Upload size={15} /> 上传数据集
          </Button>
        </div>
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
                      <Button variant="ghost" onClick={() => openVersions(d)}>
                        <History size={14} /> 版本
                      </Button>
                      <Button variant="ghost" onClick={() => openPreview(d)}>
                        <Eye size={14} /> 预览
                      </Button>
                      <Button
                        variant="ghost"
                        title={d.is_archived ? "取消归档" : "归档"}
                        onClick={() => toggleArchive(d)}
                      >
                        {d.is_archived ? (
                          <ArchiveRestore size={14} />
                        ) : (
                          <Archive size={14} />
                        )}
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
          <PaginationBar
            total={total}
            page={page}
            pageSize={PAGE_SIZE}
            onChange={setPage}
          />
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
              accept=".jsonl,.json,.csv,.tsv,.xlsx"
              className="w-full rounded-lg bg-[var(--ocd-bg)] px-3 py-2 text-sm text-[var(--ocd-text)]"
              style={{ borderColor: "var(--ocd-border)", borderWidth: 1 }}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              required
            />
            <p className="mt-1 text-xs text-[var(--ocd-text-muted)]">
              支持 JSONL / JSON / CSV / TSV / XLSX，单文件 ≤ 50 MB，≤ 100,000 行；大文件在后台导入。
            </p>
          </Field>

          <Field label="名称">
            <input
              className="w-full rounded-lg bg-[var(--ocd-bg)] px-3 py-2 text-sm text-[var(--ocd-text)]"
              style={{ borderColor: "var(--ocd-border)", borderWidth: 1 }}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="请输入名称"
              required
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

          <label className="flex cursor-pointer items-center gap-2 text-sm text-[var(--ocd-text)]">
            <input
              type="checkbox"
              checked={structuredChat}
              onChange={(e) => setStructuredChat(e.target.checked)}
            />
            结构化对话（启用 messages 对话历史与 examples 少样本示例）
          </label>

          {importJob &&
            (importJob.status === "queued" || importJob.status === "running") && (
              <div
                className="rounded-lg border p-3 text-sm"
                style={{ borderColor: "var(--ocd-border)" }}
              >
                正在后台导入
                {importJob.total_rows
                  ? `：${importJob.progress.toLocaleString()} / ${importJob.total_rows.toLocaleString()} 行`
                  : "…"}
              </div>
            )}

          {importError && (
            <div
              className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
              style={{ whiteSpace: "pre-wrap" }}
            >
              {importError}
            </div>
          )}

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

      <Modal
        open={versionsOpen}
        onClose={() => setVersionsOpen(false)}
        title={versionsDataset ? `版本管理 · ${versionsDataset.name}` : "版本管理"}
      >
        <div className="space-y-4">
          {versionsLoading ? (
            <div className="flex justify-center py-8">
              <Spinner size={20} />
            </div>
          ) : (
            <div className="space-y-2">
              {versions.length === 0 ? (
                <p className="py-4 text-center text-sm text-[var(--ocd-text-muted)]">
                  暂无版本。
                </p>
              ) : (
                versions.map((v) => {
                  const current = versionsDataset?.version === v.version;
                  return (
                    <div
                      key={v.id}
                      className="flex items-center justify-between rounded-lg border p-3"
                      style={{ borderColor: "var(--ocd-border-soft)" }}
                    >
                      <div>
                        <div className="flex items-center gap-2 text-sm font-medium">
                          v{v.version}
                          {current && (
                            <Badge status="active">当前</Badge>
                          )}
                        </div>
                        <div className="mt-0.5 text-xs text-[var(--ocd-text-muted)]">
                          {v.row_count.toLocaleString()} 行 · {v.source_filename ?? "—"} ·{" "}
                          {new Date(v.created_at).toLocaleString()}
                        </div>
                      </div>
                      {!current && (
                        <Button
                          variant="secondary"
                          onClick={() => activateVersion(v.version)}
                        >
                          激活
                        </Button>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          )}

          <div className="rounded-lg border p-3" style={{ borderColor: "var(--ocd-border-soft)" }}>
            <p className="mb-2 text-sm font-medium">新建版本</p>
            <div className="flex flex-wrap items-end gap-2">
              <select
                className="rounded-lg bg-[var(--ocd-bg)] px-3 py-2 text-sm text-[var(--ocd-text)]"
                style={{ borderColor: "var(--ocd-border)", borderWidth: 1 }}
                value={versionMode}
                onChange={(e) => setVersionMode(e.target.value as "replace" | "append")}
              >
                <option value="replace">替换 (新版本)</option>
                <option value="append">追加到当前版本之上</option>
              </select>
              <input
                type="file"
                accept=".jsonl,.json,.csv,.tsv,.xlsx"
                className="text-sm"
                onChange={(e) => setVersionFile(e.target.files?.[0] ?? null)}
              />
              <Button onClick={submitVersion} disabled={versionSubmitting || !versionFile}>
                {versionSubmitting ? <Spinner size={14} /> : "上传新版本"}
              </Button>
            </div>
          </div>
        </div>
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
