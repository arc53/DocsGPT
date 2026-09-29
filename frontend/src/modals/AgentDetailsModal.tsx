import { envVar } from '@/env';
import { CircleX, ExternalLink } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import { Agent } from '../agents/types';
import userService from '../api/services/userService';
import CopyButton from '../components/CopyButton';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { Modal } from '../components/ui/modal';
import { SectionHeader } from '../components/ui/section-header';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import ConfirmationModal from './ConfirmationModal';

const baseURL = envVar('VITE_BASE_URL');

/** The backend's `message` on a refused call, else null. */
const errorMessage = async (response: Response): Promise<string | null> => {
  try {
    const body = await response.json();
    return typeof body?.message === 'string' && body.message.trim()
      ? body.message
      : null;
  } catch {
    return null;
  }
};

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
  // A failed generate or reset, shown in the modal until the next attempt.
  const [error, setError] = useState<string | null>(null);
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

  /**
   * Runs one of the modal's calls, showing its failure in the Alert.
   *
   * @param key Which button shows the spinner.
   * @param request The call; resolves to the response.
   * @param onSuccess Receives the parsed body of a successful response.
   */
  const run = async (
    key: 'publicLink' | 'apiKey' | 'webhook',
    request: () => Promise<Response>,
    onSuccess: (data: Record<string, string>) => void,
  ) => {
    setLoading(key, true);
    setError(null);
    try {
      const response = await request();
      if (!response.ok) {
        setError(
          (await errorMessage(response)) ??
            t('modals.agentDetails.actionFailed'),
        );
        return;
      }
      onSuccess(await response.json());
    } catch {
      setError(t('modals.agentDetails.actionFailed'));
    } finally {
      setLoading(key, false);
    }
  };

  const handleGeneratePublicLink = () =>
    run(
      'publicLink',
      () => userService.shareAgent({ id: agent.id ?? '', shared: true }, token),
      (data) => setSharedToken(data.shared_token),
    );

  const handleGenerateWebhook = () =>
    run(
      'webhook',
      () => userService.getAgentWebhook(agent.id ?? '', token),
      (data) => setWebhookUrl(data.webhook_url),
    );

  const handleRegenerateKey = () =>
    run(
      'apiKey',
      () => userService.regenerateAgentKey(agent.id ?? '', token),
      (data) => {
        setApiKey(data.key);
        onKeyRegenerated?.(data.key);
      },
    );

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
          {error && (
            <Alert variant="destructive" className="mt-6">
              <CircleX />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
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
                  <p className="text-foreground inline text-sm leading-normal font-medium wrap-anywhere">
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
                    <div className="text-foreground text-sm leading-normal font-medium wrap-anywhere">
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
              ) : agent.status === 'draft' ? (
                // A draft has no key yet: the first one is minted on publish.
                <p className="text-muted-foreground text-sm">
                  {t('modals.agentDetails.apiKeyAfterPublish')}
                </p>
              ) : (
                // No key shown on a published agent: minting one replaces
                // any key it has, so it goes through the reset confirmation.
                <Button
                  type="button"
                  variant="outline-primary"
                  shape="pill"
                  onClick={() => setResetKeyConfirmState('ACTIVE')}
                  loading={loadingStates.apiKey}
                >
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
                  <p className="text-foreground text-sm leading-normal font-medium wrap-anywhere">
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
