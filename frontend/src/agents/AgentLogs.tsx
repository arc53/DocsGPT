import { useNavigate, useParams } from 'react-router-dom';

import ArrowLeft from '../assets/arrow-left.svg';
import Analytics from '../settings/Analytics';
import Logs from '../settings/Logs';

export default function AgentLogs() {
  const navigate = useNavigate();
  const { agentId } = useParams();
  return (
    <div className="p-4 md:p-12">
      <div className="flex items-center gap-3 px-4">
        <button
          className="rounded-full border p-3 text-sm text-gray-400 dark:border-0 dark:bg-[#28292D] dark:text-gray-500 dark:hover:bg-[#2E2F34]"
          onClick={() => navigate('/agents')}
        >
          <img src={ArrowLeft} alt="left-arrow" className="h-3 w-3" />
        </button>
        <p className="mt-px text-sm font-semibold text-eerie-black dark:text-bright-gray">
          Back to all agents
        </p>
      </div>
      <div className="mt-5 flex w-full flex-wrap items-center justify-between gap-2 px-4">
        <h1 className="m-0 text-[40px] font-bold text-[#212121] dark:text-white">
          Agent Logs
        </h1>
      </div>
      <Analytics agentId={agentId} />
      <Logs agentId={agentId} tableHeader="Agent endpoint logs" />
    </div>
  );
}
