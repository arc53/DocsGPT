import { Bot, Workflow, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

interface AgentTypeModalProps {
  isOpen: boolean;
  onClose: () => void;
  folderId?: string | null;
}

export default function AgentTypeModal({
  isOpen,
  onClose,
  folderId,
}: AgentTypeModalProps) {
  const navigate = useNavigate();

  if (!isOpen) return null;

  const handleSelect = (type: 'normal' | 'workflow') => {
    if (type === 'workflow') {
      navigate(
        `/agents/workflow/new${folderId ? `?folder_id=${folderId}` : ''}`,
      );
    } else {
      navigate(`/agents/new${folderId ? `?folder_id=${folderId}` : ''}`);
    }
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-lg rounded-xl bg-white p-8 shadow-2xl dark:bg-[#1e1e1e]"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute top-5 right-5 text-gray-400 transition-colors hover:text-gray-600 dark:hover:text-gray-200"
        >
          <X size={20} />
        </button>

        <h2 className="text-jet dark:text-bright-gray mb-3 text-2xl font-bold">
          Create New Agent
        </h2>
        <p className="mb-8 text-sm text-gray-500 dark:text-gray-400">
          Choose the type of agent you want to create
        </p>

        <div className="flex flex-col gap-4">
          <button
            onClick={() => handleSelect('normal')}
            className="hover:border-purple-30 hover:bg-purple-30/5 dark:hover:border-purple-30 dark:hover:bg-purple-30/10 group flex items-start gap-5 rounded-xl border-2 border-gray-200 p-5 text-left transition-all dark:border-[#2E2F34]"
          >
            <div className="dark:bg-purple-30/20 bg-purple-30/10 text-purple-30 group-hover:bg-purple-30 flex h-14 w-14 shrink-0 items-center justify-center rounded-xl transition-colors group-hover:text-white dark:text-purple-300">
              <Bot size={28} />
            </div>
            <div className="flex-1">
              <h3 className="text-jet dark:text-bright-gray mb-2 text-lg font-semibold">
                Classic Agent
              </h3>
              <p className="text-sm leading-relaxed text-gray-600 dark:text-gray-400">
                Create a standard AI agent with a single model, tools, and
                knowledge sources
              </p>
            </div>
          </button>

          <button
            onClick={() => handleSelect('workflow')}
            className="hover:border-violets-are-blue hover:bg-violets-are-blue/5 dark:hover:border-violets-are-blue dark:hover:bg-violets-are-blue/10 group flex items-start gap-5 rounded-xl border-2 border-gray-200 p-5 text-left transition-all dark:border-[#2E2F34]"
          >
            <div className="dark:bg-violets-are-blue/20 bg-violets-are-blue/10 text-violets-are-blue group-hover:bg-violets-are-blue flex h-14 w-14 shrink-0 items-center justify-center rounded-xl transition-colors group-hover:text-white dark:text-purple-300">
              <Workflow size={28} />
            </div>
            <div className="flex-1">
              <h3 className="text-jet dark:text-bright-gray mb-2 text-lg font-semibold">
                Workflow Agent
              </h3>
              <p className="text-sm leading-relaxed text-gray-600 dark:text-gray-400">
                Design complex multi-step workflows with different models,
                conditional logic, and state management
              </p>
            </div>
          </button>
        </div>
      </div>
    </div>
  );
}
