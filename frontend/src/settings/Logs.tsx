import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';

import userService from '../api/services/userService';
import ChevronRight from '../assets/chevron-right.svg';
import CopyButton from '../components/CopyButton';
import Dropdown from '../components/Dropdown';
import SkeletonLoader from '../components/SkeletonLoader';
import { useLoaderState } from '../hooks';
import { APIKeyData, LogData } from './types';

export default function Logs() {
  const { t } = useTranslation();
  const [chatbots, setChatbots] = useState<APIKeyData[]>([]);
  const [selectedChatbot, setSelectedChatbot] = useState<APIKeyData | null>();
  const [logs, setLogs] = useState<LogData[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [loadingChatbots, setLoadingChatbots] = useLoaderState(true);
  const [loadingLogs, setLoadingLogs] = useLoaderState(true);

  const fetchChatbots = async () => {
    setLoadingChatbots(true);
    try {
      const response = await userService.getAPIKeys();
      if (!response.ok) {
        throw new Error('Failed to fetch Chatbots');
      }
      const chatbots = await response.json();
      setChatbots(chatbots);
    } catch (error) {
      console.error(error);
    } finally {
      setLoadingChatbots(false);
    }
  };

  const fetchLogs = async () => {
    setLoadingLogs(true);
    try {
      const response = await userService.getLogs({
        page: page,
        api_key_id: selectedChatbot?.id,
        page_size: 10,
      });
      if (!response.ok) {
        throw new Error('Failed to fetch logs');
      }
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
    fetchChatbots();
  }, []);

  useEffect(() => {
    if (hasMore) fetchLogs();
  }, [page, selectedChatbot]);

  return (
    <div className="mt-12">
      <div className="flex flex-col items-start">
        {loadingChatbots ? (
          <SkeletonLoader component="dropdown" />
        ) : (
          <div className="flex flex-col gap-3">
            <label
              id="chatbot-filter-label"
              className="font-bold text-jet dark:text-bright-gray"
            >
              {t('settings.logs.filterByChatbot')}
            </label>
            <Dropdown
              size="w-[55vw] sm:w-[360px]"
              options={[
                ...chatbots.map((chatbot) => ({
                  label: chatbot.name,
                  value: chatbot.id,
                })),
                { label: t('settings.logs.none'), value: '' },
              ]}
              placeholder={t('settings.logs.selectChatbot')}
              onSelect={(chatbot: { label: string; value: string }) => {
                setSelectedChatbot(
                  chatbots.find((item) => item.id === chatbot.value),
                );
                setLogs([]);
                setPage(1);
                setHasMore(true);
              }}
              selectedValue={
                (selectedChatbot && {
                  label: selectedChatbot.name,
                  value: selectedChatbot.id,
                }) ||
                null
              }
              rounded="3xl"
              border="border"
              darkBorderColor="dim-gray"
            />
          </div>
        )}
      </div>

      <div className="mt-8">
        <LogsTable logs={logs} setPage={setPage} loading={loadingLogs} />
      </div>
    </div>
  );
}

type LogsTableProps = {
  logs: LogData[];
  setPage: React.Dispatch<React.SetStateAction<number>>;
  loading: boolean;
};
function LogsTable({ logs, setPage, loading }: LogsTableProps) {
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
    <div className="logs-table rounded-xl h-[55vh] w-full overflow-hidden bg-white dark:bg-black">
      <div className="h-8 bg-black/10 dark:bg-[#191919] flex flex-col items-start justify-center">
        <p className="px-3 text-xs dark:text-gray-6000">
          {t('settings.logs.tableHeader')}
        </p>
      </div>
      <div className="flex flex-col items-start h-[51vh] overflow-y-auto bg-transparent flex-grow gap-2 p-4">
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
      className="group bg-transparent [&_summary::-webkit-details-marker]:hidden w-full hover:bg-[#F9F9F9] hover:dark:bg-dark-charcoal rounded-xl group-open:opacity-80 [&[open]]:border [&[open]]:border-[#d9d9d9]"
      onToggle={(e) => {
        if ((e.target as HTMLDetailsElement).open) {
          onToggle(log.id);
        }
      }}
    >
      <summary className="flex flex-row items-start gap-2 text-gray-900 cursor-pointer px-4 py-3 group-open:bg-[#F1F1F1] dark:group-open:bg-[#1B1B1B] group-open:rounded-t-xl p-2">
        <img
          src={ChevronRight}
          alt="Expand log entry"
          className="mt-[3px] w-3 h-3 transition duration-300 group-open:rotate-90"
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
      <div className="px-4 py-3 group-open:bg-[#F1F1F1] dark:group-open:bg-[#1B1B1B] group-open:rounded-b-xl">
        <p className="px-2 leading-relaxed text-gray-700 dark:text-gray-400 text-xs break-words">
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
