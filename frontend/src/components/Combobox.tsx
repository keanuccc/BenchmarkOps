"use client";

import { useState, useRef, useEffect, useCallback } from "react";

/**
 * Combobox — searchable dropdown with keyboard navigation.
 * Zero external dependencies. Renders as a controlled input + floating list.
 */
export function Combobox<T extends { id: string; label: string; subtitle?: string }>({
  items,
  value,
  onChange,
  placeholder = "搜索…",
  disabled = false,
}: {
  items: T[];
  value: string;
  onChange: (item: T) => void;
  placeholder?: string;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const wrapperRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const highlightedIdx = useRef(0);

  // Filter items by query
  const filtered = items.filter(
    (item) =>
      !query ||
      item.label.toLowerCase().includes(query.toLowerCase()) ||
      item.subtitle?.toLowerCase().includes(query.toLowerCase()),
  );

  // Reset highlight when filter changes
  useEffect(() => {
    highlightedIdx.current = 0;
  }, [filtered.length]);

  // Close on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  function select(item: T) {
    setQuery("");
    onChange(item);
    setOpen(false);
    inputRef.current?.blur();
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (!open) {
      if (e.key === "Enter" || e.key === "ArrowDown") {
        e.preventDefault();
        setOpen(true);
      }
      return;
    }
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        highlightedIdx.current = Math.min(highlightedIdx.current + 1, filtered.length - 1);
        break;
      case "ArrowUp":
        e.preventDefault();
        highlightedIdx.current = Math.max(highlightedIdx.current - 1, 0);
        break;
      case "Enter":
        if (filtered[highlightedIdx.current]) {
          e.preventDefault();
          select(filtered[highlightedIdx.current]);
        }
        break;
      case "Escape":
        setOpen(false);
        break;
    }
  }

  const selectedItem = items.find((i) => i.id === value);

  return (
    <div ref={wrapperRef} className="relative">
      <div
        className={`flex items-center gap-2 rounded-lg bg-[var(--ocd-bg)] px-3 py-2 text-sm text-[var(--ocd-text)] ${
          open ? "ring-1" : ""
        }`}
        style={{ borderColor: "var(--ocd-border)", borderWidth: 1 }}
        onClick={() => !disabled && setOpen(true)}
      >
        <input
          ref={inputRef}
          type="text"
          className="w-full bg-transparent outline-none placeholder:text-[var(--ocd-text-faint)]"
          placeholder={selectedItem ? "" : placeholder}
          value={selectedItem ? selectedItem.label : query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onKeyDown={handleKeyDown}
          disabled={disabled}
        />
        {!selectedItem && (
          <svg className="h-4 w-4 shrink-0 opacity-40" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
        )}
      </div>

      {open && filtered.length > 0 && (
        <ul
          className="absolute z-50 mt-1 max-h-60 w-full overflow-y-auto rounded-lg border bg-[var(--ocd-surface)] shadow-lg"
          style={{ borderColor: "var(--ocd-border)" }}
        >
          {filtered.map((item, idx) => {
            const isHighlighted = idx === highlightedIdx.current;
            return (
              <li
                key={item.id}
                className={`cursor-pointer px-3 py-2 text-sm transition-colors ${
                  isHighlighted ? "bg-[var(--ocd-surface-2)]" : ""
                }`}
                onMouseDown={() => select(item)}
                onMouseEnter={() => {
                  highlightedIdx.current = idx;
                }}
              >
                <div className="font-medium">{item.label}</div>
                {item.subtitle && (
                  <div className="text-xs text-[var(--ocd-text-faint)]">{item.subtitle}</div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {open && filtered.length === 0 && (
        <div
          className="absolute z-50 mt-1 rounded-lg border bg-[var(--ocd-surface)] p-3 text-sm text-[var(--ocd-text-muted)]"
          style={{ borderColor: "var(--ocd-border)" }}
        >
          无匹配结果
        </div>
      )}
    </div>
  );
}
