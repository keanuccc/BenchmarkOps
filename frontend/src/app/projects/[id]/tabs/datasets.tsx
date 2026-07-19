"use client";

import { useEffect, useRef, useState } from "react";
import {
  listDatasets,
  uploadDataset,
  deleteDataset,
  previewDataset,
  ApiRequestError,
  type Dataset,
  type DatasetRow,
} from "@/lib/api";
import { Button, Card, EmptyState } from "@/components/ui";

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
  const fileRef = useRef<HTMLInputElement>(null);

  async function refresh() {
    setDatasets(await listDatasets(projectId));
  }
  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const file = fileRef.current?.files?.[0];
    if (!file || !name.trim()) {
      setError("名称和文件均为必填项");
      return;
    }
    const form = new FormData();
    form.set("project_id", projectId);
    form.set("name", name);
    form.set("format", format);
    form.set("file", file);
    try {
      await uploadDataset(form);
      setName("");
      if (fileRef.current) fileRef.current.value = "";
      refresh();
      onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
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
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500">文件</label>
            <input
              ref={fileRef}
              type="file"
              accept=".csv,.json,.jsonl"
              className="mt-1 text-sm"
            />
          </div>
          <Button type="submit">导入</Button>
        </form>
        {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
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
