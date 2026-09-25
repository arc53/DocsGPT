import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Input } from '../components/ui/input';
import { Modal, ModalActions } from '../components/ui/modal';
import { ActiveState } from '../models/misc';

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

  const handleCancel = () => {
    setFunctionNameError(false);
    setModalState('INACTIVE');
    setActionName('');
  };

  return (
    <Modal
      open={modalState === 'ACTIVE'}
      onOpenChange={(open) => {
        if (!open) handleCancel();
      }}
      title={t('modals.addAction.title')}
      footer={
        <ModalActions
          cancelLabel={t('modals.configTool.closeButton')}
          onCancel={handleCancel}
          submitLabel={t('modals.addAction.addButton')}
          onSubmit={handleAddAction}
        />
      }
    >
      <div className="relative">
        <Input
          type="text"
          value={actionName}
          onChange={(e) => {
            const value = e.target.value;
            setActionName(value);
            setFunctionNameError(!isValidFunctionName(value));
          }}
          label={t('modals.addAction.actionNamePlaceholder')}
          required={true}
        />
        <p
          className={`mt-2 ml-1 text-xs italic ${
            functionNameError ? 'text-destructive' : 'text-muted-foreground'
          }`}
        >
          {functionNameError
            ? t('modals.addAction.invalidFormat')
            : t('modals.addAction.formatHelp')}
        </p>
      </div>
    </Modal>
  );
}
