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
  const [logsByPage, setLogsByPage] = useState<Record<number, LogData[]>>({});
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [loadingLogs, setLoadingLogs] = useLoaderState(true);

  const logs = Object.values(logsByPage).flat();

  const fetchLogs = async () => {
    if (logsByPage[page] && logsByPage[page].length > 0) return;

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
      const data = await response.json();

      setLogsByPage((prev) => ({
        ...prev,
        [page]: data.logs,
      }));
      setHasMore(data.has_more);
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
    <div className="logs-table border-light-silver h-[55vh] w-full overflow-hidden rounded-xl border bg-white dark:border-transparent dark:bg-black">
      <div className="dark:bg-eerie-black-2 flex h-8 flex-col items-start justify-center bg-black/10">
        <p className="dark:text-gray-6000 px-3 text-xs">
          {tableHeader ? tableHeader : t('settings.logs.tableHeader')}
        </p>
      </div>
      <div className="relative flex h-[51vh] grow flex-col items-start gap-2 overflow-y-auto overscroll-contain bg-transparent p-4">
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
  const { id, action, timestamp, ...filteredLog } = log;

  return (
    <div className="group dark:hover:bg-dark-charcoal w-full rounded-xl bg-transparent hover:bg-[#F9F9F9]">
      <div
        onClick={() => onToggle(log.id)}
        className={`flex cursor-pointer flex-row items-start gap-2 p-2 px-4 py-3 text-gray-900 ${
          isOpen ? 'rounded-t-xl bg-[#F1F1F1] dark:bg-[#1B1B1B]' : ''
        }`}
      >
        <img
          src={ChevronRight}
          alt="Expand log entry"
          className={`mt-[3px] h-3 w-3 transition duration-300 ${isOpen ? 'rotate-90' : ''}`}
        />
        <span className="flex flex-row gap-2">
          <h2 className="dark:text-bright-gray text-xs text-black/60">{`${log.timestamp}`}</h2>
          <h2 className="text-xs text-[#913400] dark:text-[#DF5200]">{`[${log.action}]`}</h2>
          <h2
            className={`max-w-72 text-xs ${logLevelColor[log.level]} break-words`}
          >
            {`${log.question}`.length > 250
              ? `${log.question.substring(0, 250)}...`
              : log.question}
          </h2>
        </span>
      </div>
      {isOpen && (
        <div className="rounded-b-xl bg-[#F1F1F1] px-4 py-3 dark:bg-[#1B1B1B]">
          <div className="scrollbar-thin overflow-y-auto">
            <pre className="px-2 font-mono text-xs leading-relaxed break-words whitespace-pre-wrap text-gray-700 dark:text-gray-400">
              {JSON.stringify(filteredLog, null, 2)}
            </pre>
          </div>
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
