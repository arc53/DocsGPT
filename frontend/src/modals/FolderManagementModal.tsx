import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { ActiveState } from '../models/misc';
import WrapperModal from './WrapperModal';

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

  if (modalState !== 'ACTIVE') return null;

  return (
    <WrapperModal close={() => setModalState('INACTIVE')}>
      <div className="w-72">
        <h2 className="text-foreground dark:text-foreground mb-4 text-lg font-semibold">
          {mode === 'create'
            ? t('agents.folders.newFolder')
            : t('agents.folders.rename')}
        </h2>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={t('agents.folders.folderName')}
          autoFocus
          className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm outline-none dark:text-white"
        />
        <div className="mt-6 flex justify-end gap-2">
          <button
            onClick={() => {
              setModalState('INACTIVE');
              setName('');
            }}
            className="dark:text-foreground cursor-pointer rounded-3xl px-5 py-2 text-sm font-medium hover:bg-accent dark:hover:bg-accent"
          >
            {t('cancel')}
          </button>
          <button
            onClick={handleSubmit}
            disabled={!name.trim()}
            className="bg-primary hover:bg-primary/90 rounded-3xl px-5 py-2 text-sm text-white disabled:opacity-50"
          >
            {mode === 'create'
              ? t('agents.folders.createFolder')
              : t('agents.folders.rename')}
          </button>
        </div>
      </div>
    </WrapperModal>
  );
}
