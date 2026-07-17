"use client";

import { useEffect, useState } from "react";
import {
  listPrompts,
  listProjects,
  createPrompt,
  deletePrompt,
  type Prompt,
  type Project,
} from "@/lib/api";
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Modal,
  Spinner,
} from "@/components/ui";
import { Library, Plus, Trash2 } from "lucide-react";

export default function PromptsPage() {
  const [items, setItems] = useState<Prompt[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectMap, setProjectMap] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);

  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [projectId, setProjectId] = useState("");
  const [name, setName] = useState("");
  const [template, setTemplate] = useState("");
  const [description, setDescription] = useState("");

  async function refresh() {
    setLoading(true);
    try {
      const [prs, ps] = await Promise.all([listPrompts(""), listProjects()]);
      setItems(prs);
      setProjects(ps);
      setProjectMap(Object.fromEntries(ps.map((p) => [p.id, p.name])));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  function openModal() {
    setName("");
    setTemplate("");
    setDescription("");
    setProjectId(projects[0]?.id ?? "");
    setOpen(true);
  }

  async function submit() {
    if (!projectId || !name || !template) return;
    setSubmitting(true);
    try {
      await createPrompt({
        project_id: projectId,
        name,
        template,
        description: description || undefined,
      });
      setOpen(false);
      await refresh();
    } finally {
      setSubmitting(false);
    }
  }

  async function remove(id: string) {
    await deletePrompt(id);
    await refresh();
  }

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">提示词库</h1>
          <p className="mt-1 text-sm text-[var(--ocd-text-muted)]">
            可复用的提示词模板,使用单花括号变量占位符。
          </p>
        </div>
        <Button onClick={openModal}>
          <Plus size={15} /> 新建提示词
        </Button>
      </header>

      {loading ? (
        <EmptyState message="Loading…" icon={<Spinner size={20} />} />
      ) : items.length === 0 ? (
        <EmptyState message="暂无提示词。创建一项以开始。" icon={<Library size={28} />} />
      ) : (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead
              className="border-b text-left text-xs uppercase tracking-wider text-[var(--ocd-text-faint)]"
              style={{ borderColor: "var(--ocd-border)" }}
            >
              <tr>
                <th className="px-4 py-3">名称</th>
                <th className="px-4 py-3">版本</th>
                <th className="px-4 py-3">项目</th>
                <th className="px-4 py-3">模板</th>
                <th className="px-4 py-3">描述</th>
                <th className="px-4 py-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr
                  key={p.id}
                  className="border-b last:border-0"
                  style={{ borderColor: "var(--ocd-border-soft)" }}
                >
                  <td className="px-4 py-3 font-medium">{p.name}</td>
                  <td className="px-4 py-3">
                    <Badge>v{p.version}</Badge>
                  </td>
                  <td className="px-4 py-3 text-[var(--ocd-text-muted)]">
                    {projectMap[p.project_id] ?? p.project_id}
                  </td>
                  <td className="px-4 py-3">
                    <code className="block max-w-[260px] truncate font-mono text-xs text-[var(--ocd-text-muted)]">
                      {p.template}
                    </code>
                  </td>
                  <td className="px-4 py-3 text-[var(--ocd-text-muted)]">
                    {p.description ?? "—"}
                  </td>
                  <td className="px-4 py-3">
                    <Button variant="danger" onClick={() => remove(p.id)}>
                      <Trash2 size={14} />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      <Modal open={open} onClose={() => setOpen(false)} title="新建提示词">
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
              placeholder="提示词名称"
              required
            />
          </Field>

          <Field label="模板">
            <textarea
              className="w-full rounded-lg bg-[var(--ocd-bg)] px-3 py-2 font-mono text-sm text-[var(--ocd-text)]"
              style={{ borderColor: "var(--ocd-border)", borderWidth: 1 }}
              value={template}
              onChange={(e) => setTemplate(e.target.value)}
              rows={5}
              placeholder="请回答以下问题:{question}"
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
