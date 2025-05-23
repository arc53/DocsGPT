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
    <WrapperModal
      close={() => setModalState('INACTIVE')}
      className="sm:w-[512px]"
    >
      <div>
        <h2 className="px-3 text-xl font-semibold text-jet dark:text-bright-gray">
          New Action
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
            placeholder="Action Name"
            required={true}
          />
          <p
            className={`ml-1 mt-2 text-xs italic ${
              functionNameError ? 'text-red-500' : 'text-gray-500'
            }`}
          >
            {functionNameError
              ? 'Invalid function name format. Use only letters, numbers, underscores, and hyphens.'
              : 'Use only letters, numbers, underscores, and hyphens (e.g., `get_data`, `send_report`, etc.)'}
          </p>
        </div>
        <div className="mt-3 flex flex-row-reverse gap-1 px-3">
          <button
            onClick={handleAddAction}
            className="rounded-3xl bg-purple-30 px-5 py-2 text-sm text-white transition-all hover:bg-violets-are-blue"
          >
            Add
          </button>
          <button
            onClick={() => {
              setFunctionNameError(false);
              setModalState('INACTIVE');
              setActionName('');
            }}
            className="cursor-pointer rounded-3xl px-5 py-2 text-sm font-medium hover:bg-gray-100 dark:bg-transparent dark:text-light-gray dark:hover:bg-[#767183]/50"
          >
            {t('modals.configTool.closeButton')}
          </button>
        </div>
      </div>
    </WrapperModal>
  );
}
