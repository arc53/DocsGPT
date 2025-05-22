import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import Input from '../components/Input';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import { AvailableToolType } from './types';
import WrapperModal from './WrapperModal';

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
  const token = useSelector(selectToken);
  const [authKey, setAuthKey] = React.useState<string>('');
  const [customName, setCustomName] = React.useState<string>('');

  const handleAddTool = (tool: AvailableToolType) => {
    userService
      .createTool(
        {
          name: tool.name,
          displayName: tool.displayName,
          description: tool.description,
          config: { token: authKey },
          customName: customName,
          actions: tool.actions,
          status: true,
        },
        token,
      )
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
        <h2 className="px-3 text-xl font-semibold text-jet dark:text-bright-gray">
          {t('modals.configTool.title')}
        </h2>
        <p className="mt-5 px-3 text-sm text-gray-600 dark:text-gray-400">
          {t('modals.configTool.type')}:{' '}
          <span className="font-semibold">{tool?.name}</span>
        </p>
        <div className="mt-6 px-3">
          <Input
            type="text"
            value={customName}
            onChange={(e) => setCustomName(e.target.value)}
            borderVariant="thin"
            placeholder="Enter custom name (optional)"
            labelBgClassName="bg-white dark:bg-charleston-green-2"
          />
        </div>
        <div className="mt-6 px-3">
          <Input
            type="text"
            value={authKey}
            onChange={(e) => setAuthKey(e.target.value)}
            borderVariant="thin"
            placeholder={t('modals.configTool.apiKeyPlaceholder')}
            labelBgClassName="bg-white dark:bg-charleston-green-2"
          />
        </div>
        <div className="mt-8 flex flex-row-reverse gap-1 px-3">
          <button
            onClick={() => {
              tool && handleAddTool(tool);
            }}
            className="rounded-3xl bg-purple-30 px-5 py-2 text-sm text-white transition-all hover:bg-violets-are-blue"
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
