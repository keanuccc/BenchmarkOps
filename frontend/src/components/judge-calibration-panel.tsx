"use client";

import { useState } from "react";
import { Scale } from "lucide-react";
import { calibrateJudge, type JudgeCalibrationResponse } from "@/lib/api";
import { Button, Card, Spinner } from "@/components/ui";

function parseLabels(text: string): number[] {
  return text
    .split(/[,，\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => Number(s));
}

function pct(v: number) {
  return `${(v * 100).toFixed(1)}%`;
}

export function JudgeCalibrationPanel() {
  const [gold, setGold] = useState("");
  const [judgeA, setJudgeA] = useState("");
  const [judgeB, setJudgeB] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<JudgeCalibrationResponse | null>(null);

  async function run() {
    setError(null);
    setResult(null);
    const goldLabels = parseLabels(gold);
    const judgeLabels = parseLabels(judgeA);
    const judgeBLabels = parseLabels(judgeB);
    if (goldLabels.length === 0 || judgeLabels.length === 0) {
      setError("请至少填写黄金标注与 Judge 判断（逗号分隔的 0/1）");
      return;
    }
    if (goldLabels.length !== judgeLabels.length) {
      setError("黄金标注与 Judge 判断的数量必须一致");
      return;
    }
    if (judgeBLabels.length > 0 && judgeBLabels.length !== judgeLabels.length) {
      setError("Judge B 与 Judge A 的数量必须一致");
      return;
    }
    setBusy(true);
    try {
      const r = await calibrateJudge({
        gold_labels: goldLabels,
        judge_labels: judgeLabels,
        judge_b_labels: judgeBLabels.length > 0 ? judgeBLabels : undefined,
      });
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : "校准失败");
    } finally {
      setBusy(false);
    }
  }

  const c = result?.calibration;
  const a = result?.agreement;

  return (
    <Card className="overflow-hidden p-5">
      <div className="mb-4 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.16em] text-[var(--ocd-text-muted)]">
        <Scale size={15} className="text-[var(--ocd-accent)]" />
        LLM-judge 校准
        <span className="ml-auto font-mono text-[10px] normal-case tracking-normal text-[var(--ocd-text-faint)]">
          gold set 指标 + 一致性 kappa
        </span>
      </div>

      <div className="grid gap-3">
        <div>
          <label className="mb-1 block text-xs text-[var(--ocd-text-muted)]">
            黄金标注（gold，逗号分隔 0/1）
          </label>
          <textarea
            value={gold}
            onChange={(e) => setGold(e.target.value)}
            rows={2}
            placeholder="例如：1, 1, 0, 0, 1, 0"
            className="w-full rounded-xl border bg-[var(--ocd-bg)] px-3 py-2 font-mono text-sm text-[var(--ocd-text)]"
            style={{ borderColor: "var(--ocd-border)" }}
          />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-xs text-[var(--ocd-text-muted)]">
              Judge A 判断
            </label>
            <textarea
              value={judgeA}
              onChange={(e) => setJudgeA(e.target.value)}
              rows={2}
              placeholder="1, 1, 0, 1, 1, 0"
              className="w-full rounded-xl border bg-[var(--ocd-bg)] px-3 py-2 font-mono text-sm text-[var(--ocd-text)]"
              style={{ borderColor: "var(--ocd-border)" }}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-[var(--ocd-text-muted)]">
              Judge B 判断（可选，测一致性）
            </label>
            <textarea
              value={judgeB}
              onChange={(e) => setJudgeB(e.target.value)}
              rows={2}
              placeholder="1, 0, 0, 1, 1, 0"
              className="w-full rounded-xl border bg-[var(--ocd-bg)] px-3 py-2 font-mono text-sm text-[var(--ocd-text)]"
              style={{ borderColor: "var(--ocd-border)" }}
            />
          </div>
        </div>

        <div>
          <Button onClick={run} disabled={busy}>
            {busy ? <Spinner size={14} /> : <Scale size={15} />} 运行校准
          </Button>
        </div>

        {error && <p className="text-sm text-[var(--ocd-bad)]">{error}</p>}
      </div>

      {c && (
        <div className="mt-5 grid gap-3 sm:grid-cols-4">
          {[
            { label: "Accuracy", value: pct(c.accuracy) },
            { label: "Precision", value: pct(c.precision) },
            { label: "Recall", value: pct(c.recall) },
            { label: "F1", value: pct(c.f1) },
          ].map((m) => (
            <div
              key={m.label}
              className="rounded-xl border border-[var(--ocd-border-soft)] bg-[var(--ocd-surface-2)] p-3"
            >
              <p className="text-[10px] uppercase tracking-wider text-[var(--ocd-text-faint)]">
                {m.label}
              </p>
              <p className="mt-1 text-xl font-semibold tabular-nums text-[var(--ocd-accent)]">
                {m.value}
              </p>
            </div>
          ))}
          <div className="mt-1 font-mono text-xs text-[var(--ocd-text-muted)]">
            混淆矩阵：TP {c.confusion.tp} · FP {c.confusion.fp} · TN{" "}
            {c.confusion.tn} · FN {c.confusion.fn}
          </div>
        </div>
      )}

      {a && (
        <div className="mt-4 rounded-xl border border-[var(--ocd-border-soft)] bg-[var(--ocd-surface-2)] p-3 text-sm">
          <p className="text-[var(--ocd-text-muted)]">
            Judge A vs B 一致率{" "}
            <span className="font-semibold tabular-nums text-[var(--ocd-text)]">
              {pct(a.agreement_rate)}
            </span>{" "}
            · Cohen&apos;s kappa{" "}
            <span className="font-semibold tabular-nums text-[var(--ocd-text)]">
              {a.cohen_kappa.toFixed(4)}
            </span>
          </p>
        </div>
      )}
    </Card>
  );
}
