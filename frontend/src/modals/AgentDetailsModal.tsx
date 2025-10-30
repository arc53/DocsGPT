import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import { Agent } from '../agents/types';
import userService from '../api/services/userService';
import CopyButton from '../components/CopyButton';
import Spinner from '../components/Spinner';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import WrapperModal from './WrapperModal';

const baseURL = import.meta.env.VITE_BASE_URL;

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
  const { t } = useTranslation();
  const token = useSelector(selectToken);

  const [sharedToken, setSharedToken] = useState<string | null>(
    agent.shared_token ?? null,
  );
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [webhookUrl, setWebhookUrl] = useState<string | null>(null);
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

  useEffect(() => {
    setSharedToken(agent.shared_token ?? null);
    setApiKey(agent.key ?? null);
  }, [agent]);

  if (modalState !== 'ACTIVE') return null;
  return (
    <WrapperModal
      className="sm:w-[512px]"
      close={() => {
        setModalState('INACTIVE');
      }}
    >
      <div>
        <h2 className="text-jet dark:text-bright-gray text-xl font-semibold">
          {t('modals.agentDetails.title')}
        </h2>
        <div className="mt-8 flex flex-col gap-6">
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
              <h2 className="text-jet dark:text-bright-gray text-base font-semibold">
                {t('modals.agentDetails.publicLink')}
              </h2>
            </div>
            {sharedToken ? (
              <div className="flex flex-col gap-2">
                <p className="font-roboto inline text-[14px] leading-normal font-medium break-all text-gray-700 dark:text-[#ECECF1]">
                  <a
                    href={`${baseURL}/shared/agent/${sharedToken}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {`${baseURL}/shared/agent/${sharedToken}`}
                  </a>
                  <CopyButton
                    textToCopy={`${baseURL}/shared/agent/${sharedToken}`}
                    padding="p-1"
                    className="absolute -mt-0.5 ml-1 inline-flex"
                  />
                </p>
                <a
                  href="https://docs.docsgpt.cloud/Agents/basics#core-components-of-an-agent"
                  className="text-purple-30 flex w-fit items-center gap-1 hover:underline"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <span className="text-sm">
                    {t('modals.agentDetails.learnMore')}
                  </span>
                  <img
                    src="/src/assets/external-link.svg"
                    alt="External link"
                    className="h-3 w-3"
                  />
                </a>
              </div>
            ) : (
              <button
                className="border-purple-30 text-purple-30 hover:bg-purple-30 flex w-28 items-center justify-center rounded-3xl border border-solid px-5 py-2 text-sm font-medium transition-colors hover:text-white"
                onClick={handleGeneratePublicLink}
              >
                {loadingStates.publicLink ? (
                  <Spinner size="small" color="#976af3" />
                ) : (
                  t('modals.agentDetails.generate')
                )}
              </button>
            )}
          </div>
          <div className="flex flex-col gap-3">
            <h2 className="text-jet dark:text-bright-gray text-base font-semibold">
              {t('modals.agentDetails.apiKey')}
            </h2>
            {apiKey ? (
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2">
                  <div className="font-roboto text-[14px] leading-normal font-medium break-all text-gray-700 dark:text-[#ECECF1]">
                    {apiKey}
                    {!apiKey.includes('...') && (
                      <CopyButton
                        textToCopy={apiKey}
                        padding="p-1"
                        className="absolute -mt-0.5 ml-1 inline-flex"
                      />
                    )}
                  </div>
                  {!apiKey.includes('...') && (
                    <a
                      href={`https://widget.docsgpt.cloud/?api-key=${apiKey}`}
                      className="group border-purple-30 text-purple-30 hover:bg-purple-30 ml-8 flex w-[101px] items-center justify-center gap-1 rounded-[62px] border py-1.5 text-sm font-medium transition-colors hover:text-white"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {t('modals.agentDetails.test')}
                      <img
                        src="/src/assets/external-link.svg"
                        alt="External link"
                        className="h-3 w-3 group-hover:brightness-0 group-hover:invert"
                      />
                    </a>
                  )}
                </div>
              </div>
            ) : (
              <button className="border-purple-30 text-purple-30 hover:bg-purple-30 w-28 rounded-3xl border border-solid px-5 py-2 text-sm font-medium transition-colors hover:text-white">
                {t('modals.agentDetails.generate')}
              </button>
            )}
          </div>
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
              <h2 className="text-jet dark:text-bright-gray text-base font-semibold">
                {t('modals.agentDetails.webhookUrl')}
              </h2>
            </div>
            {webhookUrl ? (
              <div className="flex flex-col gap-2">
                <p className="font-roboto text-[14px] leading-normal font-medium break-all text-gray-700 dark:text-[#ECECF1]">
                  <a href={webhookUrl} target="_blank" rel="noreferrer">
                    {webhookUrl}
                  </a>
                  <CopyButton
                    textToCopy={webhookUrl}
                    padding="p-1"
                    className="absolute -mt-0.5 ml-1 inline-flex"
                  />
                </p>
                <a
                  href="https://docs.docsgpt.cloud/Agents/basics#core-components-of-an-agent"
                  className="text-purple-30 flex w-fit items-center gap-1 hover:underline"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <span className="text-sm">
                    {t('modals.agentDetails.learnMore')}
                  </span>
                  <img
                    src="/src/assets/external-link.svg"
                    alt="External link"
                    className="h-3 w-3"
                  />
                </a>
              </div>
            ) : (
              <button
                className="border-purple-30 text-purple-30 hover:bg-purple-30 flex w-28 items-center justify-center rounded-3xl border border-solid px-5 py-2 text-sm font-medium transition-colors hover:text-white"
                onClick={handleGenerateWebhook}
              >
                {loadingStates.webhook ? (
                  <Spinner size="small" color="#976af3" />
                ) : (
                  t('modals.agentDetails.generate')
                )}
              </button>
            )}
          </div>
        </div>
      </div>
    </WrapperModal>
  );
}
