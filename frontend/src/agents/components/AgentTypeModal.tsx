import { Bot, Workflow } from 'lucide-react';
import { agentNewPath } from '../paths';
import { useNavigate } from 'react-router-dom';

import { Modal } from '../../components/ui/modal';
import { OptionCard } from '../../components/ui/option-card';

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

  const handleSelect = (type: 'normal' | 'workflow') => {
    if (type === 'workflow') {
      navigate(agentNewPath({ workflow: true, folderId }));
    } else {
      navigate(agentNewPath({ folderId }));
    }
    onClose();
  };

  return (
    <Modal
      open={isOpen}
      onOpenChange={(o) => !o && onClose()}
      title="Create New Agent"
      description="Choose the type of agent you want to create"
      size="md"
    >
      <div className="flex flex-col gap-4">
        <OptionCard
          icon={<Bot />}
          title="Classic Agent"
          description="Create a standard AI agent with a single model, tools, and knowledge sources"
          onClick={() => handleSelect('normal')}
        />
        <OptionCard
          icon={<Workflow />}
          title="Workflow Agent"
          description="Design complex multi-step workflows with different models, conditional logic, and state management"
          onClick={() => handleSelect('workflow')}
        />
      </div>
    </Modal>
  );
}
