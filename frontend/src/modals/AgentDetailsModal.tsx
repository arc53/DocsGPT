import { envVar } from '@/env';
import { ExternalLink } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import { Agent } from '../agents/types';
import userService from '../api/services/userService';
import CopyButton from '../components/CopyButton';
import { Button } from '../components/ui/button';
import { Modal } from '../components/ui/modal';
import { SectionHeader } from '../components/ui/section-header';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import ConfirmationModal from './ConfirmationModal';

const baseURL = envVar('VITE_BASE_URL');

type AgentDetailsModalProps = {
  agent: Agent;
  mode: 'new' | 'edit' | 'draft';
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  onKeyRegenerated?: (key: string) => void;
};

export default function AgentDetailsModal({
  agent,
  mode,
  modalState,
  setModalState,
  onKeyRegenerated,
}: AgentDetailsModalProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);

  const [sharedToken, setSharedToken] = useState<string | null>(
    agent.shared_token ?? null,
  );
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [webhookUrl, setWebhookUrl] = useState<string | null>(null);
  const [resetKeyConfirmState, setResetKeyConfirmState] =
    useState<ActiveState>('INACTIVE');
  const [loadingStates, setLoadingStates] = useState({
    publicLink: false,
    apiKey: false,
    webhook: false,
  });

  const setLoading = (
    key: 'publicLink' | 'apiKey' | 'webhook',
    state: boolean,
  ) => {
    setLoadingStates((prev) => ({ ...prev, [key]: state }));
  };

  const handleGeneratePublicLink = async () => {
    setLoading('publicLink', true);
    const response = await userService.shareAgent(
      { id: agent.id ?? '', shared: true },
      token,
    );
    if (!response.ok) {
      setLoading('publicLink', false);
      return;
    }
    const data = await response.json();
    setSharedToken(data.shared_token);
    setLoading('publicLink', false);
  };

  const handleGenerateWebhook = async () => {
    setLoading('webhook', true);
    const response = await userService.getAgentWebhook(agent.id ?? '', token);
    if (!response.ok) {
      setLoading('webhook', false);
      return;
    }
    const data = await response.json();
    setWebhookUrl(data.webhook_url);
    setLoading('webhook', false);
  };

  const handleRegenerateKey = async () => {
    setLoading('apiKey', true);
    try {
      const response = await userService.regenerateAgentKey(
        agent.id ?? '',
        token,
      );
      if (!response.ok) return;
      const data = await response.json();
      setApiKey(data.key);
      onKeyRegenerated?.(data.key);
    } finally {
      setLoading('apiKey', false);
    }
  };

  useEffect(() => {
    setSharedToken(agent.shared_token ?? null);
    setApiKey(agent.key ?? null);
  }, [agent]);

  return (
    <>
      <Modal
        open={modalState === 'ACTIVE'}
        onOpenChange={(o) => !o && setModalState('INACTIVE')}
        title={t('modals.agentDetails.title')}
        size="md"
      >
        <div>
          <div className="mt-8 flex flex-col gap-6">
            <div className="flex flex-col gap-3">
              <div className="flex items-center gap-2">
                <SectionHeader
                  as="h3"
                  size="xs"
                  title={t('modals.agentDetails.publicLink')}
                />
              </div>
              {sharedToken ? (
                <div className="flex flex-col gap-2">
                  <p className="text-foreground inline text-sm leading-normal font-medium break-all">
                    <a
                      href={`${baseURL}/shared/agent/${sharedToken}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {`${baseURL}/shared/agent/${sharedToken}`}
                    </a>
                    <CopyButton
                      textToCopy={`${baseURL}/shared/agent/${sharedToken}`}
                      size="xs"
                      className="absolute -mt-0.5 ml-1 inline-flex"
                    />
                  </p>
                  <Button
                    variant="link"
                    size="inline"
                    asChild
                    className="w-fit"
                  >
                    <a
                      href="https://docs.docsgpt.cloud/Agents/basics#core-components-of-an-agent"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {t('modals.agentDetails.learnMore')}
                      <ExternalLink className="size-3" />
                    </a>
                  </Button>
                </div>
              ) : (
                <Button
                  type="button"
                  variant="outline-primary"
                  shape="pill"
                  onClick={handleGeneratePublicLink}
                  loading={loadingStates.publicLink}
                >
                  {t('modals.agentDetails.generate')}
                </Button>
              )}
            </div>
            <div className="flex flex-col gap-3">
              <SectionHeader
                as="h3"
                size="xs"
                title={t('modals.agentDetails.apiKey')}
              />
              {apiKey ? (
                <div className="flex flex-col gap-2">
                  <div className="flex items-center gap-2">
                    <div className="text-foreground text-sm leading-normal font-medium break-all">
                      {apiKey}
                      {!apiKey.includes('...') && (
                        <CopyButton
                          textToCopy={apiKey}
                          size="xs"
                          className="absolute -mt-0.5 ml-1 inline-flex"
                        />
                      )}
                    </div>
                    {!apiKey.includes('...') && (
                      <Button
                        asChild
                        variant="outline-primary"
                        size="sm"
                        shape="pill"
                        className="group ml-8 w-[101px]"
                      >
                        <a
                          href={`https://widget.docsgpt.cloud/?api-key=${apiKey}`}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {t('modals.agentDetails.test')}
                          <ExternalLink />
                        </a>
                      </Button>
                    )}
                    {apiKey.includes('...') && (
                      <Button
                        type="button"
                        onClick={() => setResetKeyConfirmState('ACTIVE')}
                        loading={loadingStates.apiKey}
                        variant="outline-primary"
                        size="sm"
                        shape="pill"
                        className="ml-8"
                      >
                        {t('modals.agentDetails.resetKey')}
                      </Button>
                    )}
                  </div>
                </div>
              ) : (
                <Button type="button" variant="outline-primary" shape="pill">
                  {t('modals.agentDetails.generate')}
                </Button>
              )}
            </div>
            <div className="flex flex-col gap-3">
              <div className="flex items-center gap-2">
                <SectionHeader
                  as="h3"
                  size="xs"
                  title={t('modals.agentDetails.webhookUrl')}
                />
              </div>
              {webhookUrl ? (
                <div className="flex flex-col gap-2">
                  <p className="text-foreground text-sm leading-normal font-medium break-all">
                    <a href={webhookUrl} target="_blank" rel="noreferrer">
                      {webhookUrl}
                    </a>
                    <CopyButton
                      textToCopy={webhookUrl}
                      size="xs"
                      className="absolute -mt-0.5 ml-1 inline-flex"
                    />
                  </p>
                  <Button
                    variant="link"
                    size="inline"
                    asChild
                    className="w-fit"
                  >
                    <a
                      href="https://docs.docsgpt.cloud/Agents/basics#core-components-of-an-agent"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {t('modals.agentDetails.learnMore')}
                      <ExternalLink className="size-3" />
                    </a>
                  </Button>
                </div>
              ) : (
                <Button
                  type="button"
                  variant="outline-primary"
                  shape="pill"
                  onClick={handleGenerateWebhook}
                  loading={loadingStates.webhook}
                >
                  {t('modals.agentDetails.generate')}
                </Button>
              )}
            </div>
          </div>
        </div>
      </Modal>
      <ConfirmationModal
        message={t('modals.agentDetails.resetKeyConfirm')}
        modalState={resetKeyConfirmState}
        setModalState={setResetKeyConfirmState}
        submitLabel={t('modals.agentDetails.resetKey')}
        handleSubmit={handleRegenerateKey}
        variant="destructive"
      />
    </>
  );
}
