"use client";

import { useEffect, useRef, useState } from "react";
import {
  listDatasets,
  importDataset,
  waitForImport,
  deleteDataset,
  archiveDataset,
  unarchiveDataset,
  previewDataset,
  getDatasetPreviewRaw,
  validateDatasetQuick,
  ApiRequestError,
  type Dataset,
  type DatasetRow,
  type DatasetPreviewRaw,
  type DatasetValidationResult,
} from "@/lib/api";
import { Button, Card, EmptyState, Spinner } from "@/components/ui";
import { Archive, ArchiveRestore } from "lucide-react";

/** Simple CSV/JSON parser for previewing a file before upload. */
function parsePreviewFile(file: File, fmt: string): Promise<DatasetRow[]> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const text = reader.result as string;
        const rows: Record<string, unknown>[] = [];

        if (fmt === "csv") {
          const lines = text.split(/\r?\n/).filter(Boolean);
          if (lines.length < 2) {
            resolve([]);
            return;
          }
          const headers = lines[0].split(",").map((h) => h.trim());
          for (let i = 1; i < Math.min(lines.length, 11); i++) {
            const values = lines[i].split(",");
            const row: Record<string, unknown> = {};
            headers.forEach((h, idx) => {
              row[h] = values[idx]?.trim() ?? "";
            });
            rows.push(row);
          }
        } else {
          // JSON / JSONL
          const data = fmt === "jsonl" ? text.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line)) : JSON.parse(text);
          const arr = Array.isArray(data) ? data : data.rows || data.data || [data];
          for (const item of arr.slice(0, 10)) {
            if (typeof item === "object" && item !== null) {
              rows.push(item);
            }
          }
        }

        resolve(rows.map((r, i) => ({ id: "", idx: i, input: r, expected: null })));
      } catch (e) {
        reject(e instanceof Error ? e : new Error("Parse error"));
      }
    };
    reader.onerror = () => reject(new Error("Failed to read file"));
    reader.readAsText(file);
  });
}

export function DatasetsTab({
  projectId,
  onChange,
}: {
  projectId: string;
  onChange: () => void;
}) {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [name, setName] = useState("");
  const [format, setFormat] = useState("jsonl");
  const [preview, setPreview] = useState<{ id: string; rows: DatasetRow[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [importProgress, setImportProgress] = useState<string | null>(null);
  const [uploadPreview, setUploadPreview] = useState<DatasetRow[] | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [serverPreview, setServerPreview] = useState<DatasetPreviewRaw | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [validationResult, setValidationResult] = useState<DatasetValidationResult | null>(null);
  const [validating, setValidating] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function refresh() {
    setDatasets((await listDatasets(projectId)).items);
  }
  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setImportProgress(null);
    setUploadPreview(null);
    const file = fileRef.current?.files?.[0];
    if (!file || !name.trim()) {
      setError("名称和文件均为必填项");
      return;
    }

    // If user has not previewed yet, do a quick auto-preview (text formats only)
    if (!uploadPreview && format !== "tsv" && format !== "xlsx") {
      try {
        setUploadPreview(await parsePreviewFile(file, format));
      } catch (err) {
        setError(err instanceof Error ? err.message : "文件解析失败");
        return;
      }
    }

    const form = new FormData();
    form.set("project_id", projectId);
    form.set("name", name);
    form.set("format", format);
    form.set("file", file);
    try {
      const job = await importDataset(form);
      const finished = await waitForImport(job.id, {
        onProgress: (j) =>
          setImportProgress(
            j.total_rows
              ? `${j.progress.toLocaleString()} / ${j.total_rows.toLocaleString()} 行`
              : null,
          ),
      });
      if (finished.status !== "succeeded") {
        const rows = finished.error_rows ?? [];
        const detail = rows.length
          ? `\n${rows
              .slice(0, 5)
              .map((r) => `第${r.row === null ? "?" : r.row + 1}行: ${r.message}`)
              .join("\n")}`
          : "";
        setError(`${finished.error ?? "导入失败"}${detail}`);
        return;
      }
      setName("");
      if (fileRef.current) fileRef.current.value = "";
      setImportProgress(null);
      refresh();
      onChange();
    } catch (err) {
      setImportProgress(null);
      setError(err instanceof Error ? err.message : "Upload failed");
    }
  }

  async function toggleArchive(d: Dataset) {
    setBusy(true);
    setError(null);
    try {
      if (d.is_archived) {
        await unarchiveDataset(d.id);
      } else {
        await archiveDataset(d.id);
      }
      refresh();
      onChange();
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "归档操作失败");
    } finally {
      setBusy(false);
    }
  }

  async function handlePreviewFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) {
      setUploadPreview(null);
      setServerPreview(null);
      setSelectedFile(null);
      return;
    }
    setSelectedFile(file);
    // Reset prior results when a new file is selected
    setValidationResult(null);

    if (format === "tsv" || format === "xlsx") {
      setUploadPreview(null);
      setError("TSV/XLSX 由服务端解析，上传完成后可在列表中预览");
      return;
    }

    try {
      setPreviewLoading(true);
      setError(null);

      // Client-side quick preview for immediate feedback
      setUploadPreview(await parsePreviewFile(file, format));

      // Server-side preview (uses already-parsed data from DB after upload)
      // Since this is pre-upload, fall back to client-side parsing for now.
      // The server preview will work after upload via the "预览" button on existing datasets.
    } catch (err) {
      setError(err instanceof Error ? err.message : "文件预览失败");
      setUploadPreview(null);
    } finally {
      setPreviewLoading(false);
    }
  }

  async function handleValidate() {
    if (!selectedFile) return;
    if (format === "tsv" || format === "xlsx") {
      setError("TSV/XLSX 由服务端解析，上传后可在列表中预览与校验");
      return;
    }
    setValidating(true);
    setError(null);
    try {
      // For pre-upload validation, use client-side parsing
      const rows = await parsePreviewFile(selectedFile, format);
      const columns: string[] = [];
      for (const r of rows) {
        for (const k of Object.keys(r.input)) {
          if (!columns.includes(k as string)) columns.push(k);
        }
        if (r.expected) {
          for (const k of Object.keys(r.expected)) {
            if (!columns.includes(k as string)) columns.push(k);
          }
        }
      }
      const errors: string[] = [];
      const warnings: string[] = [];

      // Check parseability
      if (rows.length === 0) {
        errors.push("文件解析后没有有效数据行");
      }

      // Check required fields: at least one input-like + one expected-like
      const expectedKeywords = ["expected", "answer", "label", "output", "target", "ground_truth"];
      const hasInput = columns.some((c) => !expectedKeywords.includes(c.toLowerCase()));
      const hasExpected = columns.some((c) => expectedKeywords.includes(c.toLowerCase()));
      if (!hasInput) {
        errors.push("未找到输入字段（需要至少一个非答案类字段，如 question/prompt）");
      }
      if (!hasExpected) {
        warnings.push("未找到预期答案字段（建议包含 answer/label/output 等字段）");
      }

      // Check empty rows
      for (let i = 0; i < rows.length; i++) {
        const allVals = { ...rows[i].input, ...(rows[i].expected || {}) };
        const isEmpty = Object.values(allVals).every(
          (v) => v === null || v === undefined || v === ""
        );
        if (isEmpty) {
          errors.push(`第 ${i + 1} 行：所有字段为空`);
        }
      }

      setValidationResult({
        valid: errors.length === 0,
        errors,
        warnings,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "验证失败");
    } finally {
      setValidating(false);
    }
  }

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <form onSubmit={handleUpload} className="flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[160px]">
            <label className="block text-xs font-medium text-slate-500">名称</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">格式</label>
            <select
              value={format}
              onChange={(e) => setFormat(e.target.value)}
              className="mt-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            >
              <option value="jsonl">JSONL</option>
              <option value="json">JSON</option>
              <option value="csv">CSV</option>
              <option value="tsv">TSV</option>
              <option value="xlsx">XLSX</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">文件</label>
            <input
              ref={fileRef}
              type="file"
              accept=".csv,.json,.jsonl,.tsv,.xlsx"
              className="mt-1 text-sm"
              onChange={handlePreviewFile}
            />
          </div>
          <Button type="submit" disabled={!selectedFile || busy}>
            {busy ? <Spinner size={14} /> : uploadPreview ? "确认上传" : "导入"}
          </Button>
        </form>
        {importProgress && (
          <p className="mt-2 text-xs text-[var(--ocd-text-muted)]">
            正在后台导入：{importProgress}
          </p>
        )}
        {error && <p className="mt-2 text-xs text-red-600">{error}</p>}

        {/* File selection + preview */}
        {selectedFile && (
          <div className="mt-3 space-y-3">
            <div className="flex items-center justify-between">
              <p className="text-xs text-slate-500">
                已选择：{selectedFile.name}（{(selectedFile.size / 1024).toFixed(1)} KB）
              </p>
              {!validationResult && !validating && (
                <Button
                  variant="secondary"
                  onClick={handleValidate}
                  disabled={previewLoading}
                >
                  {previewLoading ? <Spinner size={12} /> : "验证数据集"}
                </Button>
              )}
            </div>

            {/* Loading preview */}
            {previewLoading && (
              <div className="flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 p-3 text-sm text-slate-500">
                <Spinner size={14} /> 正在解析文件…
              </div>
            )}

            {/* Preview table — first 5 rows */}
            {uploadPreview && !previewLoading && (
              <div className="overflow-x-auto rounded-md border border-slate-200 bg-slate-50 p-3">
                <p className="mb-2 text-xs font-medium text-slate-500">
                  文件预览（前 {Math.min(uploadPreview.length, 5)} 行）：
                </p>
                <table className="w-full text-xs">
                  <thead className="text-left text-slate-400">
                    <tr>
                      <th className="pr-3">#</th>
                      {serverPreview
                        ? serverPreview.columns.map((c) => (
                            <th key={c} className="pr-3">
                              {c}
                            </th>
                          ))
                        : Object.keys(uploadPreview[0]?.input || {}).map((k) => (
                            <th key={k} className="pr-3">
                              {k}
                            </th>
                          ))}
                      <th>期望</th>
                    </tr>
                  </thead>
                  <tbody>
                    {uploadPreview.slice(0, 5).map((r) => (
                      <tr key={r.id} className="border-t border-slate-200">
                        <td className="pr-3 py-1">{r.idx}</td>
                        {serverPreview
                          ? serverPreview.columns.map((c) => (
                              <td key={c} className="pr-3 py-1 font-mono">
                                {String(r.input[c] ?? "")}
                              </td>
                            ))
                          : Object.keys(r.input || {}).map((k) => (
                              <td key={k} className="pr-3 py-1 font-mono">
                                {String(r.input[k] ?? "")}
                              </td>
                            ))}
                        <td className="py-1 font-mono">
                          {r.expected ? JSON.stringify(r.expected) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Validation result */}
            {validationResult && (
              <div
                className={`rounded-md border p-3 ${
                  validationResult.valid
                    ? "border-green-200 bg-green-50"
                    : "border-red-200 bg-red-50"
                }`}
              >
                <div className="flex items-center gap-2">
                  {validationResult.valid ? (
                    <span className="text-green-600">&#10003;</span>
                  ) : (
                    <span className="text-red-600">&#10007;</span>
                  )}
                  <span
                    className={`text-sm font-medium ${
                      validationResult.valid ? "text-green-700" : "text-red-700"
                    }`}
                  >
                    {validationResult.valid ? "验证通过" : "发现错误"}
                  </span>
                  <span className="ml-auto text-xs text-slate-500">
                    {validationResult.errors.length} 错误，{validationResult.warnings.length} 警告
                  </span>
                </div>
                {validationResult.errors.length > 0 && (
                  <ul className="mt-2 space-y-1 text-xs text-red-700">
                    {validationResult.errors.map((e, i) => (
                      <li key={i}>&#8226; {e}</li>
                    ))}
                  </ul>
                )}
                {validationResult.warnings.length > 0 && (
                  <ul className="mt-2 space-y-1 text-xs text-amber-700">
                    {validationResult.warnings.map((w, i) => (
                      <li key={i}>&#8226; {w}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {/* Validating spinner */}
            {validating && (
              <div className="flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 p-3 text-sm text-slate-500">
                <Spinner size={14} /> 正在验证…
              </div>
            )}
          </div>
        )}
      </Card>

      {datasets.length === 0 ? (
        <EmptyState message="暂无数据集。导入 CSV/JSON/JSONL 文件即可开始。" />
      ) : (
        <div className="space-y-2">
          {datasets.map((d) => (
            <Card key={d.id} className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-medium">
                    {d.name}{" "}
                    <span className="ml-1 rounded bg-slate-100 px-1.5 py-0.5 text-xs uppercase text-slate-500">
                      {d.format}
                    </span>
                  </p>
                  <p className="text-xs text-slate-500">
                    {d.row_count} rows · columns: {d.column_schema.join(", ") || "—"}
                  </p>
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="secondary"
                    disabled={busy}
                    onClick={async () => {
                      setBusy(true);
                      setError(null);
                      try {
                        setPreview({ id: d.id, rows: await previewDataset(d.id) });
                      } catch (err) {
                        setError(err instanceof ApiRequestError ? err.message : "预览失败");
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    预览
                  </Button>
                  <Button
                    variant="secondary"
                    disabled={busy}
                    title={d.is_archived ? "取消归档" : "归档"}
                    onClick={() => toggleArchive(d)}
                  >
                    {d.is_archived ? <ArchiveRestore size={14} /> : <Archive size={14} />}
                  </Button>
                  <Button
                    variant="danger"
                    disabled={busy}
                    onClick={async () => {
                      if (!confirm(`确定删除数据集「${d.name}」？`)) return;
                      setBusy(true);
                      setError(null);
                      try {
                        await deleteDataset(d.id);
                        refresh();
                        onChange();
                      } catch (err) {
                        setError(err instanceof ApiRequestError ? err.message : "删除失败");
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    删除
                  </Button>
                </div>
              </div>
              {preview?.id === d.id && (
                <div className="mt-3 overflow-x-auto rounded-md border border-slate-200 bg-slate-50 p-3">
                  <table className="w-full text-xs">
                    <thead className="text-left text-slate-400">
                      <tr>
                        <th className="pr-3">#</th>
                        <th className="pr-3">输入</th>
                        <th>期望</th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview.rows.map((r) => (
                        <tr key={r.id} className="border-t border-slate-200">
                          <td className="pr-3 py-1">{r.idx}</td>
                          <td className="pr-3 py-1 font-mono">
                            {JSON.stringify(r.input)}
                          </td>
                          <td className="py-1 font-mono">
                            {JSON.stringify(r.expected)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
