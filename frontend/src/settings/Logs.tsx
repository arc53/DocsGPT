import { Activity, ChevronRight } from 'lucide-react';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import CopyButton from '../components/CopyButton';
import SearchInput from '../components/SearchInput';
import SkeletonLoader from '../components/SkeletonLoader';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import {
  DescriptionItem,
  DescriptionList,
} from '../components/ui/description-list';
import { EmptyState } from '../components/ui/empty-state';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { useLoaderState } from '../hooks';
import { cn } from '../lib/utils';
import { selectToken } from '../preferences/preferenceSlice';
import TraceChips from './traces/TraceChips';
import TraceSheet from './traces/TraceSheet';
import { formatDurationMs } from './traces/traceUtils';
import { LogData, TraceRef } from './types';

type LogsProps = {
  agentId?: string;
  tableHeader?: string;
};

export default function Logs({ agentId, tableHeader }: LogsProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const [logsByPage, setLogsByPage] = useState<Record<number, LogData[]>>({});
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [loadingLogs, setLoadingLogs] = useLoaderState(true);

  const [levelFilter, setLevelFilter] = useState('all');
  const [typeFilter, setTypeFilter] = useState('all');
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [openTrace, setOpenTrace] = useState<TraceRef | null>(null);

  const logs = Object.values(logsByPage).flat();

  // Identifies the filter combination a request was issued under, so a
  // slow response from a previous combination is discarded instead of
  // landing in the freshly reset cache.
  const filterKey = [agentId ?? '', levelFilter, typeFilter, search].join('|');
  const filterKeyRef = useRef(filterKey);
  filterKeyRef.current = filterKey;
  const isFirstRender = useRef(true);
  // Set synchronously by the reset effect so the fetch effect — which
  // runs later in the same commit, still seeing the pre-reset `page` —
  // skips that cycle instead of fetching a stale page under the new
  // filters (which could latch hasMore=false and freeze the list).
  const resetPendingRef = useRef(false);

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
    setLogsByPage({});
    setPage(1);
    setHasMore(true);
  }, [levelFilter, typeFilter, search, agentId]);

  const fetchLogs = async () => {
    if (logsByPage[page] && logsByPage[page].length > 0) return;

    const issuedKey = filterKey;
    const issuedPage = page;
    setLoadingLogs(true);
    try {
      const response = await userService.getLogs(
        {
          page: page,
          api_key_id: agentId,
          page_size: 10,
          level: levelFilter === 'all' ? undefined : levelFilter,
          event_type: typeFilter === 'all' ? undefined : typeFilter,
          search: search || undefined,
        },
        token,
      );
      if (!response.ok) throw new Error('Failed to fetch logs');
      const data = await response.json();
      if (issuedKey !== filterKeyRef.current || resetPendingRef.current) return;

      setLogsByPage((prev) => ({
        ...prev,
        [issuedPage]: data.logs,
      }));
      setHasMore(data.has_more);
    } catch (error) {
      console.error(error);
    } finally {
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
  }, [page, agentId, levelFilter, typeFilter, search, logsByPage]);

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
  ];

  return (
    <div>
      <p className="text-muted-foreground mb-5 text-sm leading-6">
        {t('settings.logs.subtitle')}
      </p>
      <div className="mb-3 flex flex-row flex-wrap items-center gap-3">
        <Select value={levelFilter} onValueChange={setLevelFilter}>
          <SelectTrigger className="w-[125px]" size="field" shape="pill">
            <SelectValue placeholder={t('settings.logs.levels.all')} />
          </SelectTrigger>
          <SelectContent>
            {levelOptions.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={typeFilter} onValueChange={setTypeFilter}>
          <SelectTrigger className="w-[140px]" size="field" shape="pill">
            <SelectValue placeholder={t('settings.logs.types.all')} />
          </SelectTrigger>
          <SelectContent>
            {typeOptions.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="w-56">
          <SearchInput
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            label={t('settings.logs.searchPlaceholder')}
          />
        </div>
      </div>
      <div>
        <LogsTable
          logs={logs}
          setPage={setPage}
          loading={loadingLogs}
          tableHeader={tableHeader}
          onViewTrace={setOpenTrace}
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

type LogsTableProps = {
  logs: LogData[];
  setPage: React.Dispatch<React.SetStateAction<number>>;
  loading: boolean;
  tableHeader?: string;
  onViewTrace: (ref: TraceRef) => void;
};
function LogsTable({
  logs,
  setPage,
  loading,
  tableHeader,
  onViewTrace,
}: LogsTableProps) {
  const { t } = useTranslation();
  const observerRef = useRef<IntersectionObserver | null>(null);
  const [openLogId, setOpenLogId] = useState<string | null>(null);

  const handleLogToggle = (logId: string) => {
    if (openLogId === logId) {
      setOpenLogId(null);
    } else {
      setOpenLogId(logId);
    }
  };

  const firstObserver = useCallback((node: HTMLDivElement | null) => {
    if (observerRef.current) {
      observerRef.current.disconnect();
    }

    if (!node) return;

    observerRef.current = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting) {
        setPage((prev) => prev + 1);
      }
    });

    observerRef.current.observe(node);
  }, []);

  useEffect(() => {
    return () => {
      if (observerRef.current) {
        observerRef.current.disconnect();
      }
    };
  }, []);

  return (
    <div className="border-border bg-card h-[55vh] w-full overflow-hidden rounded-xl border font-mono">
      <div className="bg-muted flex h-8 flex-col items-start justify-center">
        <p className="text-muted-foreground px-3 text-xs">
          {tableHeader ? tableHeader : t('settings.logs.tableHeader')}
        </p>
      </div>
      <div className="relative flex h-[51vh] grow flex-col items-start gap-2 overflow-y-auto overscroll-contain bg-transparent p-4">
        {!loading && logs.length === 0 && (
          <EmptyState
            size="xs"
            illustration="none"
            title={t('settings.logs.noLogs')}
            className="w-full"
          />
        )}
        {logs?.map((log, index) => {
          if (index === logs.length - 1) {
            return (
              <div ref={firstObserver} key={index} className="w-full">
                <Log
                  log={log}
                  isOpen={openLogId === log.id}
                  onToggle={handleLogToggle}
                  onViewTrace={onViewTrace}
                />
              </div>
            );
          } else
            return (
              <Log
                key={index}
                log={log}
                isOpen={openLogId === log.id}
                onToggle={handleLogToggle}
                onViewTrace={onViewTrace}
              />
            );
        })}
        {loading && <SkeletonLoader component="logs" />}
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
}: {
  log: LogData;
  isOpen: boolean;
  onToggle: (id: string) => void;
  onViewTrace: (ref: TraceRef) => void;
}) {
  const { t } = useTranslation();
  const logLevelColor = {
    info: 'text-success',
    error: 'text-destructive',
    warning: 'text-warning',
  };
  const { id, action, timestamp, event_type, ...filteredLog } = log;

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
    <div className="group hover:bg-accent w-full rounded-xl bg-transparent">
      <div
        role="button"
        tabIndex={0}
        aria-expanded={isOpen}
        onClick={() => onToggle(log.id)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onToggle(log.id);
          }
        }}
        className={cn(
          'text-foreground focus-visible:ring-ring/50 flex cursor-pointer flex-row items-start gap-2 p-2 px-4 py-3 outline-none focus-visible:ring-3 focus-visible:ring-inset',
          isOpen && 'bg-muted rounded-t-xl',
        )}
      >
        <ChevronRight
          className={cn(
            'text-muted-foreground mt-[3px] size-3 transition-transform duration-200',
            isOpen && 'rotate-90',
          )}
        />
        <span className="flex flex-row flex-wrap gap-2">
          <h2 className="text-muted-foreground text-xs">{`${log.timestamp}`}</h2>
          {log.event_type && (
            <h2 className="text-muted-foreground text-xs">
              {t(`settings.logs.types.${log.event_type}`)}
            </h2>
          )}
          <h2 className="text-warning text-xs">{`[${log.action}]`}</h2>
          {log.trace && (
            <h2 className="text-muted-foreground text-xs tabular-nums">
              {formatDurationMs(log.trace.duration_ms)}
            </h2>
          )}
          <h2
            className={cn(
              'max-w-72 text-xs wrap-break-word',
              logLevelColor[log.level],
            )}
          >
            {`${log.question}`.length > 250
              ? `${log.question.substring(0, 250)}...`
              : log.question}
          </h2>
        </span>
      </div>
      {isOpen && (
        <div className="bg-muted rounded-b-xl px-4 py-3">
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
              <Card variant="subtle" padding="sm">
                <pre
                  className={cn(
                    'font-mono text-xs leading-relaxed wrap-break-word whitespace-pre-wrap',
                    block.isError ? 'text-destructive' : 'text-foreground',
                  )}
                >
                  {block.text}
                </pre>
              </Card>
            </div>
          ))}
          {jsonBlocks.map((block) => (
            <div key={block.label} className="flex flex-col gap-1 px-2 pb-2">
              <p className="text-muted-foreground text-xs">{block.label}</p>
              <Card variant="subtle" padding="sm">
                <div className="scrollbar-overlay max-h-60 overflow-y-auto">
                  <pre className="text-foreground font-mono text-xs leading-relaxed wrap-break-word whitespace-pre-wrap">
                    {JSON.stringify(block.value, null, 2)}
                  </pre>
                </div>
              </Card>
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
    </div>
  );
}
