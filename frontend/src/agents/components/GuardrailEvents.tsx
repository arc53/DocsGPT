import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
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
import SkeletonLoader from '../../components/SkeletonLoader';
import { LoadMoreStatus } from '../../components/ui/load-more-status';
import { useLoadMore, type LoadMorePage } from '../../hooks/useLoadMore';
import { selectToken } from '../../preferences/preferenceSlice';
import { formatDateTime } from '../../utils/dateTimeUtils';
import { GuardrailEvent, GuardrailSummary } from '../types';

/** Decisions per request; older ones load as the table's end scrolls into view. */
const PAGE_SIZE = 50;
const WINDOWS = [7, 30, 90];

const STAGE_KEYS: Record<string, string> = {
  input: 'agents.form.guardrails.stages.input',
  retrieval: 'agents.form.guardrails.stages.retrieval',
  tool_result: 'agents.form.guardrails.stages.toolResult',
  output: 'agents.form.guardrails.stages.output',
};

const ACTION_KEYS: Record<string, string> = {
  flag: 'agents.form.guardrails.actions.flag',
  redact: 'agents.form.guardrails.actions.redact',
  block: 'agents.form.guardrails.actions.block',
};

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
              className="w-[150px]"
              size="field"
              shape="pill"
              data-testid="guardrail-events-window"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {WINDOWS.map((window) => (
                <SelectItem key={window} value={String(window)}>
                  {t('agents.guardrailEvents.lastDays', { count: window })}
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
            className="w-[170px]"
            size="field"
            shape="pill"
            data-testid="guardrail-events-check-filter"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
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
            className="w-[170px]"
            size="field"
            shape="pill"
            data-testid="guardrail-events-outcome-filter"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
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

      <div className="border-border bg-card mt-3 w-full overflow-hidden rounded-xl border">
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
            <p
              className="text-muted-foreground p-4 text-sm"
              data-testid="guardrail-events-empty"
            >
              {filtered
                ? t('agents.guardrailEvents.emptyForFilter')
                : t('agents.guardrailEvents.empty')}
            </p>
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
                    <TableCell className="text-muted-foreground">
                      {event.detail || '—'}
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
      </div>
    </div>
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
