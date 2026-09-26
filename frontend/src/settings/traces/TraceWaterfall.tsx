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

import { Button } from '../../components/ui/button';
import { EmptyState } from '../../components/ui/empty-state';
import { IconButton } from '../../components/ui/icon-button';
import { cn } from '../../lib/utils';
import { Trace, TraceSpan } from '../types';
import TraceSpanDetails from './TraceSpanDetails';
import {
  barGeometry,
  buildSpanRows,
  formatDurationMs,
  spanHeadline,
  traceTotalMs,
} from './traceUtils';

/**
 * Icon per span kind, and one of the five chart series per group of kinds:
 * the agent and its steps, model calls, tool calls, retrieval (with its
 * embedding, per-source search and rerank), and guardrails.
 */
const KIND_STYLE: Record<string, { icon: React.ElementType; bar: string }> = {
  agent: { icon: Bot, bar: 'bg-chart-1' },
  step: { icon: ListTree, bar: 'bg-chart-1' },
  llm: { icon: Brain, bar: 'bg-chart-2' },
  tool: { icon: Wrench, bar: 'bg-chart-3' },
  retrieval: { icon: Search, bar: 'bg-chart-4' },
  search: { icon: Database, bar: 'bg-chart-4' },
  embedding: { icon: Binary, bar: 'bg-chart-4' },
  rerank: { icon: ListFilter, bar: 'bg-chart-4' },
  guardrail: { icon: ShieldCheck, bar: 'bg-chart-5' },
};

const INACTIVE_STATUSES = ['cancelled', 'pending', 'denied', 'skipped'];

function kindStyle(span: TraceSpan) {
  return KIND_STYLE[span.kind] ?? KIND_STYLE.step;
}

function barClass(span: TraceSpan): string {
  if (span.status === 'error') return 'bg-destructive';
  if (INACTIVE_STATUSES.includes(span.status)) return 'bg-muted-foreground/40';
  return kindStyle(span).bar;
}

/** Scale ticks: 0, a quarter, half, three quarters and the full duration. */
const SCALE_TICKS = [
  { at: 0, className: 'left-0' },
  { at: 0.25, className: 'left-1/4 -translate-x-1/2' },
  { at: 0.5, className: 'left-1/2 -translate-x-1/2' },
  { at: 0.75, className: 'left-3/4 -translate-x-1/2' },
  { at: 1, className: 'right-0' },
];

/** Indent per nesting level, in rem. */
const INDENT_REM = 0.875;

/** A waterfall of one trace's spans; select a row for its details. */
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

  const toggleSelected = (id: string) =>
    setSelectedId((current) => (current === id ? null : id));

  if (!rows.length) {
    return (
      <EmptyState
        size="xs"
        illustration="none"
        title={t('settings.logs.trace.noSpans')}
      />
    );
  }

  return (
    <div className="flex flex-col gap-0.5" role="tree">
      <div className="text-muted-foreground grid grid-cols-9 gap-3 pb-1 text-xs">
        <span className="col-span-5">{t('settings.logs.trace.step')}</span>
        <div className="relative col-span-4 h-4">
          {SCALE_TICKS.map((tick) => (
            <span
              key={tick.at}
              className={cn(
                'absolute top-0 whitespace-nowrap tabular-nums',
                tick.className,
              )}
            >
              {tick.at === 0 ? '0' : formatDurationMs(totalMs * tick.at)}
            </span>
          ))}
        </div>
      </div>
      {visibleRows.map(({ span, depth, hasChildren }) => {
        const Icon = kindStyle(span).icon;
        const { left, width } = barGeometry(span, totalMs);
        const selected = selectedId === span.id;
        const headline = spanHeadline(span, t);
        const isCollapsed = collapsed.has(span.id);
        const geometry = {
          '--trace-indent': `${depth * INDENT_REM}rem`,
          '--trace-bar-left': `${left}%`,
          '--trace-bar-width': `${width}%`,
        } as React.CSSProperties;
        return (
          <div
            key={span.id}
            role="treeitem"
            aria-level={depth + 1}
            aria-selected={selected}
            aria-expanded={hasChildren ? !isCollapsed : undefined}
            style={geometry}
          >
            <div
              className={cn(
                'grid grid-cols-9 items-center gap-3 rounded-md',
                selected && 'bg-accent',
              )}
            >
              <div className="col-span-5 flex min-w-0 items-center pl-(--trace-indent)">
                {hasChildren ? (
                  <IconButton
                    label={t('settings.logs.trace.toggleChildren')}
                    variant="ghost"
                    size="icon-sm"
                    aria-expanded={!isCollapsed}
                    onClick={() => toggleCollapsed(span.id)}
                  >
                    <ChevronRight
                      aria-hidden
                      className={cn(
                        'text-muted-foreground transition-transform duration-200',
                        !isCollapsed && 'rotate-90',
                      )}
                    />
                  </IconButton>
                ) : (
                  <span className="size-8 shrink-0" />
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  className="min-w-0 flex-1 justify-start"
                  aria-pressed={selected}
                  onClick={() => toggleSelected(span.id)}
                >
                  <Icon
                    className={cn(
                      'size-3.5',
                      span.status === 'error'
                        ? 'text-destructive'
                        : 'text-muted-foreground',
                    )}
                    aria-label={t(
                      `settings.logs.trace.kinds.${span.kind}`,
                      span.kind,
                    )}
                  />
                  <span className="truncate font-normal" title={span.name}>
                    {span.name}
                  </span>
                  {headline && (
                    <span className="text-muted-foreground truncate text-xs font-normal">
                      {headline}
                    </span>
                  )}
                  <span className="text-muted-foreground ml-auto shrink-0 pl-2 text-xs font-normal tabular-nums">
                    {formatDurationMs(span.duration_ms)}
                  </span>
                </Button>
              </div>
              {/* Mouse shortcut to the row's button; keyboard users use the button. */}
              <div
                aria-hidden="true"
                onClick={() => toggleSelected(span.id)}
                className="bg-muted relative col-span-4 h-3 cursor-pointer rounded-sm"
              >
                <span
                  className={cn(
                    'absolute inset-y-0 left-(--trace-bar-left) w-(--trace-bar-width) rounded-sm',
                    barClass(span),
                  )}
                />
              </div>
            </div>
            {selected && (
              <div className="border-border mt-1 mb-2 ml-(--trace-indent) rounded-lg border p-3">
                <TraceSpanDetails span={span} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
