import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import ChevronRight from '../assets/chevron-right.svg';
import CopyButton from '../components/CopyButton';
import SkeletonLoader from '../components/SkeletonLoader';
import { Input } from '../components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { useLoaderState } from '../hooks';
import { selectToken } from '../preferences/preferenceSlice';
import { LogData } from './types';

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

  const logs = Object.values(logsByPage).flat();

  // Identifies the filter combination a request was issued under, so a
  // slow response from a previous combination is discarded instead of
  // landing in the freshly reset cache.
  const filterKey = [agentId ?? '', levelFilter, typeFilter, search].join('|');
  const filterKeyRef = useRef(filterKey);
  filterKeyRef.current = filterKey;
  const isFirstRender = useRef(true);

  useEffect(() => {
    const handle = setTimeout(() => setSearch(searchInput.trim()), 400);
    return () => clearTimeout(handle);
  }, [searchInput]);

  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    setLogsByPage({});
    setPage(1);
    setHasMore(true);
  }, [levelFilter, typeFilter, search, agentId]);

  const fetchLogs = async () => {
    if (logsByPage[page] && logsByPage[page].length > 0) return;

    const issuedKey = filterKey;
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
      if (issuedKey !== filterKeyRef.current) return;

      setLogsByPage((prev) => ({
        ...prev,
        [page]: data.logs,
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
  ];

  return (
    <div className="mt-8">
      <p className="text-muted-foreground mb-5 text-sm leading-6">
        {t('settings.logs.subtitle')}
      </p>
      <div className="mb-3 flex flex-row flex-wrap items-center gap-3">
        <Select value={levelFilter} onValueChange={setLevelFilter}>
          <SelectTrigger
            className="w-[125px] rounded-3xl px-5 py-3 text-sm"
            size="lg"
          >
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
          <SelectTrigger
            className="w-[140px] rounded-3xl px-5 py-3 text-sm"
            size="lg"
          >
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
        <Input
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder={t('settings.logs.searchPlaceholder')}
          className="w-56 rounded-3xl"
        />
      </div>
      <div>
        <LogsTable
          logs={logs}
          setPage={setPage}
          loading={loadingLogs}
          tableHeader={tableHeader}
        />
      </div>
    </div>
  );
}

type LogsTableProps = {
  logs: LogData[];
  setPage: React.Dispatch<React.SetStateAction<number>>;
  loading: boolean;
  tableHeader?: string;
};
function LogsTable({ logs, setPage, loading, tableHeader }: LogsTableProps) {
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
    <div className="logs-table border-border bg-card h-[55vh] w-full overflow-hidden rounded-xl border dark:bg-black">
      <div className="flex h-8 flex-col items-start justify-center bg-black/10 dark:bg-white/5">
        <p className="text-muted-foreground px-3 text-xs">
          {tableHeader ? tableHeader : t('settings.logs.tableHeader')}
        </p>
      </div>
      <div className="relative flex h-[51vh] grow flex-col items-start gap-2 overflow-y-auto overscroll-contain bg-transparent p-4">
        {!loading && logs.length === 0 && (
          <p className="text-muted-foreground w-full py-4 text-center text-xs">
            {t('settings.logs.noLogs')}
          </p>
        )}
        {logs?.map((log, index) => {
          if (index === logs.length - 1) {
            return (
              <div ref={firstObserver} key={index} className="w-full">
                <Log
                  log={log}
                  isOpen={openLogId === log.id}
                  onToggle={handleLogToggle}
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
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

function Log({
  log,
  isOpen,
  onToggle,
}: {
  log: LogData;
  isOpen: boolean;
  onToggle: (id: string) => void;
}) {
  const { t } = useTranslation();
  const logLevelColor = {
    info: 'text-green-500',
    error: 'text-red-500',
    warning: 'text-yellow-500',
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
    <div className="group dark:hover:bg-accent hover:bg-muted w-full rounded-xl bg-transparent">
      <div
        onClick={() => onToggle(log.id)}
        className={`text-foreground flex cursor-pointer flex-row items-start gap-2 p-2 px-4 py-3 ${
          isOpen ? 'dark:bg-background rounded-t-xl bg-[#F1F1F1]' : ''
        }`}
      >
        <img
          src={ChevronRight}
          alt="Expand log entry"
          className={`mt-[3px] h-3 w-3 transition duration-300 ${isOpen ? 'rotate-90' : ''}`}
        />
        <span className="flex flex-row flex-wrap gap-2">
          <h2 className="dark:text-foreground text-xs text-black/60">{`${log.timestamp}`}</h2>
          {log.event_type && (
            <h2 className="text-muted-foreground text-xs">
              {t(`settings.logs.types.${log.event_type}`)}
            </h2>
          )}
          <h2 className="text-xs text-[#913400] dark:text-orange-500">{`[${log.action}]`}</h2>
          <h2
            className={`max-w-72 text-xs ${logLevelColor[log.level]} wrap-break-word`}
          >
            {`${log.question}`.length > 250
              ? `${log.question.substring(0, 250)}...`
              : log.question}
          </h2>
        </span>
      </div>
      {isOpen && (
        <div className="dark:bg-background rounded-b-xl bg-[#F1F1F1] px-4 py-3">
          {detailRows.length > 0 && (
            <div className="flex flex-col gap-1 px-2 pb-2">
              {detailRows.map(([label, value]) => (
                <div key={label} className="flex flex-row gap-2 text-xs">
                  <span className="text-muted-foreground w-28 shrink-0">
                    {label}
                  </span>
                  <span className="text-foreground wrap-break-word">
                    {value}
                  </span>
                </div>
              ))}
            </div>
          )}
          {textBlocks.map((block) => (
            <div key={block.label} className="px-2 pb-2">
              <p className="text-muted-foreground text-xs">{block.label}</p>
              <pre
                className={`font-mono text-xs leading-relaxed wrap-break-word whitespace-pre-wrap ${
                  block.isError
                    ? 'text-red-500'
                    : 'text-gray-700 dark:text-gray-400'
                }`}
              >
                {block.text}
              </pre>
            </div>
          ))}
          {jsonBlocks.map((block) => (
            <div key={block.label} className="px-2 pb-2">
              <p className="text-muted-foreground text-xs">{block.label}</p>
              <div className="scrollbar-overlay max-h-60 overflow-y-auto">
                <pre className="font-mono text-xs leading-relaxed wrap-break-word whitespace-pre-wrap text-gray-700 dark:text-gray-400">
                  {JSON.stringify(block.value, null, 2)}
                </pre>
              </div>
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
