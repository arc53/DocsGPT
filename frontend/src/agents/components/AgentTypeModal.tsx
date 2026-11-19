import { Bot, Workflow } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import { FormField } from '../../components/ui/form-field';
import { Modal } from '../../components/ui/modal';
import { OptionCard } from '../../components/ui/option-card';
import { SectionHeader } from '../../components/ui/section-header';
import { Textarea } from '../../components/ui/textarea';
import { DRAFTER_USER_MESSAGE_CHARS } from '../../drafter/drafterApi';
import { DRAFTER_STARTERS } from '../../drafter/starters';
import { useDrafterConfigFor } from '../../drafter/useDrafterConfig';
import { WandButton } from '../../drafter/WandButton';
import { selectToken } from '../../preferences/preferenceSlice';
import { type DraftStart, draftStartState } from '../draftStart';
import { agentNewPath } from '../paths';

interface AgentTypeModalProps {
  isOpen: boolean;
  onClose: () => void;
  folderId?: string | null;
}

/**
 * The New agent modal: the two blank starts (classic, workflow). Where Draft
 * with DocsGPT is on, it also takes a description or a starting point and
 * opens the new-agent form with the drafter already building from it; where
 * it is off, or not known yet, only the blank starts show.
 */
export default function AgentTypeModal({
  isOpen,
  onClose,
  folderId,
}: AgentTypeModalProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  // Read once the modal opens (and shared with every other wand), so a page
  // that only hosts the button asks nothing.
  const token = useSelector(selectToken);
  const drafting = useDrafterConfigFor(token, isOpen)?.enabled === true;
  const [text, setText] = useState('');

  const close = () => {
    setText('');
    onClose();
  };

  const handleSelect = (type: 'normal' | 'workflow') => {
    if (type === 'workflow') {
      navigate(agentNewPath({ workflow: true, folderId }));
    } else {
      navigate(agentNewPath({ folderId }));
    }
    close();
  };

  const draft = (start: DraftStart) => {
    navigate(agentNewPath({ folderId }), { state: draftStartState(start) });
    close();
  };

  const blank = (
    <>
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
    </>
  );

  if (!drafting)
    return (
      <Modal
        open={isOpen}
        onOpenChange={(o) => !o && close()}
        title={t('agents.typeModal.title')}
        description={t('agents.typeModal.description')}
      >
        <div className="flex flex-col gap-4">{blank}</div>
      </Modal>
    );

  return (
    <Modal
      open={isOpen}
      onOpenChange={(o) => !o && close()}
      size="lg"
      title={t('agents.typeModal.title')}
      description={t('agents.typeModal.draftDescription')}
    >
      <div className="flex flex-col gap-6">
        <section className="flex flex-col gap-3">
          <SectionHeader
            as="h3"
            size="xs"
            title={t('agents.typeModal.blankTitle')}
          />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">{blank}</div>
        </section>
        <section className="flex flex-col gap-3">
          <SectionHeader
            as="h3"
            size="xs"
            title={t('agents.typeModal.draftTitle')}
          />
          <FormField label={t('agents.typeModal.describeLabel')}>
            <Textarea
              size="lg"
              resize="none"
              maxLength={DRAFTER_USER_MESSAGE_CHARS}
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder={t('agents.typeModal.describePlaceholder')}
            />
          </FormField>
          <div className="flex justify-end">
            <WandButton
              mode="draft"
              onClick={() => draft(text.trim() ? { text } : {})}
            />
          </div>
          <div className="flex flex-col gap-3">
            {DRAFTER_STARTERS.map(({ key, Icon }) => (
              <OptionCard
                key={key}
                icon={<Icon />}
                title={t(`drafter.starters.${key}.title`)}
                description={t(`drafter.starters.${key}.description`)}
                onClick={() => draft({ starter: key })}
              />
            ))}
          </div>
        </section>
      </div>
    </Modal>
  );
}
