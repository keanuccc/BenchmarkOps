"use client";

import { Button } from "@/components/ui";

/**
 * Minimal pagination bar for the list pages: shows the total row count and
 * prev/next controls. Renders nothing when the list is empty.
 */
export function PaginationBar({
  total,
  page,
  pageSize,
  onChange,
}: {
  total: number;
  page: number;
  pageSize: number;
  onChange: (page: number) => void;
}) {
  if (total <= 0) return null;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div
      className="mt-4 flex items-center justify-between gap-3 border-t pt-3"
      style={{ borderColor: "var(--ocd-border-soft)" }}
    >
      <span className="text-xs text-[var(--ocd-text-faint)]">共 {total} 条</span>
      <div className="flex items-center gap-2">
        <Button
          variant="secondary"
          disabled={page <= 1}
          onClick={() => onChange(page - 1)}
        >
          上一页
        </Button>
        <span className="text-xs tabular-nums text-[var(--ocd-text-muted)]">
          {page} / {pages}
        </span>
        <Button
          variant="secondary"
          disabled={page >= pages}
          onClick={() => onChange(page + 1)}
        >
          下一页
        </Button>
      </div>
    </div>
  );
}
