import React from 'react';
import { useTranslation } from 'react-i18next';

import WrapperModal from './WrapperModal';
import Input from '../components/Input';
import { ActiveState } from '../models/misc';
import { AvailableToolType } from './types';
import userService from '../api/services/userService';

interface ConfigToolModalProps {
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  tool: AvailableToolType | null;
  getUserTools: () => void;
}

export default function ConfigToolModal({
  modalState,
  setModalState,
  tool,
  getUserTools,
}: ConfigToolModalProps) {
  const { t } = useTranslation();
  const [authKey, setAuthKey] = React.useState<string>('');

  const handleAddTool = (tool: AvailableToolType) => {
    userService
      .createTool({
        name: tool.name,
        displayName: tool.displayName,
        description: tool.description,
        config: { token: authKey },
        actions: tool.actions,
        status: true,
      })
      .then(() => {
        setModalState('INACTIVE');
        getUserTools();
      });
  };

  // Only render when modal is active
  if (modalState !== 'ACTIVE') return null;

  return (
    <WrapperModal close={() => setModalState('INACTIVE')}>
      <div>
        <h2 className="font-semibold text-xl text-jet dark:text-bright-gray px-3">
          {t('modals.configTool.title')}
        </h2>
        <p className="mt-5 text-sm text-gray-600 dark:text-gray-400 px-3">
          {t('modals.configTool.type')}:{' '}
          <span className="font-semibold">{tool?.name}</span>
        </p>
        <div className="mt-6 px-3">
          <Input
            type="text"
            value={authKey}
            onChange={(e) => setAuthKey(e.target.value)}
            borderVariant="thin"
            placeholder={t('modals.configTool.apiKeyPlaceholder')}
            label={t('modals.configTool.apiKeyLabel')}
          />
        </div>
        <div className="mt-8 flex flex-row-reverse gap-1 px-3">
          <button
            onClick={() => {
              tool && handleAddTool(tool);
            }}
            className="rounded-3xl bg-purple-30 px-5 py-2 text-sm text-white transition-all hover:bg-[#6F3FD1]"
          >
            {t('modals.configTool.addButton')}
          </button>
          <button
            onClick={() => setModalState('INACTIVE')}
            className="cursor-pointer rounded-3xl px-5 py-2 text-sm font-medium hover:bg-gray-100 dark:bg-transparent dark:text-light-gray dark:hover:bg-[#767183]/50"
          >
            {t('modals.configTool.closeButton')}
          </button>
        </div>
      </div>
    </WrapperModal>
  );
}
