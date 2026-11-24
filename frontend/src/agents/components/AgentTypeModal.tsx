import { ArrowRight, Bot, WandSparkles, Workflow } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import { Button } from '../../components/ui/button';
import { Modal } from '../../components/ui/modal';
import { OptionCard } from '../../components/ui/option-card';
import { Textarea } from '../../components/ui/textarea';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '../../components/ui/tooltip';
import { DRAFTER_USER_MESSAGE_CHARS } from '../../drafter/drafterApi';
import {
  DRAFTER_STARTERS,
  FEATURED_STARTERS,
  HAS_MORE_STARTERS,
} from '../../drafter/starters';
import { TemplatePicker } from '../../drafter/TemplatePicker';
import { useDrafterConfigFor } from '../../drafter/useDrafterConfig';
import { selectToken } from '../../preferences/preferenceSlice';
import { formatCount } from '../../utils/dateTimeUtils';
import { type DraftStart, draftStartState } from '../draftStart';
import { agentNewPath } from '../paths';

interface AgentTypeModalProps {
  isOpen: boolean;
  onClose: () => void;
  folderId?: string | null;
}

/**
 * The New agent modal. Where Draft with DocsGPT is on, it leads with a
 * description (Build) and the featured templates as chips, either opening the
 * new-agent form with the drafter already building from it, and keeps the
 * two blank starts (classic, workflow) as quiet footer buttons. Where it is
 * off, or not known yet, only the blank starts show, as OptionCards.
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
  // The Templates step, reached by All templates while there are more
  // templates than the featured chips.
  const [browsing, setBrowsing] = useState(false);

  const close = () => {
    setText('');
    setBrowsing(false);
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

  if (browsing)
    return (
      <Modal
        open={isOpen}
        onOpenChange={(o) => !o && close()}
        size="xl"
        onBack={() => setBrowsing(false)}
        title={t('drafter.templates.title')}
        description={t('drafter.templates.description', {
          count: DRAFTER_STARTERS.length,
          formatted: formatCount(DRAFTER_STARTERS.length),
        })}
      >
        <TemplatePicker onPick={(starter) => draft({ starter })} />
      </Modal>
    );

  const described = text.trim() !== '';
  const build = () => {
    if (described) draft({ text });
  };

  // The quiet blank starts: today's descriptions go in their tooltips.
  const blankButtons = (
    [
      ['normal', Bot, 'blankAgent', 'classicDescription'],
      ['workflow', Workflow, 'blankWorkflow', 'workflowDescription'],
    ] as const
  ).map(([type, Icon, label, hint]) => (
    <Tooltip key={type}>
      <TooltipTrigger asChild>
        <Button
          type="button"
          variant="ghost-muted"
          size="sm"
          shape="pill"
          onClick={() => handleSelect(type)}
        >
          <Icon />
          {t(`agents.typeModal.${label}`)}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{t(`agents.typeModal.${hint}`)}</TooltipContent>
    </Tooltip>
  ));

  return (
    <Modal
      open={isOpen}
      onOpenChange={(o) => !o && close()}
      title={t('agents.typeModal.newTitle')}
      description={t('agents.typeModal.draftDescription')}
      footer={
        <>
          {/* First in the DOM, so a phone's stacked footer puts Build on
              top and these under it. */}
          <div className="flex flex-wrap justify-center gap-1 sm:mr-auto sm:justify-start">
            {blankButtons}
          </div>
          <Button
            type="button"
            size="lg"
            shape="pill"
            disabled={!described}
            onClick={build}
          >
            <WandSparkles />
            {t('drafter.build')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Textarea
          size="lg"
          resize="none"
          maxLength={DRAFTER_USER_MESSAGE_CHARS}
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
              event.preventDefault();
              build();
            }
          }}
          aria-label={t('agents.typeModal.describeLabel')}
          placeholder={t('agents.typeModal.describePlaceholder')}
        />
        <div className="flex flex-col gap-2">
          <p className="text-muted-foreground text-xs">
            {t('agents.typeModal.templatesLabel')}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            {FEATURED_STARTERS.map(({ key, Icon }) => (
              <Button
                key={key}
                type="button"
                variant="outline"
                size="sm"
                shape="pill"
                data-template-chip={key}
                onClick={() => draft({ starter: key })}
              >
                <Icon className="text-muted-foreground" />
                {t(`drafter.starters.${key}.short`)}
              </Button>
            ))}
            {HAS_MORE_STARTERS && (
              <Button
                type="button"
                variant="link"
                size="inline"
                className="ml-1"
                onClick={() => setBrowsing(true)}
              >
                {t('drafter.templates.showAll')}
                <ArrowRight />
              </Button>
            )}
          </div>
        </div>
      </div>
    </Modal>
  );
}
