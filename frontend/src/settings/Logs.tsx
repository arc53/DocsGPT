import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import ChevronRight from '../assets/chevron-right.svg';
import CopyButton from '../components/CopyButton';
import SkeletonLoader from '../components/SkeletonLoader';
import { useLoaderState } from '../hooks';
import { selectToken } from '../preferences/preferenceSlice';
import { LogData } from './types';

type LogsProps = {
  agentId?: string;
  tableHeader?: string;
};

export default function Logs({ agentId, tableHeader }: LogsProps) {
  const token = useSelector(selectToken);
  const [logs, setLogs] = useState<LogData[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [loadingLogs, setLoadingLogs] = useLoaderState(true);

  const fetchLogs = async () => {
    setLoadingLogs(true);
    try {
      const response = await userService.getLogs(
        {
          page: page,
          api_key_id: agentId,
          page_size: 10,
        },
        token,
      );
      if (!response.ok) throw new Error('Failed to fetch logs');
      const olderLogs = await response.json();
      setLogs((prevLogs) => [...prevLogs, ...olderLogs.logs]);
      setHasMore(olderLogs.has_more);
    } catch (error) {
      console.error(error);
    } finally {
      setLoadingLogs(false);
    }
  };

  useEffect(() => {
    if (hasMore) fetchLogs();
  }, [page, agentId]);
  return (
    <div className="mt-12">
      <div className="mt-8">
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
    if (openLogId && openLogId !== logId) {
      // If a different log is being opened, close the current one
      const currentOpenLog = document.getElementById(
        openLogId,
      ) as HTMLDetailsElement;
      if (currentOpenLog) {
        currentOpenLog.open = false;
      }
    }
    setOpenLogId(logId);
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
    <div className="logs-table h-[55vh] w-full overflow-hidden rounded-xl border border-light-silver bg-white dark:border-transparent dark:bg-black">
      <div className="flex h-8 flex-col items-start justify-center bg-black/10 dark:bg-[#191919]">
        <p className="px-3 text-xs dark:text-gray-6000">
          {tableHeader ? tableHeader : t('settings.logs.tableHeader')}
        </p>
      </div>
      <div className="flex h-[51vh] flex-grow flex-col items-start gap-2 overflow-y-auto bg-transparent p-4">
        {logs?.map((log, index) => {
          if (index === logs.length - 1) {
            return (
              <div ref={firstObserver} key={index} className="w-full">
                <Log log={log} onToggle={handleLogToggle} />
              </div>
            );
          } else
            return <Log key={index} log={log} onToggle={handleLogToggle} />;
        })}
        {loading && <SkeletonLoader component="logs" />}
      </div>
    </div>
  );
}
function Log({
  log,
  onToggle,
}: {
  log: LogData;
  onToggle: (id: string) => void;
}) {
  const { t } = useTranslation();
  const logLevelColor = {
    info: 'text-green-500',
    error: 'text-red-500',
    warning: 'text-yellow-500',
  };
  const { id, action, timestamp, ...filteredLog } = log;

  return (
    <details
      id={log.id}
      className="group w-full rounded-xl bg-transparent hover:bg-[#F9F9F9] group-open:opacity-80 hover:dark:bg-dark-charcoal [&[open]]:border [&[open]]:border-[#d9d9d9] [&_summary::-webkit-details-marker]:hidden"
      onToggle={(e) => {
        if ((e.target as HTMLDetailsElement).open) {
          onToggle(log.id);
        }
      }}
    >
      <summary className="flex cursor-pointer flex-row items-start gap-2 p-2 px-4 py-3 text-gray-900 group-open:rounded-t-xl group-open:bg-[#F1F1F1] dark:group-open:bg-[#1B1B1B]">
        <img
          src={ChevronRight}
          alt="Expand log entry"
          className="mt-[3px] h-3 w-3 transition duration-300 group-open:rotate-90"
        />
        <span className="flex flex-row gap-2">
          <h2 className="text-xs text-black/60 dark:text-bright-gray">{`${log.timestamp}`}</h2>
          <h2 className="text-xs text-[#913400] dark:text-[#DF5200]">{`[${log.action}]`}</h2>
          <h2
            className={`max-w-72 text-xs ${logLevelColor[log.level]} break-words`}
          >
            {`${log.question}`.length > 250
              ? `${log.question.substring(0, 250)}...`
              : log.question}
          </h2>
        </span>
      </summary>
      <div className="px-4 py-3 group-open:rounded-b-xl group-open:bg-[#F1F1F1] dark:group-open:bg-[#1B1B1B]">
        <p className="break-words px-2 text-xs leading-relaxed text-gray-700 dark:text-gray-400">
          {JSON.stringify(filteredLog, null, 2)}
        </p>
        <div className="my-px w-fit">
          <CopyButton
            text={JSON.stringify(filteredLog)}
            colorLight="transparent"
            showText={true}
          />
        </div>
      </div>
    </details>
  );
}
