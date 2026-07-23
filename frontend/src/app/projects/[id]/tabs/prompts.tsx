"use client";

import { useEffect, useState } from "react";
import {
  listPrompts,
  createPrompt,
  deletePrompt,
  ApiRequestError,
  type Prompt,
} from "@/lib/api";
import { Button, Card, EmptyState } from "@/components/ui";
import { Eye } from "lucide-react";

export function PromptsTab({
  projectId,
  onChange,
}: {
  projectId: string;
  onChange: () => void;
}) {
  const [items, setItems] = useState<Prompt[]>([]);
  const [name, setName] = useState("");
  const [template, setTemplate] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [previewModal, setPreviewModal] = useState<{
    template: string;
    variables: string[];
  } | null>(null);

  async function refresh() {
    setItems(await listPrompts(projectId));
  }
  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!name.trim() || !template.trim()) return;
    setBusy(true);
    try {
      await createPrompt({ project_id: projectId, name, template });
      setName("");
      setTemplate("");
      refresh();
      onChange();
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <form onSubmit={handleCreate} className="space-y-3">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="提示词名称"
            className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
          <textarea
            value={template}
            onChange={(e) => setTemplate(e.target.value)}
            placeholder="模板 — 使用 {变量} 占位符,例如:回答问题:{question}"
            rows={3}
            className="w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-sm"
          />
          <Button type="submit" disabled={busy}>创建</Button>
          {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
        </form>
      </Card>

      {items.length === 0 ? (
        <EmptyState message="暂无提示词。变量会从 {占位符} 中自动提取。" />
      ) : (
        <div className="space-y-2">
          {items.map((p) => (
            <Card key={p.id} className="p-4">
              <div className="flex items-start justify-between">
                <div className="min-w-0 flex-1">
                  <p className="font-medium">
                    {p.name}{" "}
                    <span className="text-xs text-slate-400">v{p.version}</span>
                  </p>
                  <pre className="mt-1 overflow-x-auto whitespace-pre-wrap rounded bg-slate-50 p-2 font-mono text-xs text-slate-600">
                    {p.template}
                  </pre>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {p.variables.map((v) => (
                      <span
                        key={v}
                        className="rounded bg-blue-50 px-1.5 py-0.5 text-xs text-blue-700"
                      >
                        {`{${v}}`}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="ml-3 flex shrink-0 gap-2">
                  <Button
                    variant="secondary"
                    onClick={() => setPreviewModal({ template: p.template, variables: p.variables })}
                    disabled={busy}
                  >
                    <Eye size={14} /> 预览
                  </Button>
                  <Button
                    variant="danger"
                    disabled={busy}
                    onClick={async () => {
                      if (!confirm(`确定删除提示词「${p.name}」？`)) return;
                      setBusy(true);
                      setError(null);
                      try {
                        await deletePrompt(p.id);
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
            </Card>
          ))}
        </div>
      )}

      {/* Preview Modal */}
      {previewModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <Card className="mx-4 w-full max-w-lg p-5">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-semibold">提示词渲染预览</h3>
              <button
                onClick={() => setPreviewModal(null)}
                className="text-xs text-[var(--ocd-text-muted)] hover:text-[var(--ocd-text)]"
              >
                关闭
              </button>
            </div>
            <div className="rounded-md border bg-slate-50 p-3 font-mono text-xs text-slate-700">
              <p className="text-slate-400 mb-2">模板：</p>
              <pre className="whitespace-pre-wrap break-all">{previewModal.template}</pre>
              {previewModal.variables.length > 0 && (
                <>
                  <p className="text-slate-400 mt-3 mb-2">变量（未赋值）：</p>
                  <ul className="list-inside list-disc">
                    {previewModal.variables.map((v) => (
                      <li key={v} className="text-blue-600">
                        {`{${v}}`} → (空)
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
