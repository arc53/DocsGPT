import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Modal } from '../components/ui/modal';
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
        <>
          <Button
            type="button"
            variant="ghost"
            onClick={handleCancel}
            className="rounded-3xl px-5"
          >
            {t('cancel')}
          </Button>
          <Button
            type="button"
            onClick={handleSubmit}
            disabled={!name.trim()}
            className="rounded-3xl px-5"
          >
            {mode === 'create'
              ? t('agents.folders.createFolder')
              : t('agents.folders.rename')}
          </Button>
        </>
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
