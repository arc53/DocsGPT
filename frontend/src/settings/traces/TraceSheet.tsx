import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../../api/services/userService';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { LoadingState } from '@/components/ui/loading-state';
import { Sheet, SheetContent } from '../../components/ui/sheet';
import { selectToken } from '../../preferences/preferenceSlice';
import { formatDateTime } from '../../utils/dateTimeUtils';
import { Trace, TraceRef } from '../types';
import TraceChips from './TraceChips';
import TraceWaterfall from './TraceWaterfall';

type TraceSheetProps = {
  traceRef: TraceRef | null;
  agentId?: string;
  onClose: () => void;
};

/** Status → Badge variant. Unknown statuses (pending, denied, skipped) fall back to `neutral`. */
const STATUS_VARIANT: Record<
  string,
  React.ComponentProps<typeof Badge>['variant']
> = {
  ok: 'neutral',
  error: 'destructive',
  paused: 'default',
  cancelled: 'neutral',
};

/**
 * Side panel showing the execution trace(s) behind one Logs row. A chat turn
 * paused for tool approval has one trace per round, shown in order.
 */
export default function TraceSheet({
  traceRef,
  agentId,
  onClose,
}: TraceSheetProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const [traces, setTraces] = useState<Trace[]>([]);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  // Bumped by Retry to re-run the fetch for the same trace.
  const [reloadKey, setReloadKey] = useState(0);
  // The sheet is opened from a Logs row, not a SheetTrigger, so Radix has no
  // trigger to return focus to on close; remember what had focus instead.
  const returnFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!traceRef) return;
    const controller = new AbortController();
    setLoading(true);
    setFailed(false);
    setTraces([]);
    const params: Record<string, string> = {
      [traceRef.field]: traceRef.value,
    };
    if (agentId) params.api_key_id = agentId;
    userService
      .getTraces(params, token, controller.signal)
      .then(async (response: Response) => {
        if (!response.ok) throw new Error('Failed to load traces');
        const data = await response.json();
        setTraces(data.traces ?? []);
      })
      .catch((error: unknown) => {
        if ((error as Error)?.name === 'AbortError') return;
        console.error(error);
        setFailed(true);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [traceRef?.field, traceRef?.value, agentId, token, reloadKey]);

  return (
    <Sheet open={traceRef !== null} onOpenChange={(open) => !open && onClose()}>
      {/* The waterfall speaks for itself: the title is for screen readers
          only, and there is no description to announce. */}
      <SheetContent
        side="right"
        title={t('settings.logs.trace.title')}
        aria-describedby={undefined}
        onOpenAutoFocus={() => {
          returnFocusRef.current =
            document.activeElement instanceof HTMLElement
              ? document.activeElement
              : null;
        }}
        onCloseAutoFocus={(event) => {
          const target = returnFocusRef.current;
          returnFocusRef.current = null;
          if (target?.isConnected) {
            event.preventDefault();
            target.focus();
          }
        }}
        className="w-full overflow-y-auto sm:max-w-3xl"
      >
        <div className="flex flex-col gap-6 px-4 pt-4 pb-6">
          {loading && <LoadingState fill="block" />}
          {!loading && failed && (
            <EmptyState
              tone="destructive"
              size="sm"
              illustration="none"
              title={t('settings.logs.trace.failed')}
              action={
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setReloadKey((key) => key + 1)}
                >
                  {t('retry')}
                </Button>
              }
            />
          )}
          {!loading && !failed && traces.length === 0 && (
            <p className="text-muted-foreground text-sm">
              {t('settings.logs.trace.empty')}
            </p>
          )}
          {traces.map((trace, index) => (
            <section key={trace.id} className="flex flex-col gap-3">
              {/* Right padding keeps the first row clear of the close button. */}
              <div className="flex flex-wrap items-center gap-2 pr-8">
                {traces.length > 1 && (
                  <span className="text-foreground text-sm font-medium">
                    {t('settings.logs.trace.round', { n: index + 1 })}
                  </span>
                )}
                <span className="text-muted-foreground text-xs">
                  {t(
                    `settings.logs.trace.sources.${trace.source}`,
                    trace.source,
                  )}
                </span>
                <span className="text-muted-foreground text-xs">
                  {formatDateTime(trace.started_at)}
                </span>
                <Badge variant={STATUS_VARIANT[trace.status] ?? 'neutral'}>
                  {t(
                    `settings.logs.trace.status.${trace.status}`,
                    trace.status,
                  )}
                </Badge>
              </div>
              <TraceChips
                durationMs={trace.duration_ms}
                counts={trace.summary ?? {}}
              />
              {trace.dropped_spans > 0 && (
                <p className="text-muted-foreground text-xs">
                  {t('settings.logs.trace.droppedSpans', {
                    count: trace.dropped_spans,
                  })}
                </p>
              )}
              <TraceWaterfall trace={trace} />
            </section>
          ))}
        </div>
      </SheetContent>
    </Sheet>
  );
}
