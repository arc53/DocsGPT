import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';

import Input from '../components/Input';
import { ActiveState } from '../models/misc';
import WrapperModal from './WrapperModal';

type AddActionModalProps = {
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  handleSubmit: (actionName: string) => void;
};

const isValidFunctionName = (name: string): boolean => {
  const pattern = /^[a-zA-Z0-9_-]+$/;
  return pattern.test(name);
};

export default function AddActionModal({
  modalState,
  setModalState,
  handleSubmit,
}: AddActionModalProps) {
  const { t } = useTranslation();
  const [actionName, setActionName] = React.useState('');
  const [functionNameError, setFunctionNameError] = useState<boolean>(false);

  const handleAddAction = () => {
    if (!isValidFunctionName(actionName)) {
      setFunctionNameError(true);
      return;
    }
    setFunctionNameError(false);
    handleSubmit(actionName);
    setActionName('');
    setModalState('INACTIVE');
  };

  if (modalState !== 'ACTIVE') return null;
  return (
    <WrapperModal close={() => setModalState('INACTIVE')} className="sm:w-lg">
      <div>
        <h2 className="text-jet dark:text-bright-gray px-3 text-xl font-semibold">
          {t('modals.addAction.title')}
        </h2>
        <div className="relative mt-6 px-3">
          <Input
            type="text"
            value={actionName}
            onChange={(e) => {
              const value = e.target.value;
              setActionName(value);
              setFunctionNameError(!isValidFunctionName(value));
            }}
            borderVariant="thin"
            labelBgClassName="bg-white dark:bg-charleston-green-2"
            placeholder={t('modals.addAction.actionNamePlaceholder')}
            required={true}
          />
          <p
            className={`mt-2 ml-1 text-xs italic ${
              functionNameError ? 'text-red-500' : 'text-gray-500'
            }`}
          >
            {functionNameError
              ? t('modals.addAction.invalidFormat')
              : t('modals.addAction.formatHelp')}
          </p>
        </div>
        <div className="mt-3 flex flex-row-reverse gap-1 px-3">
          <button
            onClick={handleAddAction}
            className="bg-purple-30 hover:bg-violets-are-blue rounded-3xl px-5 py-2 text-sm text-white transition-all"
          >
            {t('modals.addAction.addButton')}
          </button>
          <button
            onClick={() => {
              setFunctionNameError(false);
              setModalState('INACTIVE');
              setActionName('');
            }}
            className="dark:text-light-gray cursor-pointer rounded-3xl px-5 py-2 text-sm font-medium hover:bg-gray-100 dark:bg-transparent dark:hover:bg-[#767183]/50"
          >
            {t('modals.configTool.closeButton')}
          </button>
        </div>
      </div>
    </WrapperModal>
  );
}
