import {
  Bot,
  KeyRound,
  RefreshCw,
  Repeat,
  type LucideIcon,
} from 'lucide-react';
import { type ReactNode, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import { agentEditPath, agentSchedulesPath } from '../../agents/paths';
import payerService, {
  type TeamUsage,
  type TeamUsagePausedItem,
} from '../../api/services/payerService';
import { canManageTeam, type TeamRole } from '../../api/services/teamsService';
import SkeletonLoader from '../../components/SkeletonLoader';
import StatCard from '../../components/StatCard';
import { Avatar } from '../../components/ui/avatar';
import { Button } from '../../components/ui/button';
import { Card } from '../../components/ui/card';
import { EmptyState } from '../../components/ui/empty-state';
import { ListRow, ListRows } from '../../components/ui/list-row';
import { SectionHeader } from '../../components/ui/section-header';
import { ToggleGroup, ToggleGroupItem } from '../../components/ui/toggle-group';
import {
  formatPayerDate,
  payerOf,
  pauseReasonText,
} from '../../payer/pauseReason';
import {
  OUTSIDE_ACCESS_KINDS,
  type OutsideAccessKind,
} from '../../payer/types';
import { usagePeriodOf, type UsagePeriod } from '../../payer/usagePeriod';
import { selectToken } from '../../preferences/preferenceSlice';
import { AppDispatch } from '../../store';
import {
  formatCount,
  headingLocale,
  intlLocale,
} from '../../utils/dateTimeUtils';
import { readerIdFromToken } from '../../utils/personLabel';
import {
  selectWorkspaceId,
  switchWorkspace,
} from '../../workspace/workspaceSlice';
import type { Team } from '../teamsSlice';
import { initialOf, truncateSub } from './teamGrants';

/** Rows a list shows before "Show all". */
const PREVIEW_ROWS = 5;

const noEscape = { interpolation: { escapeValue: false } };

const KNOWN_ROLES = new Set(['owner', 'admin', 'editor', 'viewer']);

const ACCESS_KEYS: Record<OutsideAccessKind, string> = {
  api_key: 'payer.common.access.apiKey',
  public_link: 'payer.common.access.publicLink',
  webhook: 'payer.common.access.webhook',
};

const PAUSED_ICONS: Record<TeamUsagePausedItem['type'], LucideIcon> = {
  schedule: Repeat,
  outside_access: KeyRound,
  source_sync: RefreshCw,
};

type Amount = { tokens: number; cost: number };
type Period = 'current' | 'previous';

type UsageTabProps = {
  team: Team;
  /** The caller's role in the team; the report is for its owner and admins. */
  role: TeamRole;
};

/** A list's amount column: the figure, and an optional muted line under it. */
function AmountCell({ value, sub }: { value: string; sub?: string }) {
  return (
    <div className="shrink-0 text-right">
      <p className="text-foreground text-sm tabular-nums">{value}</p>
      {sub ? (
        <p className="text-muted-foreground text-xs whitespace-nowrap">{sub}</p>
      ) : null}
    </div>
  );
}

/**
 * A titled list that shows its first rows and the rest on "Show all".
 */
function ReportList<T>({
  testId,
  title,
  rows,
  renderRow,
  empty,
  footnote,
}: {
  testId: string;
  title: string;
  rows: T[];
  renderRow: (row: T) => ReactNode;
  empty: string;
  footnote?: string;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? rows : rows.slice(0, PREVIEW_ROWS);
  return (
    <section data-testid={testId} className="flex min-w-0 flex-col gap-3">
      <SectionHeader as="h4" size="sm" title={title} count={rows.length} />
      {rows.length === 0 ? (
        <EmptyState size="xs" illustration="none" title={empty} />
      ) : (
        <Card variant="subtle" padding="none" className="overflow-hidden">
          <ListRows>{shown.map(renderRow)}</ListRows>
        </Card>
      )}
      {rows.length > PREVIEW_ROWS && (
        <Button
          variant="link"
          size="inline"
          className="self-start"
          onClick={() => setExpanded((open) => !open)}
        >
          {expanded
            ? t('payer.team.showFewer')
            : t('payer.team.showAll', {
                formatted: formatCount(rows.length),
              })}
        </Button>
      )}
      {footnote ? (
        <p className="text-muted-foreground text-xs">{footnote}</p>
      ) : null}
    </section>
  );
}

/**
 * A team's Usage tab, for its owner and admins: what was used in the team
 * workspace this period or the one before, split into chats and runs
 * without a person, by person and by agent, and what is paused for want of
 * a payer, each with a way to take it over. A report, never a limit.
 */
export default function UsageTab({ team, role }: UsageTabProps) {
  const { t, i18n } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const token = useSelector(selectToken);
  const workspaceId = useSelector(selectWorkspaceId);
  const language = i18n?.language;
  const me = readerIdFromToken(token);

  const [period, setPeriod] = useState<Period>('current');
  // The window's kind names the toggle; kept while the next period loads.
  const [kind, setKind] = useState<UsagePeriod>('month');
  const [report, setReport] = useState<TeamUsage | null>(null);
  const [status, setStatus] = useState<'loading' | 'error' | 'ready'>(
    'loading',
  );
  const [reload, setReload] = useState(0);
  const allowed = canManageTeam(role);

  useEffect(() => {
    if (!allowed) return;
    let cancelled = false;
    setStatus('loading');
    payerService
      .getTeamUsage(team.id, period, token)
      .then((body) => {
        if (cancelled) return;
        setReport(body);
        setKind(usagePeriodOf(body?.period?.kind));
        setStatus('ready');
      })
      .catch(() => {
        if (!cancelled) setStatus('error');
      });
    return () => {
      cancelled = true;
    };
  }, [allowed, team.id, token, period, reload]);

  if (!allowed) return null;

  // Dollars when any model used here has rates, tokens otherwise, as quotas
  // count.
  const priced = (report?.totals.cost ?? 0) > 0;
  const money = new Intl.NumberFormat(intlLocale(language), {
    style: 'currency',
    currency: 'USD',
  });
  const amount = (value: Amount): string =>
    priced
      ? money.format(value.cost)
      : t('payer.team.tokens', {
          count: value.tokens,
          formatted: formatCount(value.tokens, language),
        });

  const accessList = new Intl.ListFormat(
    headingLocale(language === 'jp' ? 'ja' : language),
    { type: 'conjunction' },
  );

  // The team's agents open in the team: move there first when elsewhere.
  const openInTeam = (path: string) => {
    navigate(path);
    if (workspaceId !== team.id) dispatch(switchWorkspace(team.id));
  };

  const rangeText = (usage: TeamUsage): string => {
    const start = formatPayerDate(usage.period.start, language, { utc: true });
    const endMs = new Date(usage.period.end).getTime() - 1;
    const end = Number.isNaN(endMs)
      ? ''
      : formatPayerDate(new Date(endMs).toISOString(), language, {
          utc: true,
        });
    if (!start || !end || start === end) return start || end;
    return t('payer.team.period.range', { start, end, ...noEscape });
  };

  const personRow = (row: TeamUsage['by_person'][number]) => {
    const label = row.label?.trim() || truncateSub(row.user_id);
    const roleText =
      row.role === null
        ? t('payer.team.byPerson.left')
        : KNOWN_ROLES.has(row.role)
          ? t(`workspace.common.roles.${row.role}`)
          : row.role;
    const description = [
      roleText,
      me && row.user_id === me ? t('payer.team.byPerson.you') : null,
    ]
      .filter(Boolean)
      .join(' · ');
    return (
      <ListRow
        key={row.user_id}
        leading={
          <span aria-hidden="true" className="contents">
            <Avatar alt="" size="sm" shape="circle" variant="muted">
              {initialOf(label)}
            </Avatar>
          </span>
        }
        title={label}
        description={description}
        trailing={<AmountCell value={amount(row)} />}
      />
    );
  };

  const agentRow = (row: TeamUsage['by_agent'][number]) => {
    const name = row.moved_out
      ? t('payer.team.byAgent.movedOut')
      : row.name?.trim() || t('payer.team.byAgent.deleted');
    const parts = [
      t('payer.team.byAgent.requests', {
        count: row.requests,
        formatted: formatCount(row.requests, language),
      }),
      t('payer.team.byAgent.people', {
        count: row.people,
        formatted: formatCount(row.people, language),
      }),
    ];
    if (row.published) {
      const payer = payerOf(row.published.paid_by, me);
      parts.push(
        payer.you
          ? t('payer.team.byAgent.outsidePaidByYou')
          : payer.label
            ? t('payer.team.byAgent.outsidePaidBy', {
                name: payer.label,
                ...noEscape,
              })
            : t('payer.team.byAgent.outsideNoPayer'),
      );
    }
    return (
      <ListRow
        key={row.agent_id}
        leading={
          <Avatar aria-hidden="true" size="sm" shape="square" variant="icon">
            <Bot className="size-4" aria-hidden />
          </Avatar>
        }
        title={name}
        description={parts.join(' · ')}
        trailing={
          <AmountCell
            value={amount(row)}
            sub={
              row.moved_out
                ? undefined
                : row.limit_on
                  ? t('payer.team.byAgent.limitOn')
                  : t('payer.team.byAgent.noLimit')
            }
          />
        }
      />
    );
  };

  const pausedRow = (item: TeamUsagePausedItem) => {
    const Icon = PAUSED_ICONS[item.type] ?? Repeat;
    let title: string;
    let kindLine: string;
    let reason: string;
    let target: string | null = null;
    if (item.type === 'source_sync') {
      title = item.name?.trim() || t('payer.team.paused.unnamed');
      kindLine = t('payer.team.paused.sync');
      reason = t('payer.team.paused.syncNoPayer');
    } else {
      const payer = payerOf(item.paid_by, me);
      reason = pauseReasonText(t, item.paused_for, payer.label, team.name, {
        you: payer.you,
        language,
      });
      const agentName = item.agent?.name?.trim() || '';
      if (item.type === 'schedule') {
        title =
          item.name?.trim() || agentName || t('payer.team.paused.unnamed');
        kindLine = agentName
          ? t('payer.team.paused.schedule', { agent: agentName, ...noEscape })
          : t('payer.team.paused.scheduleNoAgent');
        if (item.agent?.id) target = agentSchedulesPath(item.agent.id);
      } else {
        title = agentName || t('payer.team.paused.unnamed');
        const access = accessList.format(
          (item.access ?? [])
            .filter((access) => OUTSIDE_ACCESS_KINDS.includes(access))
            .map((access) => t(ACCESS_KEYS[access])),
        );
        kindLine = access
          ? t('payer.team.paused.access', { access, ...noEscape })
          : t('payer.team.paused.accessAll');
        target = agentEditPath(item.agent?.id || item.id);
      }
    }
    return (
      <ListRow
        key={`${item.type}-${item.id}`}
        wrap
        leading={
          <Avatar aria-hidden="true" size="sm" shape="square" variant="icon">
            <Icon className="size-4" aria-hidden />
          </Avatar>
        }
        title={title}
        description={
          <>
            <span className="block">{kindLine}</span>
            {reason ? (
              <span className="text-warning block">{reason}</span>
            ) : null}
          </>
        }
        trailing={
          target ? (
            <Button
              variant="outline"
              size="sm"
              className="shrink-0"
              aria-label={t('payer.team.paused.takeOverLabel', {
                name: title,
                ...noEscape,
              })}
              onClick={() => openInTeam(target)}
            >
              {t('payer.common.takeOver.submit')}
            </Button>
          ) : null
        }
      />
    );
  };

  const header = (
    <SectionHeader
      as="h4"
      size="xs"
      title={report && status === 'ready' ? rangeText(report) : t('loading')}
      actions={
        <ToggleGroup
          type="single"
          value={period}
          onValueChange={(value) => value && setPeriod(value as Period)}
          aria-label={t('payer.team.period.label')}
        >
          <ToggleGroupItem value="current">
            {t(`payer.team.period.current.${kind}`)}
          </ToggleGroupItem>
          <ToggleGroupItem value="previous">
            {t(`payer.team.period.previous.${kind}`)}
          </ToggleGroupItem>
        </ToggleGroup>
      }
    />
  );

  if (status === 'error') {
    return (
      <div className="flex flex-col gap-6">
        {header}
        <EmptyState
          size="sm"
          tone="destructive"
          illustration="none"
          title={t('payer.team.loadError')}
          onRetry={() => setReload((n) => n + 1)}
        />
      </div>
    );
  }

  if (status === 'loading' || !report) {
    return (
      <div className="flex flex-col gap-6">
        {header}
        <SkeletonLoader component="default" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-4">
        {header}
        <div className="grid gap-4 md:grid-cols-3">
          <StatCard
            label={t('payer.team.stats.used', { team: team.name, ...noEscape })}
            value={amount(report.totals)}
            sub={t('payer.team.stats.people', {
              count: report.totals.people,
              formatted: formatCount(report.totals.people, language),
            })}
          />
          <StatCard
            label={t('payer.team.stats.chats')}
            value={amount(report.split.chats)}
            sub={t('payer.team.stats.chatsDetail')}
          />
          <StatCard
            label={t('payer.team.stats.runs')}
            value={amount(report.split.runs)}
            sub={t('payer.team.stats.runsDetail')}
          />
        </div>
        <p className="text-muted-foreground text-xs">
          {t('payer.team.notALimit')}
        </p>
      </div>

      {report.paused.length > 0 && (
        <section data-testid="usage-paused" className="flex flex-col gap-3">
          <SectionHeader
            as="h4"
            size="sm"
            title={t('payer.team.paused.title')}
            count={report.paused.length}
          />
          <p className="text-muted-foreground text-sm">
            {t('payer.team.paused.description')}
          </p>
          <Card variant="subtle" padding="none" className="overflow-hidden">
            <ListRows>{report.paused.map(pausedRow)}</ListRows>
          </Card>
        </section>
      )}

      <div className="grid gap-8 lg:grid-cols-2">
        <ReportList
          testId="usage-by-person"
          title={t('payer.team.byPerson.title')}
          rows={report.by_person}
          renderRow={personRow}
          empty={t('payer.team.empty')}
        />
        <ReportList
          testId="usage-by-agent"
          title={t('payer.team.byAgent.title')}
          rows={report.by_agent}
          renderRow={agentRow}
          empty={t('payer.team.byAgent.empty')}
          footnote={t('payer.team.byAgent.totalsOnly')}
        />
      </div>
    </div>
  );
}
