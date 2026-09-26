import { Bot, Workflow } from 'lucide-react';
import { agentNewPath } from '../paths';
import { useTranslation } from 'react-i18next';
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
  const { t } = useTranslation();
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
      title={t('agents.typeModal.title')}
      description={t('agents.typeModal.description')}
      size="md"
    >
      <div className="flex flex-col gap-4">
        <OptionCard
          icon={<Bot />}
          title={t('agents.typeModal.classicTitle')}
          description={t('agents.typeModal.classicDescription')}
          onClick={() => handleSelect('normal')}
        />
        <OptionCard
          icon={<Workflow />}
          title={t('agents.typeModal.workflowTitle')}
          description={t('agents.typeModal.workflowDescription')}
          onClick={() => handleSelect('workflow')}
        />
      </div>
    </Modal>
  );
}
