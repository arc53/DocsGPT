import { Agent } from '../agents/types';
import { ActiveState } from '../models/misc';
import WrapperModal from './WrapperModal';
import { useNavigate } from 'react-router-dom';

type AgentDetailsModalProps = {
  agent: Agent;
  mode: 'new' | 'edit' | 'draft';
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
};

export default function AgentDetailsModal({
  agent,
  mode,
  modalState,
  setModalState,
}: AgentDetailsModalProps) {
  const navigate = useNavigate();
  if (modalState !== 'ACTIVE') return null;
  return (
    <WrapperModal
      className="sm:w-[512px]"
      close={() => {
        if (mode === 'new') navigate('/agents');
        setModalState('INACTIVE');
      }}
    >
      <div>
        <h2 className="text-xl font-semibold text-jet dark:text-bright-gray">
          Access Details
        </h2>
        <div className="mt-8 flex flex-col gap-6">
          <div className="flex flex-col gap-3">
            <h2 className="text-base font-semibold text-jet dark:text-bright-gray">
              Public link
            </h2>
            <button className="hover:bg-vi</button>olets-are-blue w-28 rounded-3xl border border-solid border-violets-are-blue px-5 py-2 text-sm font-medium text-violets-are-blue transition-colors hover:bg-violets-are-blue hover:text-white">
              Generate
            </button>
          </div>
          <div className="flex flex-col gap-3">
            <h2 className="text-base font-semibold text-jet dark:text-bright-gray">
              API Key
            </h2>
            {agent.key ? (
              <span className="font-mono text-sm text-gray-700 dark:text-[#ECECF1]">
                {agent.key}
              </span>
            ) : (
              <button className="hover:bg-vi</button>olets-are-blue w-28 rounded-3xl border border-solid border-violets-are-blue px-5 py-2 text-sm font-medium text-violets-are-blue transition-colors hover:bg-violets-are-blue hover:text-white">
                Generate
              </button>
            )}
          </div>
          <div className="flex flex-col gap-3">
            <h2 className="text-base font-semibold text-jet dark:text-bright-gray">
              Webhooks
            </h2>
            <button className="hover:bg-vi</button>olets-are-blue w-28 rounded-3xl border border-solid border-violets-are-blue px-5 py-2 text-sm font-medium text-violets-are-blue transition-colors hover:bg-violets-are-blue hover:text-white">
              Generate
            </button>
          </div>
        </div>
      </div>
    </WrapperModal>
  );
}
