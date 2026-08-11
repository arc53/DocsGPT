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

import userService from '../../api/services/userService';
import SkeletonLoader from '../../components/SkeletonLoader';
import { selectToken } from '../../preferences/preferenceSlice';
import { formatDateTime } from '../../utils/dateTimeUtils';
import { GuardrailEvent, GuardrailSummary } from '../types';

const PAGE_SIZE = 100;
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

/** Colour by consequence, so "we refused" reads differently from "we noticed". */
function actionTone(action: string, outcome: string): string {
  if (outcome === 'not_evaluated')
    return 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300';
  if (action === 'block')
    return 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300';
  if (action === 'redact')
    return 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300';
  return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300';
}

type Props = { agentId?: string };

export default function GuardrailEvents({ agentId }: Props) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);

  const [events, setEvents] = React.useState<GuardrailEvent[]>([]);
  const [summary, setSummary] = React.useState<GuardrailSummary | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [days, setDays] = React.useState(30);
  const [checkFilter, setCheckFilter] = React.useState('all');
  const [outcomeFilter, setOutcomeFilter] = React.useState('all');

  React.useEffect(() => {
    if (!agentId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);

    Promise.all([
      userService.getGuardrailEvents(agentId, token, PAGE_SIZE),
      userService.getGuardrailSummary(token, agentId, days),
    ])
      .then(async ([eventsRes, summaryRes]) => {
        if (cancelled) return;
        const eventsBody = await eventsRes.json();
        const summaryBody = await summaryRes.json();
        if (!eventsBody?.success || !summaryBody?.success) {
          setError(t('agents.guardrailEvents.loadError'));
          return;
        }
        setEvents(eventsBody.events ?? []);
        setSummary(summaryBody as GuardrailSummary);
      })
      .catch(() => {
        if (!cancelled) setError(t('agents.guardrailEvents.loadError'));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [agentId, token, days, t]);

  const checkNames = React.useMemo(
    () => Array.from(new Set(events.map((e) => e.check_name))).sort(),
    [events],
  );

  const visible = events.filter(
    (e) =>
      (checkFilter === 'all' || e.check_name === checkFilter) &&
      (outcomeFilter === 'all' ||
        (outcomeFilter === 'not_evaluated'
          ? e.outcome === 'not_evaluated'
          : e.outcome === 'triggered' && e.action === outcomeFilter)),
  );

  const totals = summary?.totals;

  return (
    <div className="mt-8 px-4" data-testid="guardrail-events">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">
            {t('agents.guardrailEvents.heading')}
          </h2>
          <p className="text-muted-foreground mt-1 text-xs">
            {t('agents.guardrailEvents.description')}
          </p>
        </div>
        <Select
          value={String(days)}
          onValueChange={(value) => setDays(Number(value))}
        >
          <SelectTrigger
            className="w-[150px] rounded-3xl px-5 py-3 text-sm"
            size="lg"
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
      </div>

      {/* Blocked / flagged / redacted / not-evaluated are four different
          product problems; a single "violations" number hides which one you
          have. Not-evaluated in particular means a check silently stopped
          working. */}
      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile
          label={t('agents.guardrailEvents.blocked')}
          value={totals?.blocked}
          loading={loading}
          testId="guardrail-stat-blocked"
          tone="text-red-700 dark:text-red-400"
        />
        <StatTile
          label={t('agents.guardrailEvents.redacted')}
          value={totals?.redacted}
          loading={loading}
          testId="guardrail-stat-redacted"
          tone="text-amber-700 dark:text-amber-400"
        />
        <StatTile
          label={t('agents.guardrailEvents.flagged')}
          value={totals?.flagged}
          loading={loading}
          testId="guardrail-stat-flagged"
          tone="text-emerald-700 dark:text-emerald-400"
        />
        <StatTile
          label={t('agents.guardrailEvents.notEvaluated')}
          value={totals?.not_evaluated}
          loading={loading}
          testId="guardrail-stat-not-evaluated"
          tone="text-muted-foreground"
          hint={t('agents.guardrailEvents.notEvaluatedHint')}
        />
      </div>

      {summary && summary.breakdown.length > 0 && <ByCheck summary={summary} />}

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <Select value={checkFilter} onValueChange={setCheckFilter}>
          <SelectTrigger
            className="w-[170px] rounded-3xl px-5 py-3 text-sm"
            size="lg"
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
            className="w-[170px] rounded-3xl px-5 py-3 text-sm"
            size="lg"
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

      <div className="border-border bg-card mt-3 w-full overflow-hidden rounded-xl border dark:bg-black">
        <div className="flex h-8 flex-col items-start justify-center bg-black/10 dark:bg-white/5">
          <p className="text-muted-foreground px-3 text-xs">
            {t('agents.guardrailEvents.tableHeader')}
          </p>
        </div>
        <div className="max-h-[45vh] overflow-y-auto">
          {loading ? (
            <div className="p-3">
              <SkeletonLoader count={3} />
            </div>
          ) : error ? (
            <p className="text-destructive p-4 text-sm">{error}</p>
          ) : visible.length === 0 ? (
            <p
              className="text-muted-foreground p-4 text-sm"
              data-testid="guardrail-events-empty"
            >
              {events.length === 0
                ? t('agents.guardrailEvents.empty')
                : t('agents.guardrailEvents.emptyForFilter')}
            </p>
          ) : (
            <table className="w-full text-left text-xs">
              <thead className="text-muted-foreground">
                <tr className="border-border border-b">
                  <th className="px-3 py-2 font-medium">
                    {t('agents.guardrailEvents.when')}
                  </th>
                  <th className="px-3 py-2 font-medium">
                    {t('agents.guardrailEvents.check')}
                  </th>
                  <th className="px-3 py-2 font-medium">
                    {t('agents.guardrailEvents.stage')}
                  </th>
                  <th className="px-3 py-2 font-medium">
                    {t('agents.guardrailEvents.outcome')}
                  </th>
                  <th className="px-3 py-2 font-medium">
                    {t('agents.guardrailEvents.detail')}
                  </th>
                </tr>
              </thead>
              <tbody data-testid="guardrail-events-rows">
                {visible.map((event) => (
                  <tr
                    key={event.id}
                    className="border-border/60 border-b last:border-0"
                  >
                    <td className="text-muted-foreground px-3 py-2 whitespace-nowrap">
                      {formatDateTime(event.created_at)}
                    </td>
                    <td className="px-3 py-2">
                      <span className="font-medium">{event.check_name}</span>
                      {event.category && (
                        <span className="text-muted-foreground ml-1">
                          · {event.category}
                        </span>
                      )}
                    </td>
                    <td className="text-muted-foreground px-3 py-2">
                      {t(STAGE_KEYS[event.stage] ?? event.stage)}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${actionTone(
                          event.action,
                          event.outcome,
                        )}`}
                      >
                        {event.outcome === 'not_evaluated'
                          ? t('agents.guardrailEvents.notEvaluated')
                          : t(ACTION_KEYS[event.action] ?? event.action)}
                      </span>
                    </td>
                    <td className="text-muted-foreground max-w-[28rem] px-3 py-2">
                      {event.detail || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
      {events.length >= PAGE_SIZE && (
        <p className="text-muted-foreground mt-2 text-xs">
          {t('agents.guardrailEvents.truncated', { count: PAGE_SIZE })}
        </p>
      )}
    </div>
  );
}

function StatTile({
  label,
  value,
  loading,
  tone,
  testId,
  hint,
}: {
  label: string;
  value?: number;
  loading: boolean;
  tone: string;
  testId: string;
  hint?: string;
}) {
  return (
    <div
      className="border-border bg-card rounded-xl border px-4 py-3"
      data-testid={testId}
      title={hint}
    >
      <p className="text-muted-foreground text-xs">{label}</p>
      {loading ? (
        <div className="mt-1 h-6 w-10">
          <SkeletonLoader count={1} />
        </div>
      ) : (
        <p className={`mt-1 text-xl font-semibold ${tone}`}>{value ?? 0}</p>
      )}
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
            <div className="bg-border/60 h-2 flex-1 overflow-hidden rounded-full">
              <div
                className="bg-violets-are-blue h-full rounded-full"
                style={{ width: `${max ? (total / max) * 100 : 0}%` }}
              />
            </div>
            <span className="text-muted-foreground w-10 shrink-0 text-right text-xs">
              {total}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
