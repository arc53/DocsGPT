import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Input } from '../components/ui/input';
import { Modal, ModalActions } from '../components/ui/modal';
import { ActiveState } from '../models/misc';

type FolderNameModalProps = {
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  mode: 'create' | 'rename';
  initialName?: string;
  onSubmit: (name: string) => void;
};

export default function FolderNameModal({
  modalState,
  setModalState,
  mode,
  initialName = '',
  onSubmit,
}: FolderNameModalProps) {
  const { t } = useTranslation();
  const [name, setName] = useState(initialName);

  useEffect(() => {
    if (modalState === 'ACTIVE') {
      setName(initialName);
    }
  }, [modalState, initialName]);

  const handleSubmit = () => {
    if (name.trim()) {
      onSubmit(name.trim());
      setModalState('INACTIVE');
      setName('');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSubmit();
    }
  };

  const handleCancel = () => {
    setModalState('INACTIVE');
    setName('');
  };

  return (
    <Modal
      open={modalState === 'ACTIVE'}
      onOpenChange={(open) => {
        if (!open) handleCancel();
      }}
      size="sm"
      title={
        mode === 'create'
          ? t('agents.folders.newFolder')
          : t('agents.folders.rename')
      }
      footer={
        <ModalActions
          cancelLabel={t('cancel')}
          onCancel={handleCancel}
          submitLabel={
            mode === 'create'
              ? t('agents.folders.createFolder')
              : t('agents.folders.rename')
          }
          onSubmit={handleSubmit}
          disabled={!name.trim()}
        />
      }
    >
      <Input
        type="text"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={t('agents.folders.folderName')}
        autoFocus
      />
    </Modal>
  );
}
