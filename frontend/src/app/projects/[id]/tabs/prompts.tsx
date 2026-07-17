"use client";

import { useEffect, useState } from "react";
import {
  listPrompts,
  createPrompt,
  deletePrompt,
  type Prompt,
} from "@/lib/api";
import { Button, Card, EmptyState } from "@/components/ui";

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

  async function refresh() {
    setItems(await listPrompts(projectId));
  }
  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !template.trim()) return;
    await createPrompt({ project_id: projectId, name, template });
    setName("");
    setTemplate("");
    refresh();
    onChange();
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
          <Button type="submit">创建</Button>
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
                <Button
                  variant="danger"
                  className="ml-3"
                  onClick={async () => {
                    await deletePrompt(p.id);
                    refresh();
                    onChange();
                  }}
                >
                  删除
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
