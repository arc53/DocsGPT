import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../../api/services/userService';
import Spinner from '../../components/Spinner';
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

/** Status pill tones. The theme has no success or warning token yet. */
const STATUS_TONE: Record<string, string> = {
  ok: 'bg-muted text-foreground',
  error: 'bg-destructive/10 text-destructive',
  paused: 'bg-primary/10 text-primary',
  cancelled: 'bg-muted text-muted-foreground',
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
  }, [traceRef?.field, traceRef?.value, agentId, token]);

  return (
    <Sheet open={traceRef !== null} onOpenChange={(open) => !open && onClose()}>
      {/* The waterfall speaks for itself: the title is for screen readers
          only, and there is no description to announce. */}
      <SheetContent
        side="right"
        title={t('settings.logs.trace.title')}
        aria-describedby={undefined}
        className="w-full overflow-y-auto sm:max-w-3xl"
      >
        <div className="flex flex-col gap-8 px-4 pt-4 pb-6">
          {loading && (
            <div className="flex justify-center py-10">
              <Spinner />
            </div>
          )}
          {!loading && failed && (
            <p className="text-destructive text-sm">
              {t('settings.logs.trace.failed')}
            </p>
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
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                    STATUS_TONE[trace.status] ?? STATUS_TONE.cancelled
                  }`}
                >
                  {t(
                    `settings.logs.trace.status.${trace.status}`,
                    trace.status,
                  )}
                </span>
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
