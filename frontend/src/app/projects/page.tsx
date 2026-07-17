"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  listProjects,
  createProject,
  archiveProject,
  type Project,
} from "@/lib/api";
import { Button, Card, Badge, EmptyState, Modal, SectionTitle } from "@/components/ui";
import { Plus, Boxes, Archive, FolderOpen } from "lucide-react";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  async function refresh() {
    setLoading(true);
    try {
      setProjects(await listProjects());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    await createProject({ name, description: description || undefined });
    setName("");
    setDescription("");
    setCreating(false);
    refresh();
  }

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">项目</h1>
          <p className="mt-1 text-sm text-[var(--ocd-text-muted)]">
            每个项目拥有自己的数据集、基准、提示词、实验与报告。
          </p>
        </div>
        <Button
          onClick={() => setCreating(true)}
          className="gap-1.5"
        >
          <Plus size={15} /> 新建项目
        </Button>
      </header>

      <Modal open={creating} onClose={() => setCreating(false)} title="创建项目">
        <form onSubmit={handleCreate} className="space-y-3">
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="项目名称"
            className="w-full rounded-lg border bg-[var(--ocd-bg)] px-3 py-2 text-sm outline-none focus:border-[var(--ocd-accent)]"
            style={{ borderColor: "var(--ocd-border)" }}
          />
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="描述（可选）"
            rows={3}
            className="w-full rounded-lg border bg-[var(--ocd-bg)] px-3 py-2 text-sm outline-none focus:border-[var(--ocd-accent)]"
            style={{ borderColor: "var(--ocd-border)" }}
          />
          <div className="flex gap-2">
            <Button type="submit">创建</Button>
            <Button type="button" variant="ghost" onClick={() => setCreating(false)}>
              取消
            </Button>
          </div>
        </form>
      </Modal>

      {loading ? (
        <EmptyState message="加载中…" icon={<Boxes size={28} />} />
      ) : projects.length === 0 ? (
        <EmptyState message="暂无项目。创建第一个项目以开始。" icon={<Boxes size={28} />} />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {projects.map((p) => (
            <Card key={p.id} className="flex flex-col p-5">
              <div className="flex items-start justify-between gap-2">
                <Link
                  href={`/projects/${p.id}`}
                  className="text-base font-semibold hover:underline"
                >
                  {p.name}
                </Link>
                <Badge status={p.status}>{p.status}</Badge>
              </div>
              <p className="mt-2 line-clamp-2 flex-1 text-sm text-[var(--ocd-text-muted)]">
                {p.description || "无描述"}
              </p>
              <div className="mt-4 flex gap-2">
                <Link href={`/projects/${p.id}`}>
                  <Button variant="secondary" className="gap-1.5">
                    <FolderOpen size={14} /> 打开
                  </Button>
                </Link>
                {p.status === "active" && (
                  <Button
                    variant="ghost"
                    className="gap-1.5"
                    onClick={async () => {
                      await archiveProject(p.id);
                      refresh();
                    }}
                  >
                    <Archive size={14} /> 归档
                  </Button>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
