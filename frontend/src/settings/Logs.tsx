import { Activity, ChevronRight, ThumbsDown, ThumbsUp } from 'lucide-react';
import React, { useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { useSearchParams } from 'react-router-dom';

import {
  selectActivityRevision,
  selectRunningKey,
} from '../activity/activitySlice';
import { formatElapsed, workflowStep } from '../activity/format';
import userService from '../api/services/userService';
import CopyButton from '../components/CopyButton';
import SearchInput from '../components/SearchInput';
import SkeletonLoader from '../components/SkeletonLoader';
import { useClock } from '../hooks/useClock';
import { useScrollSentinel } from '../hooks/useLoadMore';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { CodeBlock } from '../components/ui/code-block';
import { Collapsible } from '../components/ui/collapsible';
import {
  DescriptionItem,
  DescriptionList,
} from '../components/ui/description-list';
import { EmptyState } from '../components/ui/empty-state';
import { LoadMoreStatus } from '../components/ui/load-more-status';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { useLoaderState } from '../hooks';
import { cn } from '../lib/utils';
import {
  selectAnalyticsEnabled,
  selectToken,
} from '../preferences/preferenceSlice';
import LabelChips from './LabelChips';
import TraceChips from './traces/TraceChips';
import TraceSheet from './traces/TraceSheet';
import { isLogLabel, LOG_LABELS, revealElement } from './logsLinks';
import { mergeLoadedPages, newestFirst, uniqueLogs } from './logsPage';
import { formatDurationMs } from './traces/traceUtils';
import { AgentTopic, LogData, TraceRef } from './types';

/** How often page 1 reloads while it shows a run: runs by other people on a
 * shared agent send their events to them, not to the owner. */
const RUNNING_POLL_MS = 30_000;

/** Rows per page. */
const PAGE_SIZE = 10;
/** A log's own keys that its Copy leaves out; the rest is the record. */
const COPY_OMITS = ['id', 'action', 'timestamp', 'event_type'];

/** The most rows one request reads: the endpoint's largest page. */
const MAX_REQUEST_ROWS = 100;

/** The most pages read looking for a linked message before giving up. */
const MAX_TARGET_PAGES = 10;

/** A conversation id as the API takes it: a UUID, else it refuses the call. */
const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The label filter's keys under `settings.logs.labels`. */
const LABEL_KEYS: Record<(typeof LOG_LABELS)[number], string> = {
  not_answered: 'notAnswered',
  docs_gap: 'docsGap',
  frustrated: 'frustrated',
  asks_human: 'asksHuman',
  negative_reaction: 'negativeReaction',
  negative_sentiment: 'negativeSentiment',
};

type LogsProps = {
  agentId?: string;
  tableHeader?: string;
  /**
   * An agent's analytics: whether its conversations are labelled (the label
   * filter shows only then) and its topics, offered as filters; those that
   * can overlap also name the rows' chips. Left out on the account's Logs.
   */
  analytics?: { enabled: boolean; topics: AgentTopic[] };
};

export default function Logs({ agentId, tableHeader, analytics }: LogsProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  // The drill-down filters live in the URL, so a docs-gap example or a
  // shared link opens Logs already narrowed: `label`, `conversation` and the
  // `message` to open.
  const [searchParams, setSearchParams] = useSearchParams();
  const rawLabel = searchParams.get('label');
  const labelFilter = isLogLabel(rawLabel) ? rawLabel : null;
  // A malformed id is ignored, like an unknown label: the API would refuse
  // it and leave an error with no way out.
  const rawConversation = searchParams.get('conversation');
  const conversationFilter =
    rawConversation && UUID_RE.test(rawConversation) ? rawConversation : null;
  const messageTarget = searchParams.get('message') || null;
  // The server's flag from Redux (read at start-up), so the filter row is
  // whole on the first paint instead of growing a select later.
  const serverLabels = useSelector(selectAnalyticsEnabled);
  // On an agent's page the agent must label its conversations too; until it
  // has loaded the filter stays hidden. A link that carries a label keeps it
  // shown, so the filter can be cleared.
  const labelsOn =
    serverLabels && (agentId ? Boolean(analytics?.enabled) : true);
  const showLabelFilter = labelsOn || labelFilter !== null;
  // Chip names of the agent's overlapping topics (`tag:<id>`), then from
  // each page's `tag_names`.
  const [pageTagNames, setPageTagNames] = useState<Record<string, string>>({});
  const agentTopics = analytics?.topics ?? [];
  const tagNames = {
    ...pageTagNames,
    ...Object.fromEntries(
      agentTopics
        .filter((topic) => topic.label.startsWith('tag:'))
        .map((topic) => [topic.label.slice('tag:'.length), topic.name]),
    ),
  };
  const [logsByPage, setLogsByPage] = useState<Record<number, LogData[]>>({});
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [loadingLogs, setLoadingLogs] = useLoaderState(true);
  // The last page failed: an error with Retry instead of "no logs".
  const [loadFailed, setLoadFailed] = useState(false);

  const [levelFilter, setLevelFilter] = useState('all');
  const [typeFilter, setTypeFilter] = useState('all');
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [openTrace, setOpenTrace] = useState<TraceRef | null>(null);

  const logs = uniqueLogs(Object.values(logsByPage));
  const activityRevision = useSelector(selectActivityRevision);
  const runningKey = useSelector(selectRunningKey);

  // Identifies the filter combination a request was issued under, so a
  // slow response from a previous combination is discarded instead of
  // landing in the freshly reset cache.
  const filterKey = [
    agentId ?? '',
    levelFilter,
    typeFilter,
    search,
    labelFilter ?? '',
    conversationFilter ?? '',
  ].join('|');
  const filterKeyRef = useRef(filterKey);
  filterKeyRef.current = filterKey;
  const isFirstRender = useRef(true);
  // Set synchronously by the reset effect so the fetch effect — which
  // runs later in the same commit, still seeing the pre-reset `page` —
  // skips that cycle instead of fetching a stale page under the new
  // filters (which could latch hasMore=false and freeze the list).
  const resetPendingRef = useRef(false);
  // Moves whenever the pages start over (new filters, or a refresh that
  // read past them): a Load more still out asked for a page of the old
  // paging, and its rows and has_more no longer fit.
  const generationRef = useRef(0);
  // The pages on their way, by paging generation, filters and page. The
  // fetch effect runs again whenever a page lands, and the seek and the
  // scroll sentinel can each move on while one loads, so without this a
  // page still loading would be asked for again.
  const inFlightRef = useRef(new Set<string>());

  useEffect(() => {
    const handle = setTimeout(() => setSearch(searchInput.trim()), 400);
    return () => clearTimeout(handle);
  }, [searchInput]);

  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    resetPendingRef.current = true;
    generationRef.current += 1;
    setLoadFailed(false);
    setLogsByPage({});
    setPage(1);
    setHasMore(true);
  }, [
    levelFilter,
    typeFilter,
    search,
    agentId,
    labelFilter,
    conversationFilter,
  ]);

  // A new drill-down starts from every level, type and text, so a filter
  // left from earlier can't hide the conversation it points at.
  const shownConversation = useRef(conversationFilter);
  useEffect(() => {
    if (shownConversation.current === conversationFilter) return;
    shownConversation.current = conversationFilter;
    if (!conversationFilter) return;
    setLevelFilter('all');
    setTypeFilter('all');
    setSearchInput('');
    setSearch('');
  }, [conversationFilter]);

  const setLabelFilter = (value: string) =>
    setSearchParams(
      (prev) => {
        const params = new URLSearchParams(prev);
        if (value === 'all') params.delete('label');
        else params.set('label', value);
        return params;
      },
      { replace: true },
    );
  const clearConversation = () =>
    setSearchParams(
      (prev) => {
        const params = new URLSearchParams(prev);
        params.delete('conversation');
        params.delete('message');
        return params;
      },
      { replace: true },
    );
  const addTagNames = (names: unknown) => {
    if (!names || typeof names !== 'object') return;
    const entries = Object.entries(names as Record<string, unknown>).filter(
      (entry): entry is [string, string] => typeof entry[1] === 'string',
    );
    if (entries.length)
      setPageTagNames((prev) => ({ ...prev, ...Object.fromEntries(entries) }));
  };

  const requestPage = (pageNumber: number, pageSize = PAGE_SIZE) =>
    userService.getLogs(
      {
        page: pageNumber,
        api_key_id: agentId,
        page_size: pageSize,
        level: levelFilter === 'all' ? undefined : levelFilter,
        ...typeFilterParams(typeFilter),
        search: search || undefined,
        label: labelFilter ?? undefined,
        conversation_id: conversationFilter ?? undefined,
      },
      token,
    );

  const fetchLogs = async () => {
    if (logsByPage[page] && logsByPage[page].length > 0) return;

    const issuedKey = filterKey;
    const issuedPage = page;
    const issuedGeneration = generationRef.current;
    const flight = `${issuedGeneration}|${issuedPage}|${issuedKey}`;
    if (inFlightRef.current.has(flight)) return;
    inFlightRef.current.add(flight);
    setLoadingLogs(true);
    setLoadFailed(false);
    try {
      const response = await requestPage(page);
      if (!response.ok) throw new Error('Failed to fetch logs');
      const data = await response.json();
      if (
        issuedKey !== filterKeyRef.current ||
        issuedGeneration !== generationRef.current ||
        resetPendingRef.current
      )
        return;

      setLogsByPage((prev) => ({
        ...prev,
        [issuedPage]: data.logs,
      }));
      setHasMore(data.has_more);
      addTagNames(data.tag_names);
    } catch (error) {
      console.error(error);
      if (
        issuedKey === filterKeyRef.current &&
        issuedGeneration === generationRef.current
      )
        setLoadFailed(true);
    } finally {
      inFlightRef.current.delete(flight);
      if (issuedKey === filterKeyRef.current) setLoadingLogs(false);
    }
  };

  // `logsByPage` is a dependency so the fetch re-fires after a filter
  // change clears the cache; the early-return guard keeps it from looping.
  useEffect(() => {
    if (resetPendingRef.current) {
      // The reset effect ran in this commit; this closure still sees
      // pre-reset state. Its queued updates re-run this effect with
      // the clean values.
      resetPendingRef.current = false;
      return;
    }
    if (hasMore) fetchLogs();
  }, [
    page,
    agentId,
    levelFilter,
    typeFilter,
    search,
    labelFilter,
    conversationFilter,
    logsByPage,
  ]);

  // Reloads the loaded pages in place: new rows come in on top and runs that
  // ended give way to their finished rows. Only page 1 while no loaded page
  // shows a run; while one does, pages 1 to the deepest one showing a run
  // (the pages past it only shift, as past page 1 when none runs): one
  // request up to 100 rows, past that one per 100, side by side.
  const logsByPageRef = useRef(logsByPage);
  logsByPageRef.current = logsByPage;
  // The latest refresh. The poll and an activity change can each start one;
  // an older one answering last would put back runs that have ended.
  const refreshSeqRef = useRef(0);
  const refreshLoadedPages = async () => {
    const issuedKey = filterKey;
    const seq = ++refreshSeqRef.current;
    const loaded = logsByPageRef.current;
    const pages = Math.max(
      1,
      ...Object.entries(loaded)
        .filter(([, rows]) => rows.some((log) => log.running))
        .map(([n]) => Number(n)),
    );
    const rows = pages * PAGE_SIZE;
    try {
      const responses = await Promise.all(
        rows <= MAX_REQUEST_ROWS
          ? [requestPage(1, rows)]
          : Array.from({ length: Math.ceil(rows / MAX_REQUEST_ROWS) }, (_, i) =>
              requestPage(i + 1, MAX_REQUEST_ROWS),
            ),
      );
      if (responses.some((response) => !response.ok)) return;
      const parts = await Promise.all(
        responses.map((response) => response.json()),
      );
      // The server adds running webhook rows to request 1 only, by time
      // within it: one older than its rows sits at its end, ahead of the
      // next request's, so the joined rows are put back in time order.
      // Past one request, the last reads beyond the loaded rows; what it
      // has beyond them is more.
      const last = parts[parts.length - 1];
      const keep =
        parts.length > 1
          ? rows - (parts.length - 1) * MAX_REQUEST_ROWS
          : last.logs.length;
      const joined = [
        ...parts.slice(0, -1).flatMap((part) => part.logs),
        ...last.logs.slice(0, keep),
      ];
      const data = {
        logs: parts.length > 1 ? newestFirst(joined) : joined,
        has_more: last.has_more || last.logs.length > keep,
      };
      if (issuedKey !== filterKeyRef.current) return;
      parts.forEach((part) => addTagNames(part.tag_names));
      if (seq !== refreshSeqRef.current) return;
      const previous = logsByPageRef.current;
      if (!previous[1]) return;
      const merged = mergeLoadedPages(
        previous,
        data.logs,
        pages,
        PAGE_SIZE,
        Boolean(data.has_more),
      );
      if (merged.reset) {
        // Loading more goes on from the refreshed pages.
        generationRef.current += 1;
        setLogsByPage(merged.pages);
        setPage(pages);
        setHasMore(true);
        return;
      }
      // Merged against the latest state: a page may have landed meanwhile.
      setLogsByPage(
        (prev) =>
          mergeLoadedPages(prev, data.logs, pages, PAGE_SIZE, false).pages,
      );
    } catch (error) {
      // The next event or poll tries again.
      console.error(error);
    }
  };

  // The cue to refresh: the activity revision moves when a run ends (or a
  // poll found news), the running key when a run starts or ends. A run that
  // only moves a step moves neither. Both moving at once refreshes once.
  const seen = useRef(`${activityRevision}#${runningKey}`);
  useEffect(() => {
    const now = `${activityRevision}#${runningKey}`;
    if (seen.current === now) return;
    seen.current = now;
    void refreshLoadedPages();
  }, [activityRevision, runningKey]);

  // The poll calls this render's refresh, not the one it started with: that
  // one's token may have been renewed since.
  const refreshRef = useRef(refreshLoadedPages);
  refreshRef.current = refreshLoadedPages;
  const showsRunning = logs.some((log) => log.running);
  useEffect(() => {
    if (!showsRunning) return;
    const timer = window.setInterval(
      () => void refreshRef.current(),
      RUNNING_POLL_MS,
    );
    return () => window.clearInterval(timer);
  }, [showsRunning, filterKey]);

  const levelOptions = [
    { label: t('settings.logs.levels.all'), value: 'all' },
    { label: t('settings.logs.levels.info'), value: 'info' },
    { label: t('settings.logs.levels.error'), value: 'error' },
    { label: t('settings.logs.levels.warning'), value: 'warning' },
  ];
  const typeOptions = [
    { label: t('settings.logs.types.all'), value: 'all' },
    { label: t('settings.logs.types.chat'), value: 'chat' },
    { label: t('settings.logs.types.schedule'), value: 'schedule' },
    { label: t('settings.logs.types.webhook'), value: 'webhook' },
    { label: t('settings.logs.types.workflow'), value: 'workflow' },
    { label: t('settings.logs.types.system'), value: 'system' },
    { label: t('settings.logs.types.search'), value: 'search' },
    { label: t('settings.logs.types.graph'), value: 'graph' },
    { label: t('settings.logs.feedback.like'), value: 'like' },
    { label: t('settings.logs.feedback.dislike'), value: 'dislike' },
  ];

  // The agent's topics, and the one in the URL even if it isn't one of them.
  const topicOptions: { label: string; name: string }[] = [...agentTopics];
  if (
    labelFilter &&
    (labelFilter.startsWith('tag:') || labelFilter.startsWith('topic:')) &&
    !topicOptions.some((topic) => topic.label === labelFilter)
  ) {
    const name = labelFilter.startsWith('tag:')
      ? (tagNames[labelFilter.slice('tag:'.length)] ??
        labelFilter.slice('tag:'.length))
      : labelFilter.slice('topic:'.length);
    topicOptions.push({ label: labelFilter, name });
  }
  const selectedTopicName = topicOptions.find(
    (topic) => topic.label === labelFilter,
  )?.name;
  const drilledDown = labelFilter !== null || conversationFilter !== null;

  return (
    <div>
      {/* The account's copy; an agent's Logs page heads the list itself. */}
      {!agentId && (
        <p className="text-muted-foreground mb-5 text-sm leading-6">
          {t('settings.logs.subtitle')}
        </p>
      )}
      <div className="mb-3">
        <div className="flex flex-row flex-wrap items-center gap-3">
          <Select value={levelFilter} onValueChange={setLevelFilter}>
            <SelectTrigger
              className="min-w-[125px]"
              size="field"
              shape="pill"
              aria-label={t('settings.logs.levelFilter')}
            >
              <SelectValue placeholder={t('settings.logs.levels.all')} />
            </SelectTrigger>
            <SelectContent fit>
              {levelOptions.map((o) => (
                <SelectItem key={o.value} value={o.value}>
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={typeFilter} onValueChange={setTypeFilter}>
            <SelectTrigger
              className="min-w-[140px]"
              size="field"
              shape="pill"
              aria-label={t('settings.logs.typeFilter')}
            >
              <SelectValue placeholder={t('settings.logs.types.all')} />
            </SelectTrigger>
            <SelectContent fit>
              {typeOptions.map((o) => (
                <SelectItem key={o.value} value={o.value}>
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {showLabelFilter && (
            <Select value={labelFilter ?? 'all'} onValueChange={setLabelFilter}>
              <SelectTrigger
                className="min-w-[170px]"
                size="field"
                shape="pill"
                aria-label={t('settings.logs.labels.filter')}
                title={selectedTopicName}
                data-testid="logs-label-filter"
              >
                <SelectValue
                  placeholder={t('settings.logs.labels.filterAll')}
                />
              </SelectTrigger>
              <SelectContent fit>
                <SelectItem value="all">
                  {t('settings.logs.labels.filterAll')}
                </SelectItem>
                {LOG_LABELS.map((label) => (
                  <SelectItem key={label} value={label}>
                    {t(`settings.logs.labels.${LABEL_KEYS[label]}`)}
                  </SelectItem>
                ))}
                {topicOptions.length > 0 && (
                  <>
                    <SelectSeparator />
                    <SelectGroup>
                      <SelectLabel>
                        {t('settings.logs.labels.topics')}
                      </SelectLabel>
                      {topicOptions.map((topic) => (
                        <SelectItem key={topic.label} value={topic.label}>
                          {topic.name}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </>
                )}
              </SelectContent>
            </Select>
          )}
          <div className="w-56">
            <SearchInput
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              label={t('settings.logs.searchPlaceholder')}
            />
          </div>
          {conversationFilter && (
            <Badge
              onRemove={clearConversation}
              removeLabel={t('settings.logs.labels.clearConversation')}
              data-testid="logs-conversation-chip"
            >
              {t('settings.logs.labels.conversation')}
              <span className="font-mono" title={conversationFilter}>
                {conversationFilter.slice(0, 8)}
              </span>
            </Badge>
          )}
        </div>
        {drilledDown && (
          <p className="text-muted-foreground mt-1.5 text-xs">
            {t('settings.logs.labels.hint')}
          </p>
        )}
      </div>
      <div>
        <LogsTable
          logs={logs}
          setPage={setPage}
          loading={loadingLogs}
          hasMore={hasMore}
          failed={loadFailed}
          onRetry={fetchLogs}
          tableHeader={tableHeader}
          onViewTrace={setOpenTrace}
          emptyTitle={
            drilledDown
              ? t('settings.logs.labels.emptyForFilter')
              : t('settings.logs.noLogs')
          }
          targetMessageId={messageTarget}
          tagNames={tagNames}
        />
      </div>
      <TraceSheet
        traceRef={openTrace}
        agentId={agentId}
        onClose={() => setOpenTrace(null)}
      />
    </div>
  );
}

/**
 * The request filters for the event-type select: an event type, or Liked /
 * Disliked, which ask for chat turns rated that way.
 */
export function typeFilterParams(value: string): {
  event_type?: string;
  feedback?: string;
} {
  if (value === 'all') return {};
  if (value === 'like' || value === 'dislike') return { feedback: value };
  return { event_type: value };
}

type LogsTableProps = {
  logs: LogData[];
  setPage: React.Dispatch<React.SetStateAction<number>>;
  loading: boolean;
  hasMore: boolean;
  /** The last page failed to load; `onRetry` asks for it again. */
  failed: boolean;
  onRetry: () => void;
  tableHeader?: string;
  onViewTrace: (ref: TraceRef) => void;
  /** The empty list's message: none at all, or none for the drill-down. */
  emptyTitle: string;
  /** A message to open and bring into view once its row has loaded. */
  targetMessageId: string | null;
  tagNames: Record<string, string>;
};
function LogsTable({
  logs,
  setPage,
  loading,
  hasMore,
  failed,
  onRetry,
  tableHeader,
  onViewTrace,
  emptyTitle,
  targetMessageId,
  tagNames,
}: LogsTableProps) {
  const { t } = useTranslation();
  const [openLogId, setOpenLogId] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Opens the linked message once, when its row arrives; collapsing it
  // afterwards is the user's choice and sticks. Pages hold the newest rows
  // first, so an older message is further on: load on until its row is
  // there, the last page or MAX_TARGET_PAGES.
  const openedTarget = useRef<string | null>(null);
  // `rows`: how many rows were there when it last asked for a page, so a
  // render before that page starts loading doesn't ask again.
  const seeking = useRef({ target: '', pages: 1, rows: -1 });
  useEffect(() => {
    if (!targetMessageId || openedTarget.current === targetMessageId) return;
    const target = logs.find((log) => log.message_id === targetMessageId);
    if (!target) {
      // A new link, or the pages started over (other filters): seek anew.
      if (
        seeking.current.target !== targetMessageId ||
        logs.length < seeking.current.rows
      )
        seeking.current = { target: targetMessageId, pages: 1, rows: -1 };
      const seek = seeking.current;
      if (loading || failed || !hasMore || logs.length === 0) return;
      if (seek.pages >= MAX_TARGET_PAGES || seek.rows === logs.length) return;
      seek.pages += 1;
      seek.rows = logs.length;
      setPage((prev) => prev + 1);
      return;
    }
    openedTarget.current = targetMessageId;
    setOpenLogId(target.id);
    const row = Array.from(
      listRef.current?.querySelectorAll<HTMLElement>('[data-log-id]') ?? [],
    ).find((element) => element.dataset.logId === target.id);
    revealElement(row, 'nearest');
  }, [logs, targetMessageId, loading, failed, hasMore, setPage]);

  const handleLogToggle = (logId: string) => {
    if (openLogId === logId) {
      setOpenLogId(null);
    } else {
      setOpenLogId(logId);
    }
  };

  // Loads the next page as the end of the list nears the screen.
  const sentinelRef = useScrollSentinel(
    () => setPage((prev) => prev + 1),
    !loading && hasMore && !failed,
    logs.length,
  );

  return (
    <div className="border-border bg-card h-[55svh] w-full overflow-hidden rounded-xl border font-mono">
      <div className="bg-muted flex h-8 flex-col items-start justify-center">
        <p className="text-foreground px-3 text-xs">
          {tableHeader ? tableHeader : t('settings.logs.tableHeader')}
        </p>
      </div>
      <div
        ref={listRef}
        className="relative flex h-[51svh] grow flex-col items-start gap-2 overflow-y-auto overscroll-contain bg-transparent p-4"
      >
        {!loading && failed && logs.length === 0 && (
          <EmptyState
            tone="destructive"
            size="xs"
            illustration="none"
            title={t('settings.logs.loadError')}
            onRetry={onRetry}
            className="w-full"
          />
        )}
        {!loading && !failed && logs.length === 0 && (
          <EmptyState
            size="xs"
            illustration="none"
            title={emptyTitle}
            className="w-full"
          />
        )}
        {logs?.map((log) => (
          <Log
            key={log.id}
            log={log}
            isOpen={openLogId === log.id}
            onToggle={handleLogToggle}
            onViewTrace={onViewTrace}
            tagNames={tagNames}
          />
        ))}
        <div ref={sentinelRef} aria-hidden="true" className="h-px w-full" />
        {loading && <SkeletonLoader component="logs" />}
        {!loading && failed && logs.length > 0 && (
          <LoadMoreStatus
            loading={false}
            error
            done={false}
            onRetry={onRetry}
            className="w-full"
          />
        )}
      </div>
    </div>
  );
}

function formatDuration(start?: string, end?: string): string | null {
  if (!start || !end) return null;
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (isNaN(ms) || ms < 0) return null;
  return formatDurationMs(ms);
}

function Log({
  log,
  isOpen,
  onToggle,
  onViewTrace,
  tagNames,
}: {
  log: LogData;
  isOpen: boolean;
  onToggle: (id: string) => void;
  onViewTrace: (ref: TraceRef) => void;
  tagNames: Record<string, string>;
}) {
  const { t } = useTranslation();
  const bodyId = useId();
  const clock = useClock(Boolean(log.running));
  const step = log.running ? workflowStep(log.workflow_progress) : null;
  // A failed workflow run keeps the step it was on (0053): say where it stopped.
  const failedStep =
    log.event_type === 'workflow' && log.status === 'failed'
      ? workflowStep(log.workflow_progress)
      : null;
  // The details mount on first open (a long list stays light), then stay so
  // closing can animate.
  const [opened, setOpened] = useState(isOpen);
  if (isOpen && !opened) setOpened(true);
  const logLevelColor = {
    info: 'text-success',
    error: 'text-destructive',
    warning: 'text-warning',
  };
  const filteredLog = Object.fromEntries(
    Object.entries(log).filter(([key]) => !COPY_OMITS.includes(key)),
  );

  const detailRows: [string, string][] = [];
  if (log.event_type === 'chat') {
    if (log.agent_id)
      detailRows.push([t('settings.logs.detail.agent'), log.agent_id]);
    if (log.tool_calls?.length)
      detailRows.push([
        t('settings.logs.detail.toolCalls'),
        String(log.tool_calls.length),
      ]);
    if (log.sources?.length)
      detailRows.push([
        t('settings.logs.detail.sources'),
        String(log.sources.length),
      ]);
    if (log.feedback?.text === 'like' || log.feedback?.text === 'dislike')
      detailRows.push([
        t('settings.logs.detail.feedback'),
        t(`settings.logs.feedback.${log.feedback.text}`),
      ]);
    const passthrough = Object.entries(log.passthrough ?? {});
    if (passthrough.length)
      detailRows.push([
        t('settings.logs.detail.passthrough'),
        passthrough.map(([key, value]) => `${key}=${value}`).join(', '),
      ]);
  } else if (log.event_type === 'schedule') {
    if (log.status)
      detailRows.push([t('settings.logs.detail.status'), log.status]);
    if (log.trigger_source)
      detailRows.push([t('settings.logs.detail.trigger'), log.trigger_source]);
    if (log.error_type)
      detailRows.push([t('settings.logs.detail.errorType'), log.error_type]);
    if (log.prompt_tokens || log.generated_tokens)
      detailRows.push([
        t('settings.logs.detail.tokens'),
        `${(log.prompt_tokens || 0) + (log.generated_tokens || 0)}`,
      ]);
    const duration = formatDuration(log.started_at, log.finished_at);
    if (duration)
      detailRows.push([t('settings.logs.detail.duration'), duration]);
    if (log.conversation_id)
      detailRows.push([
        t('settings.logs.detail.conversation'),
        log.conversation_id,
      ]);
  } else if (log.event_type === 'workflow') {
    if (log.workflow_name)
      detailRows.push([t('settings.logs.detail.workflow'), log.workflow_name]);
    if (log.status)
      detailRows.push([t('settings.logs.detail.status'), log.status]);
    const duration = formatDuration(log.started_at, log.finished_at);
    if (duration)
      detailRows.push([t('settings.logs.detail.duration'), duration]);
  } else if (log.event_type === 'system' || log.event_type === 'webhook') {
    if (log.endpoint)
      detailRows.push([t('settings.logs.detail.endpoint'), log.endpoint]);
  } else if (log.event_type === 'search' || log.event_type === 'graph') {
    if (log.source)
      detailRows.push([
        t('settings.logs.detail.source'),
        t(`settings.logs.trace.sources.${log.source}`, log.source),
      ]);
    if (log.status)
      detailRows.push([
        t('settings.logs.detail.status'),
        t(`settings.logs.trace.status.${log.status}`, log.status),
      ]);
  }

  const textBlocks: { label: string; text: string; isError?: boolean }[] = [];
  if (log.event_type === 'schedule' && log.instruction)
    textBlocks.push({
      label: t('settings.logs.detail.instruction'),
      text: log.instruction,
    });
  if (log.response)
    textBlocks.push({
      label: t('settings.logs.detail.response'),
      text: log.response,
    });
  if (log.output)
    textBlocks.push({
      label: t('settings.logs.detail.output'),
      text: log.output,
    });
  if (log.error)
    textBlocks.push({
      label: t('settings.logs.detail.error'),
      text: log.error,
      isError: true,
    });

  const jsonBlocks: { label: string; value: unknown }[] = [];
  if (log.tool_calls?.length)
    jsonBlocks.push({
      label: t('settings.logs.detail.toolCalls'),
      value: log.tool_calls,
    });
  if (log.sources?.length)
    jsonBlocks.push({
      label: t('settings.logs.detail.sources'),
      value: log.sources,
    });
  if (log.stacks?.length)
    jsonBlocks.push({
      label:
        log.event_type === 'webhook'
          ? t('settings.logs.detail.activity')
          : t('settings.logs.detail.error'),
      value: log.stacks,
    });
  if (log.steps?.length)
    jsonBlocks.push({
      label: t('settings.logs.detail.steps'),
      value: log.steps,
    });
  if (log.event_type === 'workflow' && log.result)
    jsonBlocks.push({
      label: t('settings.logs.detail.result'),
      value: log.result,
    });

  return (
    <div
      data-log-id={log.id}
      className={cn(
        'group w-full rounded-xl bg-transparent',
        !isOpen && 'hover:bg-accent',
      )}
    >
      <button
        type="button"
        aria-expanded={isOpen}
        aria-controls={bodyId}
        onClick={() => onToggle(log.id)}
        className={cn(
          'text-foreground focus-visible:ring-ring/50 flex w-full cursor-pointer flex-row items-start gap-2 rounded-xl p-2 px-4 py-3 text-left outline-none focus-visible:ring-3 focus-visible:ring-inset',
          isOpen && 'bg-secondary rounded-b-none',
        )}
      >
        <ChevronRight
          aria-hidden
          className={cn(
            'text-muted-foreground mt-[3px] size-3 transition-transform duration-200',
            isOpen && 'rotate-90',
          )}
        />
        <span className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="flex flex-row flex-wrap gap-2">
            <span className="text-muted-foreground text-xs">{`${log.timestamp}`}</span>
            {log.event_type && (
              <span className="text-muted-foreground text-xs">
                {t(`settings.logs.types.${log.event_type}`)}
              </span>
            )}
            {log.origin && (
              <span className="text-muted-foreground text-xs">
                {t(`settings.logs.origin.${log.origin}`)}
              </span>
            )}
            <span className="text-warning text-xs">{`[${log.action}]`}</span>
            {log.running && (
              <>
                <span className="text-info text-xs">
                  {t('settings.logs.running')}
                </span>
                {log.started_at && (
                  <span className="text-muted-foreground text-xs tabular-nums">
                    {formatElapsed(log.started_at, clock)}
                  </span>
                )}
                {step && (
                  <span className="text-muted-foreground text-xs">
                    {[
                      step.total
                        ? t('activity.now.stepOf', {
                            step: step.step,
                            total: step.total,
                          })
                        : t('activity.now.step', { step: step.step }),
                      step.title,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                )}
              </>
            )}
            {failedStep && (
              <>
                <span className="text-destructive text-xs">
                  {failedStep.total
                    ? t('settings.logs.failedAtStepOf', {
                        step: failedStep.step,
                        total: failedStep.total,
                      })
                    : t('settings.logs.failedAtStep', {
                        step: failedStep.step,
                      })}
                </span>
                {failedStep.title && (
                  <span className="text-muted-foreground text-xs">
                    {failedStep.title}
                  </span>
                )}
              </>
            )}
            {log.feedback?.text === 'like' && (
              <ThumbsUp
                className="text-success mt-[2px] size-3"
                aria-label={t('settings.logs.feedback.like')}
              />
            )}
            {log.feedback?.text === 'dislike' && (
              <ThumbsDown
                className="text-destructive mt-[2px] size-3"
                aria-label={t('settings.logs.feedback.dislike')}
              />
            )}
            {log.trace && (
              <span className="text-muted-foreground text-xs tabular-nums">
                {formatDurationMs(log.trace.duration_ms)}
              </span>
            )}
            <span
              className={cn(
                'min-w-0 flex-1 basis-60 font-sans text-xs wrap-break-word',
                logLevelColor[log.level],
              )}
            >
              {`${log.question}`.length > 250
                ? `${log.question.substring(0, 250)}...`
                : log.question}
            </span>
          </span>
          {/* The labels on a line of their own, so the header stays one line. */}
          <LabelChips labels={log.labels} tagNames={tagNames} />
        </span>
      </button>
      <Collapsible open={isOpen} id={bodyId}>
        {opened && (
          <div className="bg-secondary rounded-b-xl px-4 py-3">
            {log.trace && (
              <div className="flex flex-wrap items-center gap-2 px-2 pb-3">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => log.trace && onViewTrace(log.trace.ref)}
                >
                  <Activity />
                  {log.trace.count > 1
                    ? t('settings.logs.trace.viewRounds', {
                        count: log.trace.count,
                      })
                    : t('settings.logs.trace.view')}
                </Button>
                <TraceChips
                  durationMs={log.trace.duration_ms}
                  counts={log.trace.summary}
                />
              </div>
            )}
            {detailRows.length > 0 && (
              <DescriptionList size="xs" className="mx-2 mb-2">
                {detailRows.map(([label, value]) => (
                  <DescriptionItem key={label} label={label}>
                    {value}
                  </DescriptionItem>
                ))}
              </DescriptionList>
            )}
            {textBlocks.map((block) => (
              <div key={block.label} className="flex flex-col gap-1 px-2 pb-2">
                <p className="text-muted-foreground text-xs">{block.label}</p>
                <CodeBlock
                  surface="subtle"
                  tone={block.isError ? 'destructive' : 'default'}
                >
                  {block.text}
                </CodeBlock>
              </div>
            ))}
            {jsonBlocks.map((block) => (
              <div key={block.label} className="flex flex-col gap-1 px-2 pb-2">
                <p className="text-muted-foreground text-xs">{block.label}</p>
                <CodeBlock surface="subtle" maxHeight="md">
                  {JSON.stringify(block.value, null, 2)}
                </CodeBlock>
              </div>
            ))}
            <div className="my-px w-fit">
              <CopyButton
                textToCopy={JSON.stringify(filteredLog)}
                showText={true}
              />
            </div>
          </div>
        )}
      </Collapsible>
    </div>
  );
}
