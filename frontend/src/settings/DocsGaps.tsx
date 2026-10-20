import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  ChevronRight,
  Download,
  Minus,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { Link, useLocation } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Card, CardDescription, CardTitle } from '@/components/ui/card';
import {
  DescriptionItem,
  DescriptionList,
} from '@/components/ui/description-list';
import { EmptyState } from '@/components/ui/empty-state';
import { ListRow, ListRows } from '@/components/ui/list-row';
import { SectionHeader } from '@/components/ui/section-header';
import { PanelBody, PanelHeader, SidePanel } from '@/components/ui/side-panel';
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { cn } from '@/lib/utils';

import userService from '../api/services/userService';
import SkeletonLoader from '../components/SkeletonLoader';
import { selectToken } from '../preferences/preferenceSlice';
import {
  EMPTY_VALUE,
  formatCount,
  formatDateTime,
} from '../utils/dateTimeUtils';
import { docsGapsCsv, docsGapsFileName, downloadCsv } from './docsGapsCsv';
import {
  formatEstimate,
  formatShare,
  gapChange,
  NONE_OF_THESE,
} from './insights/format';
import { logsDrilldownPath, revealElement } from './logsLinks';
import type { DocsGapRow, DocsGapsGroup } from './types';

/** The most groups the report lists: a short table, so no pager. */
const LIMIT = 25;

/** The last grouping picked, kept on this device. */
const GROUP_STORAGE_KEY = 'DocsGPTDocsGapsGroup';

function readGroup(): DocsGapsGroup {
  try {
    const stored = localStorage.getItem(GROUP_STORAGE_KEY);
    if (stored === 'page' || stored === 'source' || stored === 'topic')
      return stored;
  } catch {
    // Storage blocked (private mode): the default.
  }
  return 'page';
}

function writeGroup(group: DocsGapsGroup) {
  try {
    localStorage.setItem(GROUP_STORAGE_KEY, group);
  } catch {
    // Not remembered, but still applied.
  }
}

type DocsGapsProps = {
  agentId?: string;
  /** For the CSV's file name. */
  agentName?: string;
  filterOption: string;
  /** The agent has topics, so grouping by topic is offered. */
  hasTopics: boolean;
};

/**
 * Questions the docs could not answer, grouped by the closest retrieved page,
 * its source or the question's topic: expected gaps, the
 * share of the group's questions, the change from the previous period, and
 * example questions that open in Logs. Rendered by ConversationInsights only
 * while it has figures, so it says nothing about off or empty states itself.
 */
export default function DocsGaps({
  agentId,
  agentName,
  filterOption,
  hasTopics,
}: DocsGapsProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const location = useLocation();
  const [stored, setStored] = useState<DocsGapsGroup>(readGroup);
  const groupBy: DocsGapsGroup =
    stored === 'topic' && !hasTopics ? 'page' : stored;
  const [state, setState] = useState<{
    status: 'loading' | 'error' | 'ready';
    enabled: boolean;
    rows: DocsGapRow[];
  }>({ status: 'loading', enabled: true, rows: [] });
  const [reloadKey, setReloadKey] = useState(0);
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const requestId = useRef(0);
  const sectionRef = useRef<HTMLDivElement>(null);
  const revealed = useRef(false);

  useEffect(() => {
    const id = ++requestId.current;
    setState((prev) => ({ ...prev, status: 'loading', rows: [] }));
    setOpenIndex(null);
    userService
      .getDocsGaps(
        {
          api_key_id: agentId,
          filter_option: filterOption,
          group_by: groupBy,
          limit: LIMIT,
        },
        token,
      )
      .then((response) => {
        if (!response.ok) throw new Error('docs gaps');
        return response.json();
      })
      .then(
        (body: {
          success?: boolean;
          enabled?: boolean;
          rows?: DocsGapRow[];
        }) => {
          if (id !== requestId.current) return;
          if (!body?.success) throw new Error('docs gaps');
          setState({
            status: 'ready',
            enabled: body.enabled !== false,
            rows: body.rows ?? [],
          });
        },
      )
      .catch(() => {
        if (id === requestId.current)
          setState({ status: 'error', enabled: true, rows: [] });
      });
  }, [agentId, filterOption, groupBy, token, reloadKey]);

  // The weekly notification links here (`#docs-gaps`): once the report has
  // loaded, bring it into view.
  useEffect(() => {
    if (state.status !== 'ready' || revealed.current) return;
    if (location.hash !== '#docs-gaps') return;
    revealed.current = true;
    revealElement(sectionRef.current, 'start');
  }, [state.status, location.hash]);

  if (state.status === 'ready' && !state.enabled) return null;

  const { rows } = state;
  const openRow = openIndex !== null ? rows[openIndex] : undefined;
  const groupLabel = t(`settings.analytics.gaps.groups.${groupBy}`);

  const nameOf = (row: DocsGapRow): string | null => {
    const name = row.name || row.key;
    if (!name) return null;
    return groupBy === 'topic' && name === NONE_OF_THESE
      ? t('settings.analytics.insights.panels.noneOfThese')
      : name;
  };
  const displayName = (row: DocsGapRow) =>
    nameOf(row) ?? t('settings.analytics.gaps.noPage');

  const exportCsv = () =>
    downloadCsv(
      docsGapsCsv(rows, groupBy),
      docsGapsFileName({ agentName, groupBy, filterOption }),
    );

  const shareText = (row: DocsGapRow) =>
    t('settings.analytics.gaps.share', {
      count: row.turns,
      percent: formatShare(row.rate),
      formatted: formatCount(row.turns),
    });

  return (
    <div
      ref={sectionRef}
      id="docs-gaps"
      className="mt-8 flex flex-col gap-4"
      data-testid="docs-gaps"
    >
      <SectionHeader
        title={t('settings.analytics.gaps.heading')}
        description={t(`settings.analytics.gaps.description.${groupBy}`)}
        actions={
          <>
            <ToggleGroup
              type="single"
              value={groupBy}
              onValueChange={(value) => {
                if (!value) return;
                setStored(value as DocsGapsGroup);
                writeGroup(value as DocsGapsGroup);
              }}
              aria-label={t('settings.analytics.gaps.groupBy')}
            >
              <ToggleGroupItem value="page">
                {t('settings.analytics.gaps.groups.page')}
              </ToggleGroupItem>
              <ToggleGroupItem value="source">
                {t('settings.analytics.gaps.groups.source')}
              </ToggleGroupItem>
              {hasTopics && (
                <ToggleGroupItem value="topic">
                  {t('settings.analytics.gaps.groups.topic')}
                </ToggleGroupItem>
              )}
            </ToggleGroup>
            {state.status === 'ready' && rows.length > 0 && (
              <Button
                type="button"
                variant="outline"
                size="field"
                shape="pill"
                onClick={exportCsv}
              >
                <Download />
                {t('settings.analytics.gaps.export')}
              </Button>
            )}
          </>
        }
      />

      {state.status === 'loading' ? (
        <Card variant="subtle" padding="sm">
          <SkeletonLoader count={3} />
        </Card>
      ) : state.status === 'error' ? (
        <EmptyState
          tone="destructive"
          size="sm"
          illustration="none"
          title={t('settings.analytics.gaps.loadError')}
          onRetry={() => setReloadKey((key) => key + 1)}
        />
      ) : rows.length === 0 ? (
        <EmptyState
          size="sm"
          illustration="none"
          title={t('settings.analytics.gaps.empty')}
          description={t('settings.analytics.gaps.emptyDescription')}
        />
      ) : (
        <>
          <TableContainer className="hidden lg:block">
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeader>{groupLabel}</TableHeader>
                  <TableHeader align="right">
                    {t('settings.analytics.gaps.columns.gaps')}
                  </TableHeader>
                  <TableHeader align="right">
                    {t('settings.analytics.gaps.columns.share')}
                  </TableHeader>
                  <TableHeader align="right">
                    {t('settings.analytics.gaps.columns.change')}
                  </TableHeader>
                  <TableHeader>
                    {t('settings.analytics.gaps.columns.example')}
                  </TableHeader>
                  <TableHeader width="40px" align="center">
                    <span className="sr-only">
                      {t('settings.analytics.gaps.columns.open')}
                    </span>
                  </TableHeader>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((row, index) => {
                  const name = nameOf(row);
                  const prompt = row.examples[0]?.prompt;
                  return (
                    <TableRow
                      key={`${row.key ?? ''}:${index}`}
                      selected={openIndex === index}
                      onClick={() => setOpenIndex(index)}
                      aria-label={t('settings.analytics.gaps.openRow', {
                        name: displayName(row),
                        interpolation: { escapeValue: false },
                      })}
                    >
                      <TableCell>
                        <span
                          className={cn(
                            'block max-w-64 truncate',
                            name ? 'font-medium' : 'text-muted-foreground',
                          )}
                          title={row.key ?? undefined}
                        >
                          {displayName(row)}
                        </span>
                      </TableCell>
                      <TableCell
                        align="right"
                        className="whitespace-nowrap tabular-nums"
                      >
                        {formatEstimate(row.expected_gaps)}
                      </TableCell>
                      <TableCell
                        align="right"
                        className="whitespace-nowrap tabular-nums"
                      >
                        {shareText(row)}
                      </TableCell>
                      <TableCell align="right" className="whitespace-nowrap">
                        <GapChangeLabel
                          expected={row.expected_gaps}
                          previous={row.previous_expected}
                        />
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {prompt ? (
                          <span
                            className="line-clamp-1 max-w-80"
                            title={prompt}
                          >
                            {prompt}
                          </span>
                        ) : (
                          EMPTY_VALUE
                        )}
                      </TableCell>
                      <TableCell align="center">
                        <ChevronRight
                          aria-hidden
                          className="text-muted-foreground size-4"
                        />
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>

          <ul className="flex flex-col gap-3 lg:hidden">
            {rows.map((row, index) => {
              const prompt = row.examples[0]?.prompt;
              return (
                <li key={`${row.key ?? ''}:${index}`}>
                  <Card variant="filled" interactive asChild className="w-full">
                    <button type="button" onClick={() => setOpenIndex(index)}>
                      <div className="flex w-full items-center gap-3">
                        <CardTitle
                          className="min-w-0 flex-1 truncate"
                          title={row.key ?? undefined}
                        >
                          {displayName(row)}
                        </CardTitle>
                        <ChevronRight
                          aria-hidden
                          className="text-muted-foreground size-4 shrink-0"
                        />
                      </div>
                      <div className="flex flex-wrap items-center gap-x-1.5 text-xs tabular-nums">
                        <span>
                          {t('settings.analytics.gaps.gapsCount', {
                            count: Math.round(row.expected_gaps),
                            formatted: formatEstimate(row.expected_gaps),
                          })}
                        </span>
                        <span aria-hidden>·</span>
                        <span>{shareText(row)}</span>
                        <span aria-hidden>·</span>
                        <GapChangeLabel
                          expected={row.expected_gaps}
                          previous={row.previous_expected}
                        />
                      </div>
                      {prompt && (
                        <CardDescription size="xs" className="line-clamp-2">
                          {prompt}
                        </CardDescription>
                      )}
                    </button>
                  </Card>
                </li>
              );
            })}
          </ul>
        </>
      )}

      <SidePanel
        open={openRow !== undefined}
        onOpenChange={(open) => !open && setOpenIndex(null)}
      >
        {openRow && (
          <>
            <PanelHeader
              title={displayName(openRow)}
              description={groupLabel}
            />
            <PanelBody>
              <DescriptionList size="sm">
                <DescriptionItem
                  label={t('settings.analytics.gaps.panel.gaps')}
                >
                  {formatEstimate(openRow.expected_gaps)}
                </DescriptionItem>
                <DescriptionItem
                  label={t('settings.analytics.gaps.panel.share')}
                >
                  {shareText(openRow)}
                </DescriptionItem>
                <DescriptionItem
                  label={t('settings.analytics.gaps.panel.previous')}
                >
                  {formatEstimate(openRow.previous_expected)}
                </DescriptionItem>
              </DescriptionList>
              {openRow.examples.length > 0 && (
                <div className="flex flex-col gap-3">
                  <SectionHeader
                    as="h3"
                    size="xs"
                    title={t('settings.analytics.gaps.panel.examples')}
                  />
                  <Card
                    variant="subtle"
                    padding="none"
                    className="overflow-hidden"
                  >
                    <ListRows>
                      {openRow.examples.map((example) => (
                        <ListRow
                          key={example.message_id}
                          interactive
                          asChild
                          title={example.prompt}
                          description={formatDateTime(example.timestamp)}
                        >
                          <Link
                            to={logsDrilldownPath({
                              agentId,
                              conversationId: example.conversation_id,
                              messageId: example.message_id,
                            })}
                            onClick={() => setOpenIndex(null)}
                          />
                        </ListRow>
                      ))}
                    </ListRows>
                  </Card>
                </div>
              )}
              <div>
                <Button variant="link" size="inline" asChild>
                  <Link
                    to={logsDrilldownPath({ agentId, label: 'docs_gap' })}
                    onClick={() => setOpenIndex(null)}
                  >
                    {t('settings.analytics.gaps.panel.allInLogs')}
                    <ArrowRight />
                  </Link>
                </Button>
              </div>
            </PanelBody>
          </>
        )}
      </SidePanel>
    </div>
  );
}

/**
 * The change from the previous period: "New", no change, or up / down by a
 * rounded count. More gaps is worse, so up is red and down is green; the
 * colour is only on the short label and its icon.
 */
function GapChangeLabel({
  expected,
  previous,
}: {
  expected: number;
  previous: number;
}) {
  const { t } = useTranslation();
  const change = gapChange(expected, previous);
  if (change.kind === 'new')
    return (
      <span className="text-warning text-xs font-medium">
        {t('settings.analytics.gaps.change.new')}
      </span>
    );
  if (change.kind === 'none')
    return (
      <span className="text-muted-foreground inline-flex items-center">
        <Minus aria-hidden className="size-3" />
        <span className="sr-only">
          {t('settings.analytics.gaps.change.none')}
        </span>
      </span>
    );
  const formatted = formatCount(change.delta);
  const up = change.kind === 'up';
  const Icon = up ? ArrowUp : ArrowDown;
  return (
    <span
      className={cn(
        'inline-flex items-center gap-0.5 text-xs tabular-nums',
        up ? 'text-destructive' : 'text-success',
      )}
    >
      <Icon aria-hidden className="size-3" />
      <span aria-hidden>{up ? `+${formatted}` : `−${formatted}`}</span>
      <span className="sr-only">
        {t(
          up
            ? 'settings.analytics.gaps.change.upLabel'
            : 'settings.analytics.gaps.change.downLabel',
          { formatted },
        )}
      </span>
    </span>
  );
}
