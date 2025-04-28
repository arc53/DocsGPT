import { useState } from 'react';
import { useSelector } from 'react-redux';

import { Agent } from '../agents/types';
import userService from '../api/services/userService';
import CopyButton from '../components/CopyButton';
import Spinner from '../components/Spinner';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import WrapperModal from './WrapperModal';

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
  const token = useSelector(selectToken);

  const [publicLink, setPublicLink] = useState<string | null>(null);
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

  if (modalState !== 'ACTIVE') return null;
  return (
    <WrapperModal
      className="sm:w-[512px]"
      close={() => {
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
            <div className="flex items-center gap-2">
              <h2 className="text-base font-semibold text-jet dark:text-bright-gray">
                Webhook URL
              </h2>
              {webhookUrl && (
                <div className="mb-1">
                  <CopyButton textToCopy={webhookUrl} padding="p-1" />
                </div>
              )}
            </div>
            {webhookUrl ? (
              <div className="flex flex-col flex-wrap items-start gap-2">
                <p className="f break-all font-mono text-sm text-gray-700 dark:text-[#ECECF1]">
                  {webhookUrl}
                </p>
              </div>
            ) : (
              <button
                className="hover:bg-vi</button>olets-are-blue flex w-28 items-center justify-center rounded-3xl border border-solid border-violets-are-blue px-5 py-2 text-sm font-medium text-violets-are-blue transition-colors hover:bg-violets-are-blue hover:text-white"
                onClick={handleGenerateWebhook}
              >
                {loadingStates.webhook ? (
                  <Spinner size="small" color="#976af3" />
                ) : (
                  'Generate'
                )}
              </button>
            )}
          </div>
        </div>
      </div>
    </WrapperModal>
  );
}
