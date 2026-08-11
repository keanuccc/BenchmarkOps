"use client";

import { useCallback, useEffect, useState } from "react";
import {
  createScheduledReport,
  deleteScheduledReport,
  listScheduledReports,
  runScheduledReportNow,
  updateScheduledReport,
  type Experiment,
  type ScheduledReportInfo,
} from "@/lib/api";
import { Badge, Button, Card, EmptyState, SectionTitle } from "@/components/ui";
import { useToast } from "@/components/notifications";
import { CalendarClock, Play, Plus, Trash2 } from "lucide-react";

const SCHEDULE_LABELS: Record<string, string> = {
  daily: "每日",
  weekly: "每周",
  monthly: "每月",
};

export function ScheduledReportsPanel({
  projectId,
  experiments,
}: {
  projectId: string;
  experiments: Experiment[];
}) {
  const { addToast } = useToast();
  const [items, setItems] = useState<ScheduledReportInfo[]>([]);
  const [name, setName] = useState("");
  const [schedule, setSchedule] = useState<"daily" | "weekly" | "monthly">("daily");
  const [format, setFormat] = useState<"md" | "html" | "pdf">("md");
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setItems(await listScheduledReports(projectId));
    } catch {
      setItems([]);
    }
  }, [projectId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleCreate() {
    if (!name.trim() || checked.size === 0) {
      addToast("error", "请填写名称并至少选择一个实验");
      return;
    }
    setBusy(true);
    try {
      await createScheduledReport({
        project_id: projectId,
        name: name.trim(),
        experiment_ids: [...checked],
        schedule,
        format,
      });
      setName("");
      setChecked(new Set());
      addToast("success", "定时报告已创建");
      refresh();
    } catch (e) {
      addToast("error", e instanceof Error ? e.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleRun(id: string) {
    try {
      await runScheduledReportNow(id);
      addToast("success", "已触发，稍后在报告列表查看");
      refresh();
    } catch (e) {
      addToast("error", e instanceof Error ? e.message : "运行失败");
    }
  }

  async function handleToggle(item: ScheduledReportInfo) {
    try {
      await updateScheduledReport(item.id, { is_active: !item.is_active });
      refresh();
    } catch (e) {
      addToast("error", e instanceof Error ? e.message : "操作失败");
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteScheduledReport(id);
      addToast("success", "已删除");
      refresh();
    } catch (e) {
      addToast("error", e instanceof Error ? e.message : "删除失败");
    }
  }

  return (
    <Card className="p-5 space-y-4">
      <SectionTitle>
        <span className="flex items-center gap-2">
          <CalendarClock size={14} /> 定时报告（持续评测订阅）
        </span>
      </SectionTitle>

      {items.length === 0 ? (
        <EmptyState message="还没有定时报告，创建后后端会自动按周期生成。" />
      ) : (
        <div className="space-y-2">
          {items.map((item) => (
            <div
              key={item.id}
              className="flex flex-wrap items-center justify-between gap-2 border border-neutral-800 rounded-lg px-3 py-2 text-sm"
            >
              <div className="flex items-center gap-2">
                <span className="font-medium">{item.name}</span>
                <Badge>{SCHEDULE_LABELS[item.schedule] ?? item.schedule}</Badge>
                <Badge>{item.format.toUpperCase()}</Badge>
                {item.is_active ? (
                  <Badge>运行中</Badge>
                ) : (
                  <Badge>已暂停</Badge>
                )}
                {item.last_status && <span className="text-xs text-neutral-500">{item.last_status}</span>}
              </div>
              <div className="flex items-center gap-1">
                <Button variant="ghost" onClick={() => handleRun(item.id)} title="立即运行">
                  <Play className="h-4 w-4" />
                </Button>
                <Button variant="ghost" onClick={() => handleToggle(item)} title={item.is_active ? "暂停" : "启用"}>
                  {item.is_active ? "暂停" : "启用"}
                </Button>
                <Button variant="ghost" onClick={() => handleDelete(item.id)} title="删除">
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="border border-neutral-800 rounded-xl p-4 space-y-3">
        <h4 className="font-medium text-sm flex items-center gap-2">
          <Plus className="h-4 w-4" /> 新建定时报告
        </h4>
        <input
          className="w-full bg-neutral-900 border border-neutral-700 rounded-lg px-3 py-2 text-sm"
          placeholder="报告名称（如：每周模型质量报告）"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <div className="flex flex-wrap gap-2">
          <select
            className="bg-neutral-900 border border-neutral-700 rounded-lg px-3 py-2 text-sm"
            value={schedule}
            onChange={(e) => setSchedule(e.target.value as "daily" | "weekly" | "monthly")}
          >
            <option value="daily">每日</option>
            <option value="weekly">每周</option>
            <option value="monthly">每月</option>
          </select>
          <select
            className="bg-neutral-900 border border-neutral-700 rounded-lg px-3 py-2 text-sm"
            value={format}
            onChange={(e) => setFormat(e.target.value as "md" | "html" | "pdf")}
          >
            <option value="md">Markdown</option>
            <option value="html">HTML</option>
            <option value="pdf">PDF</option>
          </select>
        </div>
        <div className="max-h-40 overflow-y-auto border border-neutral-800 rounded-lg p-2 space-y-1">
          {experiments.length === 0 && (
            <p className="text-xs text-neutral-500">暂无已完成的实验可勾选</p>
          )}
          {experiments.map((exp) => (
            <label key={exp.id} className="flex items-center gap-2 text-sm cursor-pointer">
              <input
                type="checkbox"
                checked={checked.has(exp.id)}
                onChange={() =>
                  setChecked((s) => {
                    const n = new Set(s);
                    if (n.has(exp.id)) n.delete(exp.id);
                    else n.add(exp.id);
                    return n;
                  })
                }
              />
              <span className="truncate">{exp.name}</span>
            </label>
          ))}
        </div>
        <Button onClick={handleCreate} disabled={busy}>
          <Plus className="h-4 w-4 mr-1" /> 创建
        </Button>
      </div>
    </Card>
  );
}
