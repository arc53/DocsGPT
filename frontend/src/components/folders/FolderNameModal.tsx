import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { FormField } from '../ui/form-field';
import { Input } from '../ui/input';
import { Modal, ModalActions } from '../ui/modal';
import { folderErrorMessage } from './folderCopy';
import type { Folder, FolderType } from './types';
import { useFolderActions } from './useFolderActions';

/** The longest name the server takes. */
const MAX_NAME_LENGTH = 80;

export type FolderNameModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  type: FolderType;
  /** `create` a folder inside `parentId`, or `rename` `folder`. */
  mode: 'create' | 'rename';
  /** Where a new folder goes (null: the top level). */
  parentId?: string | null;
  /** The folder to rename. */
  folder?: Pick<Folder, 'id' | 'name'> | null;
  /** After the server saved it and the folder list reloaded. */
  onSaved?: (folder: Folder) => void;
};

/**
 * New folder and Rename: one labelled name field. The dialog waits for the
 * request (pending submit) and closes only once it worked; a refusal stays
 * under the field (a name already in use, too deep, a failed request).
 */
export default function FolderNameModal({
  open,
  onOpenChange,
  type,
  mode,
  parentId = null,
  folder,
  onSaved,
}: FolderNameModalProps) {
  const { t } = useTranslation();
  const actions = useFolderActions(type);
  const initialName = mode === 'rename' ? (folder?.name ?? '') : '';
  const [name, setName] = useState(initialName);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  // Bumped on every open and close; a request settling under an older one
  // (the dialog was closed meanwhile) is dropped.
  const generation = useRef(0);

  // Reset on open and close only: a rename reloads the folder list before it
  // resolves, and the new name must not count as a reopen.
  useEffect(() => {
    generation.current += 1;
    setName(initialName);
    setError(null);
    setPending(false);
  }, [open]);

  const trimmed = name.trim();
  const unchanged = mode === 'rename' && trimmed === folder?.name;

  const submit = async () => {
    if (!trimmed || pending) return;
    if (unchanged) {
      onOpenChange(false);
      return;
    }
    const issued = generation.current;
    setPending(true);
    setError(null);
    try {
      const saved =
        mode === 'create'
          ? await actions.create(trimmed, parentId)
          : await actions.rename(folder?.id ?? '', trimmed);
      if (issued !== generation.current) return;
      onOpenChange(false);
      onSaved?.(saved);
    } catch (reason) {
      if (issued !== generation.current) return;
      setPending(false);
      setError(folderErrorMessage(t, reason, 'folders.errors.saveFailed'));
    }
  };

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      size="sm"
      title={
        mode === 'create' ? t('folders.newFolder') : t('folders.renameTitle')
      }
      footer={
        <ModalActions
          cancelLabel={t('cancel')}
          onCancel={() => onOpenChange(false)}
          submitLabel={
            mode === 'create' ? t('folders.create') : t('folders.rename')
          }
          onSubmit={submit}
          pending={pending}
          disabled={!trimmed}
        />
      }
    >
      <FormField label={t('folders.name')} error={error ?? undefined}>
        <Input
          type="text"
          value={name}
          maxLength={MAX_NAME_LENGTH}
          onChange={(e) => {
            setName(e.target.value);
            if (error) setError(null);
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              submit();
            }
          }}
        />
      </FormField>
    </Modal>
  );
}
