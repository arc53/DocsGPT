import React from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { Progress } from '@/components/ui/progress';
import { SectionHeader } from '@/components/ui/section-header';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import StatCard from '@/components/StatCard';

import userService from '../../api/services/userService';
import { chunkFilePath } from '../../components/graph/graphCanvasUtils';
import SkeletonLoader from '../../components/SkeletonLoader';
import { LoadMoreStatus } from '../../components/ui/load-more-status';
import { useLoadMore, type LoadMorePage } from '../../hooks/useLoadMore';
import { showActionToast } from '../../notifications/actionToastSlice';
import { selectToken } from '../../preferences/preferenceSlice';
import { knowledgeLink } from '../../settings/knowledgeLink';
import { EMPTY_VALUE, formatDateTime } from '../../utils/dateTimeUtils';
import { GuardrailEvent, GuardrailSummary } from '../types';
import { ACTION_KEYS, STAGE_KEYS } from './GuardrailsSection';

/** Decisions per request; older ones load as the table's end scrolls into view. */
const PAGE_SIZE = 50;
/** The windows (days) and their labels, worded as the analytics select's. */
const WINDOWS = [
  [7, 'last7Days'],
  [30, 'last30Days'],
  [90, 'last90Days'],
] as const;

/** What an item-level verdict was about: a retrieved chunk, or an attached file. */
type ItemRef =
  | { kind: 'chunk'; sourceId: string; chunkKey: string }
  | { kind: 'attachment'; id: string };

/** Read `chunk:<source_id>:<chunk_key>` or `attachment:<id>`; null for anything else. */
export function parseItemRef(ref?: string | null): ItemRef | null {
  const chunk = /^chunk:([^:]+):([0-9a-f]{32})$/.exec(ref ?? '');
  if (chunk) return { kind: 'chunk', sourceId: chunk[1], chunkKey: chunk[2] };
  const attachment = /^attachment:(.+)$/.exec(ref ?? '');
  return attachment ? { kind: 'attachment', id: attachment[1] } : null;
}

/**
 * Colour by meaning, matching the status tokens used across the app: a block
 * is a refusal, a flag needs review, a redaction is informational.
 */
function actionTone(
  action: string,
  outcome: string,
): 'neutral' | 'destructive' | 'warning' | 'info' {
  if (outcome === 'not_evaluated') return 'neutral';
  if (action === 'block') return 'destructive';
  if (action === 'redact') return 'info';
  return 'warning';
}

type Props = { agentId?: string };

export default function GuardrailEvents({ agentId }: Props) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);

  const [summary, setSummary] = React.useState<GuardrailSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = React.useState(true);
  const [summaryError, setSummaryError] = React.useState(false);
  const [days, setDays] = React.useState(30);
  const [checkFilter, setCheckFilter] = React.useState('all');
  const [outcomeFilter, setOutcomeFilter] = React.useState('all');
  // Bumped by Retry to re-run both fetches.
  const [reloadKey, setReloadKey] = React.useState(0);

  React.useEffect(() => {
    if (!agentId) return;
    let cancelled = false;
    setSummaryLoading(true);
    setSummaryError(false);
    userService
      .getGuardrailSummary(token, agentId, days)
      .then((res: Response) => res.json())
      .then((body: GuardrailSummary & { success?: boolean }) => {
        if (cancelled) return;
        if (!body?.success) setSummaryError(true);
        else setSummary(body);
      })
      .catch(() => {
        if (!cancelled) setSummaryError(true);
      })
      .finally(() => {
        if (!cancelled) setSummaryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [agentId, token, days, reloadKey]);

  // The window and both filters are applied by the server, so every page
  // is filtered and scrolling reaches every match.
  const check = checkFilter === 'all' ? undefined : checkFilter;
  const outcome = outcomeFilter === 'all' ? undefined : outcomeFilter;
  const feed = useLoadMore<GuardrailEvent, number>({
    getKey: (event) => String(event.id),
    resetKey: [agentId, days, check, outcome, reloadKey].join('|'),
    load: async (offset): Promise<LoadMorePage<GuardrailEvent, number>> => {
      if (!agentId) return { items: [], next: null };
      const from = offset ?? 0;
      const res = await userService.getGuardrailEvents(
        agentId,
        token,
        PAGE_SIZE,
        from,
        { days, check, outcome },
      );
      const body = await res.json();
      if (!body?.success) throw new Error('guardrail events');
      const page: GuardrailEvent[] = body.events ?? [];
      return {
        items: page,
        next: page.length < PAGE_SIZE ? null : from + page.length,
      };
    },
  });
  const events = feed.items;
  const firstPage = feed.loading && events.length === 0;
  const loading = summaryLoading || firstPage;
  const error =
    summaryError || (feed.error && events.length === 0)
      ? t('agents.guardrailEvents.loadError')
      : null;
  const filtered = check !== undefined || outcome !== undefined;

  // Every check that fired in the window, from the summary, not only the
  // ones on the loaded page; the picked one stays listed.
  const checkNames = React.useMemo(() => {
    const names = new Set(summary?.breakdown.map((row) => row.check_name));
    if (check) names.add(check);
    return Array.from(names).sort();
  }, [summary, check]);

  const totals = summary?.totals;
  const tableHeadingId = React.useId();

  return (
    <div className="mt-8" data-testid="guardrail-events">
      <SectionHeader
        title={t('agents.guardrailEvents.heading')}
        description={t('agents.guardrailEvents.description')}
        actions={
          <Select
            value={String(days)}
            onValueChange={(value) => setDays(Number(value))}
          >
            <SelectTrigger
              className="min-w-[125px]"
              size="field"
              shape="pill"
              aria-label={t('activity.history.periodFilter')}
              data-testid="guardrail-events-window"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent fit>
              {WINDOWS.map(([window, labelKey]) => (
                <SelectItem key={window} value={String(window)}>
                  {t(`settings.analytics.filterOptions.${labelKey}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        }
      />

      {/* Blocked / flagged / redacted / not-evaluated are four different
          product problems; a single "violations" number hides which one you
          have. Not-evaluated in particular means a check silently stopped
          working. */}
      <div className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard
          label={t('agents.guardrailEvents.blocked')}
          value={totals?.blocked ?? 0}
          loading={loading}
          data-testid="guardrail-stat-blocked"
          valueTone="destructive"
        />
        <StatCard
          label={t('agents.guardrailEvents.redacted')}
          value={totals?.redacted ?? 0}
          loading={loading}
          data-testid="guardrail-stat-redacted"
          valueTone="info"
        />
        <StatCard
          label={t('agents.guardrailEvents.flagged')}
          value={totals?.flagged ?? 0}
          loading={loading}
          data-testid="guardrail-stat-flagged"
          valueTone="warning"
        />
        <StatCard
          label={t('agents.guardrailEvents.notEvaluated')}
          value={totals?.not_evaluated ?? 0}
          loading={loading}
          data-testid="guardrail-stat-not-evaluated"
          valueTone="muted"
          hint={t('agents.guardrailEvents.notEvaluatedHint')}
        />
      </div>

      {summary && summary.breakdown.length > 0 && <ByCheck summary={summary} />}

      <SectionHeader
        as="h3"
        size="xs"
        id={tableHeadingId}
        title={t('agents.guardrailEvents.tableHeader')}
        className="mt-6"
      />
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Select value={checkFilter} onValueChange={setCheckFilter}>
          <SelectTrigger
            className="min-w-[170px]"
            size="field"
            shape="pill"
            aria-label={t('agents.guardrailEvents.check')}
            data-testid="guardrail-events-check-filter"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent fit>
            <SelectItem value="all">
              {t('agents.guardrailEvents.allChecks')}
            </SelectItem>
            {checkNames.map((name) => (
              <SelectItem key={name} value={name}>
                {name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={outcomeFilter} onValueChange={setOutcomeFilter}>
          <SelectTrigger
            className="min-w-[170px]"
            size="field"
            shape="pill"
            aria-label={t('agents.guardrailEvents.outcome')}
            data-testid="guardrail-events-outcome-filter"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent fit>
            <SelectItem value="all">
              {t('agents.guardrailEvents.allOutcomes')}
            </SelectItem>
            <SelectItem value="block">
              {t('agents.form.guardrails.actions.block')}
            </SelectItem>
            <SelectItem value="redact">
              {t('agents.form.guardrails.actions.redact')}
            </SelectItem>
            <SelectItem value="flag">
              {t('agents.form.guardrails.actions.flag')}
            </SelectItem>
            <SelectItem value="not_evaluated">
              {t('agents.guardrailEvents.notEvaluated')}
            </SelectItem>
          </SelectContent>
        </Select>
      </div>

      <Card
        variant="subtle"
        padding="none"
        className="mt-3 w-full gap-0 overflow-hidden"
      >
        <div className="scrollbar-overlay max-h-[45svh] overflow-y-auto">
          {loading ? (
            <div className="p-3">
              <SkeletonLoader count={3} />
            </div>
          ) : error ? (
            <EmptyState
              tone="destructive"
              size="sm"
              illustration="none"
              title={error}
              onRetry={() => setReloadKey((key) => key + 1)}
            />
          ) : events.length === 0 ? (
            <EmptyState
              size="sm"
              illustration="none"
              data-testid="guardrail-events-empty"
              title={
                filtered
                  ? t('agents.guardrailEvents.emptyForFilter')
                  : t('agents.guardrailEvents.empty')
              }
            />
          ) : (
            <Table aria-labelledby={tableHeadingId}>
              <TableHead>
                <TableRow>
                  <TableHeader>{t('agents.guardrailEvents.when')}</TableHeader>
                  <TableHeader>{t('agents.guardrailEvents.check')}</TableHeader>
                  <TableHeader>{t('agents.guardrailEvents.stage')}</TableHeader>
                  <TableHeader>
                    {t('agents.guardrailEvents.outcome')}
                  </TableHeader>
                  <TableHeader>{t('agents.guardrailEvents.score')}</TableHeader>
                  <TableHeader>
                    {t('agents.guardrailEvents.detail')}
                  </TableHeader>
                </TableRow>
              </TableHead>
              <TableBody data-testid="guardrail-events-rows">
                {events.map((event) => (
                  <TableRow key={event.id}>
                    <TableCell className="text-muted-foreground whitespace-nowrap">
                      {formatDateTime(event.created_at)}
                    </TableCell>
                    <TableCell>
                      <span className="font-medium">{event.check_name}</span>
                      {event.category && (
                        <span className="text-muted-foreground ml-1">
                          · {event.category}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {t(STAGE_KEYS[event.stage] ?? event.stage)}
                    </TableCell>
                    <TableCell>
                      <Badge variant={actionTone(event.action, event.outcome)}>
                        {event.outcome === 'not_evaluated'
                          ? t('agents.guardrailEvents.notEvaluated')
                          : t(ACTION_KEYS[event.action] ?? event.action)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground tabular-nums">
                      {typeof event.score === 'number'
                        ? event.score.toFixed(2)
                        : EMPTY_VALUE}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      <div className="flex flex-col items-start gap-1">
                        <span>{event.detail || EMPTY_VALUE}</span>
                        <ItemRefCell value={event.item_ref} />
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          <div ref={feed.sentinelRef} aria-hidden="true" className="h-px" />
        </div>
        {events.length >= PAGE_SIZE ? (
          <LoadMoreStatus
            loading={feed.loading}
            error={feed.error}
            done={feed.done}
            onRetry={feed.retry}
            divider
          />
        ) : null}
      </Card>
    </div>
  );
}

/**
 * The item an event is about: a link that opens the chunk in Knowledge
 * (found by its content key, as a citation is), or "Attached file".
 */
function ItemRefCell({ value }: { value?: string | null }) {
  const { t } = useTranslation();
  const ref = parseItemRef(value);
  if (!ref) return null;
  if (ref.kind === 'attachment')
    return (
      <span className="text-xs">
        {t('agents.guardrailEvents.attachedFile')}
      </span>
    );
  return <ChunkLink sourceId={ref.sourceId} chunkKey={ref.chunkKey} />;
}

function ChunkLink({
  sourceId,
  chunkKey,
}: {
  sourceId: string;
  chunkKey: string;
}) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const [opening, setOpening] = React.useState(false);

  const open = async () => {
    setOpening(true);
    try {
      const response = await userService.getSourceChunk(
        sourceId,
        chunkKey,
        token,
      );
      if (!response.ok) throw new Error('chunk lookup');
      const body = await response.json();
      const metadata = body.chunk?.metadata ?? {};
      navigate(
        knowledgeLink(
          body.source?.kind === 'wiki' && body.page_path
            ? { sourceId, wikiPage: body.page_path }
            : {
                sourceId,
                chunk: {
                  id: body.chunk.doc_id,
                  search: body.chunk.text ?? '',
                  path: chunkFilePath(metadata) || undefined,
                },
              },
        ),
      );
    } catch {
      dispatch(
        showActionToast({
          variant: 'destructive',
          message: t('agents.guardrailEvents.chunkUnavailable'),
        }),
      );
    } finally {
      setOpening(false);
    }
  };

  // A text-size link takes the type of the line it sits in.
  return (
    <span className="text-xs">
      <Button
        type="button"
        variant="link"
        size="text"
        loading={opening}
        onClick={open}
      >
        {t('agents.guardrailEvents.openChunk')}
      </Button>
    </span>
  );
}

/**
 * Per-check totals. The point is to see *which* control is firing: a rollout's
 * first week is spent finding the one that is over-triggering, and an
 * undifferentiated count cannot tell you that.
 */
function ByCheck({ summary }: { summary: GuardrailSummary }) {
  const { t } = useTranslation();
  const rows = React.useMemo(() => {
    const byCheck = new Map<string, number>();
    summary.breakdown.forEach((row) => {
      byCheck.set(
        row.check_name,
        (byCheck.get(row.check_name) ?? 0) + Number(row.total),
      );
    });
    return Array.from(byCheck.entries()).sort((a, b) => b[1] - a[1]);
  }, [summary]);

  const max = rows.length ? rows[0][1] : 0;
  if (!rows.length) return null;

  return (
    <div className="mt-4" data-testid="guardrail-by-check">
      <p className="text-muted-foreground mb-2 text-xs">
        {t('agents.guardrailEvents.byCheck')}
      </p>
      <div className="flex flex-col gap-1.5">
        {rows.map(([check, total]) => (
          <div key={check} className="flex items-center gap-3">
            <span className="w-32 shrink-0 truncate text-xs">{check}</span>
            <Progress
              className="flex-1"
              value={max ? (total / max) * 100 : 0}
            />
            <span className="text-muted-foreground w-10 shrink-0 text-right text-xs">
              {total}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
