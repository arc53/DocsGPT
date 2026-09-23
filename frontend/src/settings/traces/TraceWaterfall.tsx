import {
  Binary,
  Bot,
  Brain,
  ChevronRight,
  Database,
  ListFilter,
  ListTree,
  Search,
  ShieldCheck,
  Wrench,
} from 'lucide-react';
import React, { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Trace, TraceSpan } from '../types';
import TraceSpanDetails from './TraceSpanDetails';
import {
  barGeometry,
  buildSpanRows,
  formatDurationMs,
  spanHeadline,
  traceTotalMs,
} from './traceUtils';

const KIND_STYLE: Record<string, { icon: React.ElementType; bar: string }> = {
  agent: { icon: Bot, bar: 'bg-violet-500' },
  llm: { icon: Brain, bar: 'bg-sky-500' },
  tool: { icon: Wrench, bar: 'bg-amber-500' },
  retrieval: { icon: Search, bar: 'bg-emerald-500' },
  search: { icon: Database, bar: 'bg-emerald-400' },
  embedding: { icon: Binary, bar: 'bg-teal-500' },
  rerank: { icon: ListFilter, bar: 'bg-lime-500' },
  guardrail: { icon: ShieldCheck, bar: 'bg-rose-400' },
  step: { icon: ListTree, bar: 'bg-indigo-400' },
};

function barClass(span: TraceSpan): string {
  if (span.status === 'error') return 'bg-red-500';
  if (['cancelled', 'pending', 'denied', 'skipped'].includes(span.status))
    return 'bg-gray-400 dark:bg-gray-500';
  return (KIND_STYLE[span.kind] ?? KIND_STYLE.step).bar;
}

const SCALE_STEPS = [0, 0.25, 0.5, 0.75, 1];
const INDENT_PX = 14;

/** A waterfall of one trace's spans; click a row for its details. */
export default function TraceWaterfall({ trace }: { trace: Trace }) {
  const { t } = useTranslation();
  const rows = useMemo(() => buildSpanRows(trace.spans), [trace.spans]);
  const totalMs = traceTotalMs(trace.duration_ms, trace.spans);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const visibleRows = useMemo(() => {
    const out: typeof rows = [];
    let hiddenBelowDepth: number | null = null;
    for (const row of rows) {
      if (hiddenBelowDepth !== null && row.depth > hiddenBelowDepth) continue;
      hiddenBelowDepth = collapsed.has(row.span.id) ? row.depth : null;
      out.push(row);
    }
    return out;
  }, [rows, collapsed]);

  const toggleCollapsed = (id: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  if (!rows.length) {
    return (
      <p className="text-muted-foreground py-4 text-center text-xs">
        {t('settings.logs.trace.noSpans')}
      </p>
    );
  }

  return (
    <div className="flex flex-col text-xs" role="tree">
      <div className="grid grid-cols-[minmax(0,5fr)_minmax(0,4fr)] gap-3 pb-1">
        <span className="text-muted-foreground">
          {t('settings.logs.trace.step')}
        </span>
        <div className="text-muted-foreground relative h-4">
          {SCALE_STEPS.map((step) => (
            <span
              key={step}
              className="absolute top-0 -translate-x-1/2 whitespace-nowrap tabular-nums first:translate-x-0 last:-translate-x-full"
              style={{ left: `${step * 100}%` }}
            >
              {step === 0 ? '0' : formatDurationMs(totalMs * step)}
            </span>
          ))}
        </div>
      </div>
      {visibleRows.map(({ span, depth, hasChildren }) => {
        const Icon = (KIND_STYLE[span.kind] ?? KIND_STYLE.step).icon;
        const { left, width } = barGeometry(span, totalMs);
        const selected = selectedId === span.id;
        const headline = spanHeadline(span, t);
        return (
          <div key={span.id} role="treeitem" aria-selected={selected}>
            <div
              role="button"
              tabIndex={0}
              onClick={() => setSelectedId(selected ? null : span.id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  setSelectedId(selected ? null : span.id);
                }
              }}
              className={`grid w-full cursor-pointer grid-cols-[minmax(0,5fr)_minmax(0,4fr)] items-center gap-3 rounded-md py-1 text-left ${
                selected
                  ? 'bg-muted dark:bg-white/10'
                  : 'hover:bg-muted/60 dark:hover:bg-white/5'
              }`}
            >
              <span
                className="flex min-w-0 items-center gap-1.5"
                style={{ paddingLeft: depth * INDENT_PX }}
              >
                {hasChildren ? (
                  <button
                    type="button"
                    aria-label={t('settings.logs.trace.toggleChildren')}
                    aria-expanded={!collapsed.has(span.id)}
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleCollapsed(span.id);
                    }}
                    onKeyDown={(e) => e.stopPropagation()}
                    className="text-muted-foreground hover:text-foreground shrink-0"
                  >
                    <ChevronRight
                      className={`size-3 transition-transform ${collapsed.has(span.id) ? '' : 'rotate-90'}`}
                    />
                  </button>
                ) : (
                  <span className="w-3 shrink-0" />
                )}
                <Icon
                  className={`size-3.5 shrink-0 ${span.status === 'error' ? 'text-red-500' : 'text-muted-foreground'}`}
                  aria-label={t(
                    `settings.logs.trace.kinds.${span.kind}`,
                    span.kind,
                  )}
                />
                <span className="text-foreground truncate" title={span.name}>
                  {span.name}
                </span>
                {headline && (
                  <span className="text-muted-foreground shrink-0 truncate">
                    {headline}
                  </span>
                )}
                <span className="text-muted-foreground ml-auto shrink-0 pl-2 tabular-nums">
                  {formatDurationMs(span.duration_ms)}
                </span>
              </span>
              <span className="bg-muted/60 relative h-3 rounded-sm dark:bg-white/5">
                <span
                  className={`absolute inset-y-0 rounded-sm ${barClass(span)}`}
                  style={{ left: `${left}%`, width: `${width}%` }}
                  title={`${span.name} · ${formatDurationMs(span.duration_ms)}`}
                />
              </span>
            </div>
            {selected && (
              <div
                className="border-border my-1 rounded-lg border px-3 py-2"
                style={{ marginLeft: depth * INDENT_PX }}
              >
                <TraceSpanDetails span={span} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
