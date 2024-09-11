import React from 'react';

import userService from '../api/services/userService';
import ChevronRight from '../assets/chevron-right.svg';
import Dropdown from '../components/Dropdown';
import { APIKeyData, LogData } from './types';
import CoppyButton from '../components/CopyButton';

export default function Logs() {
  const [chatbots, setChatbots] = React.useState<APIKeyData[]>([]);
  const [selectedChatbot, setSelectedChatbot] =
    React.useState<APIKeyData | null>();
  const [logs, setLogs] = React.useState<LogData[]>([]);
  const [page, setPage] = React.useState(1);
  const [hasMore, setHasMore] = React.useState(true);

  const fetchChatbots = async () => {
    try {
      const response = await userService.getAPIKeys();
      if (!response.ok) {
        throw new Error('Failed to fetch Chatbots');
      }
      const chatbots = await response.json();
      setChatbots(chatbots);
    } catch (error) {
      console.error(error);
    }
  };

  const fetchLogs = async () => {
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
      setLogs([...logs, ...olderLogs.logs]);
      setHasMore(olderLogs.has_more);
    } catch (error) {
      console.error(error);
    }
  };

  React.useEffect(() => {
    fetchChatbots();
  }, []);

  React.useEffect(() => {
    if (hasMore) fetchLogs();
  }, [page, selectedChatbot]);
  return (
    <div className="mt-12">
      <div className="flex flex-col items-start">
        <div className="flex flex-col gap-3">
          <p className="font-bold text-jet dark:text-bright-gray">
            Filter by chatbot
          </p>
          <Dropdown
            size="w-[55vw] sm:w-[360px]"
            options={[
              ...chatbots.map((chatbot) => ({
                label: chatbot.name,
                value: chatbot.id,
              })),
              { label: 'None', value: '' },
            ]}
            placeholder="Select chatbot"
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
          />
        </div>
      </div>
      <div className="mt-8">
        <LogsTable logs={logs} setPage={setPage} />
      </div>
    </div>
  );
}

type LogsTableProps = {
  logs: LogData[];
  setPage: React.Dispatch<React.SetStateAction<number>>;
};

function LogsTable({ logs, setPage }: LogsTableProps) {
  const observerRef = React.useRef<any>();
  const firstObserver = React.useCallback((node: HTMLDivElement) => {
    if (observerRef.current) {
      observerRef.current = new IntersectionObserver((enteries) => {
        if (enteries[0].isIntersecting) setPage((prev) => prev + 1);
      });
    }
    if (node && observerRef.current) observerRef.current.observe(node);
  }, []);
  return (
    <div className="logs-table border rounded-2xl h-[55vh] w-full overflow-hidden border-silver dark:border-silver/40">
      <div className="h-8 bg-black/10 dark:bg-chinese-black flex flex-col items-start justify-center">
        <p className="px-3 text-xs dark:text-gray-6000">
          API generated / chatbot conversations
        </p>
      </div>
      <div
        ref={observerRef}
        className="flex flex-col items-start h-[51vh] overflow-y-auto bg-transparent flex-grow gap-px"
      >
        {logs.map((log, index) => {
          if (index === logs.length - 1) {
            return (
              <div ref={firstObserver} key={index}>
                <Log log={log} />
              </div>
            );
          } else return <Log key={index} log={log} />;
        })}
      </div>
    </div>
  );
}

function Log({ log }: { log: LogData }) {
  const logLevelColor = {
    info: 'text-green-500',
    error: 'text-red-500',
    warning: 'text-yellow-500',
  };
  const { id, action, timestamp, ...filteredLog } = log;
  return (
    <details className="group bg-transparent [&_summary::-webkit-details-marker]:hidden w-full hover:bg-[#F9F9F9] hover:dark:bg-dark-charcoal">
      <summary className="flex flex-row items-center gap-2 text-gray-900 cursor-pointer p-2 group-open:bg-[#F9F9F9] dark:group-open:bg-dark-charcoal">
        <img
          src={ChevronRight}
          alt="chevron-right"
          className="w-3 h-3 transition duration-300 group-open:rotate-90"
        />
        <span className="flex flex-row gap-2">
          <h2 className="text-xs text-black/60 dark:text-bright-gray">{`${log.timestamp}`}</h2>
          <h2 className="text-xs text-[#913400] dark:text-[#DF5200]">{`[${log.action}]`}</h2>
          <h2
            className={`text-xs ${logLevelColor[log.level]}`}
          >{`${log.question}`}</h2>
        </span>
      </summary>
      <div className="px-4 group-open:bg-[#F9F9F9] dark:group-open:bg-dark-charcoal">
        <p className="px-2 leading-relaxed text-gray-700 dark:text-gray-400 text-xs">
          {JSON.stringify(filteredLog, null, 2)}
        </p>
        <div className="my-px w-8">
          <CoppyButton
            text={JSON.stringify(filteredLog)}
            colorLight="transparent"
          />
        </div>
      </div>
    </details>
  );
}
