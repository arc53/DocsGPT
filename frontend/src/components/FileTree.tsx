import React, { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import userService from '../api/services/userService';
import { Trash2 } from 'lucide-react';
import { SOURCE_FILE_TREE_ACCEPT_ATTR } from '../constants/fileUpload';
import ConfirmationModal from '../modals/ConfirmationModal';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';
import type { Crumb } from './tree/PathHeader';
import TreeBrowser from './tree/TreeBrowser';
import { Button } from './ui/button';
import type { MenuOption } from './ui/dropdown-menu';
import type { RowMenuContext, TreeBrowserController } from './tree/types';
import { useReingestSseWaiter } from './tree/useReingestWait';

type QueuedOperation = {
  operation: 'add' | 'remove' | 'remove_directory';
  files?: File[];
  filePath?: string;
  directoryPath?: string;
  parentDirPath?: string;
};

interface FileTreeProps {
  docId: string;
  sourceName: string;
  onBackToDocuments: () => void;
  /** Extra header control, rendered left of "Add file". */
  headerAction?: React.ReactNode;
  /**
   * Inside another source view (the graph source's Files tab): no Sources
   * crumb, badge or byline, and no headerAction; Add file stays.
   */
  embedded?: boolean;
  /** Embedded only: the host header's action slot (see TreeBrowser). */
  actionsTarget?: HTMLElement | null;
  /** A file to open once the structure loads (path, file name or display name). */
  initialPath?: string;
  /** Embedded only: the tree's crumbs, for the host's header (see TreeBrowser). */
  onCrumbsChange?: (crumbs: Crumb[]) => void;
  /**
   * Whether the caller may change the source (`can(source, 'edit')`).
   * False hides Add file, file and folder Delete (row and header menus) and the chunk writes; browsing stays.
   */
  canEdit?: boolean;
}

const FileTree: React.FC<FileTreeProps> = ({
  docId,
  sourceName,
  onBackToDocuments,
  headerAction,
  embedded = false,
  actionsTarget,
  initialPath,
  onCrumbsChange,
  canEdit = true,
}) => {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const dispatch = useDispatch();

  const controllerRef = useRef<TreeBrowserController | null>(null);
  const currentPathRef = useRef<string[]>([]);

  const [deleteModalState, setDeleteModalState] = useState<
    'ACTIVE' | 'INACTIVE'
  >('INACTIVE');
  const [itemToDelete, setItemToDelete] = useState<{
    name: string;
    isFile: boolean;
  } | null>(null);

  const currentOpRef = useRef<null | 'add' | 'remove' | 'remove_directory'>(
    null,
  );
  const opQueueRef = useRef<QueuedOperation[]>([]);
  const processingRef = useRef(false);
  const [, setQueueLength] = useState(0);
  const [isProcessing, setIsProcessing] = useState(false);

  const { waitForTerminal, mountedRef } = useReingestSseWaiter();

  const manageSource = async (
    operation: 'add' | 'remove' | 'remove_directory',
    files?: File[] | null,
    filePath?: string,
    directoryPath?: string,
    parentDirPath?: string,
  ) => {
    currentOpRef.current = operation;
    // A delete runs after its confirm has closed, so its failure is a toast.
    const reportDeleteFailure = () => {
      const path = operation === 'remove' ? filePath : directoryPath;
      if (operation === 'add' || !path) return;
      dispatch(
        showActionToast({
          variant: 'destructive',
          message: t('settings.sources.deleteItemFailed', {
            interpolation: { escapeValue: false },
            name: path.split('/').pop(),
          }),
        }),
      );
    };

    try {
      const formData = new FormData();
      formData.append('source_id', docId);
      formData.append('operation', operation);

      if (operation === 'add' && files && files.length) {
        formData.append(
          'parent_dir',
          parentDirPath ?? currentPathRef.current.join('/'),
        );
        for (let i = 0; i < files.length; i++) {
          formData.append('file', files[i]);
        }
      } else if (operation === 'remove' && filePath) {
        const filePaths = JSON.stringify([filePath]);
        formData.append('file_paths', filePaths);
      } else if (operation === 'remove_directory' && directoryPath) {
        formData.append('directory_path', directoryPath);
      }

      const response = await userService.manageSourceFiles(formData, token);
      const result = await response.json();

      if (result.success && result.reingest_task_id) {
        const reingestSourceId: string | undefined = result.source_id;
        const opStartedAt = Date.now();

        const terminal = await waitForTerminal(reingestSourceId, opStartedAt);
        if (!mountedRef.current) return false;

        if (terminal === 'completed') {
          if (await controllerRef.current?.refreshDirectory()) {
            currentOpRef.current = null;
            return true;
          }
        } else if (terminal === 'failed') {
          console.error('Reingest task failed (per SSE)');
          reportDeleteFailure();
        } else if (terminal === 'unmounted') {
          return false;
        } else {
          console.error('Reingest timed out waiting for SSE terminal');
        }
      } else {
        throw new Error(
          `Failed to ${operation} ${operation === 'remove_directory' ? 'directory' : 'file(s)'}`,
        );
      }
    } catch (error) {
      const actionText =
        operation === 'add'
          ? 'uploading'
          : operation === 'remove_directory'
            ? 'deleting directory'
            : 'deleting file(s)';
      console.error(`Error ${actionText}:`, error);
      reportDeleteFailure();
    } finally {
      currentOpRef.current = null;
    }

    return false;
  };

  const processQueue = async () => {
    if (processingRef.current) return;
    processingRef.current = true;
    setIsProcessing(true);
    try {
      while (opQueueRef.current.length > 0) {
        const nextOp = opQueueRef.current.shift()!;
        setQueueLength(opQueueRef.current.length);
        await manageSource(
          nextOp.operation,
          nextOp.files,
          nextOp.filePath,
          nextOp.directoryPath,
          nextOp.parentDirPath,
        );
      }
    } finally {
      processingRef.current = false;
      setIsProcessing(false);
    }
  };

  const enqueueOperation = (op: QueuedOperation) => {
    opQueueRef.current.push(op);
    setQueueLength(opQueueRef.current.length);
    if (!processingRef.current) {
      void processQueue();
    }
  };

  const handleAddFile = () => {
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.multiple = true;
    fileInput.accept = SOURCE_FILE_TREE_ACCEPT_ATTR;

    fileInput.onchange = (event) => {
      const fileList = (event.target as HTMLInputElement).files;
      if (!fileList || fileList.length === 0) return;
      const files = Array.from(fileList);
      enqueueOperation({
        operation: 'add',
        files,
        parentDirPath: currentPathRef.current.join('/'),
      });
    };

    fileInput.click();
  };

  const confirmDeleteItem = (name: string, isFile: boolean) => {
    setItemToDelete({ name, isFile });
    setDeleteModalState('ACTIVE');
  };

  const handleConfirmedDelete = async () => {
    if (itemToDelete) {
      const itemPath = [...currentPathRef.current, itemToDelete.name].join('/');
      if (itemToDelete.isFile) {
        enqueueOperation({ operation: 'remove', filePath: itemPath });
      } else {
        enqueueOperation({
          operation: 'remove_directory',
          directoryPath: itemPath,
        });
      }
      setDeleteModalState('INACTIVE');
      setItemToDelete(null);
    }
  };

  const handleCancelDelete = () => {
    setDeleteModalState('INACTIVE');
    setItemToDelete(null);
  };

  const getRowMenuOptions = ({
    name,
    isFile,
    defaultViewOption,
  }: RowMenuContext): MenuOption[] => {
    // Read-only: View only, so a one-file source draws no header menu.
    if (!canEdit) return [defaultViewOption];
    return [
      defaultViewOption,
      {
        icon: Trash2,
        label: t('settings.sources.delete'),
        onClick: () => confirmDeleteItem(name, isFile),
        variant: 'destructive',
      },
    ];
  };

  const statusLabel = isProcessing
    ? currentOpRef.current === 'add'
      ? t('settings.sources.uploadingFilesTitle')
      : t('settings.sources.deletingTitle')
    : null;

  // headerAction stays visible while an upload/delete is in flight — only the
  // Add file button is suppressed then.
  const topRightAction = (
    <>
      {embedded ? null : headerAction}
      {canEdit && !isProcessing ? (
        <Button type="button" size="field" shape="pill" onClick={handleAddFile}>
          {t('settings.sources.addFile')}
        </Button>
      ) : null}
    </>
  );

  const extraContent = (
    <ConfirmationModal
      message={t('settings.sources.deleteWarning', {
        interpolation: { escapeValue: false },
        name: itemToDelete?.name ?? '',
      })}
      description={
        itemToDelete?.isFile
          ? t('settings.sources.deleteFileConsequence')
          : t('settings.sources.deleteDirectoryConsequence')
      }
      modalState={deleteModalState}
      setModalState={setDeleteModalState}
      handleSubmit={handleConfirmedDelete}
      handleCancel={handleCancelDelete}
      submitLabel={t('settings.sources.delete')}
      variant="destructive"
    />
  );

  return (
    <TreeBrowser
      docId={docId}
      sourceName={sourceName}
      onBackToDocuments={onBackToDocuments}
      embedded={embedded}
      onCrumbsChange={onCrumbsChange}
      canEdit={canEdit}
      actionsTarget={actionsTarget}
      initialPath={initialPath}
      columnOrder="size-first"
      sortEntries={false}
      controllerRef={controllerRef}
      topRightAction={topRightAction}
      statusLabel={statusLabel}
      getRowMenuOptions={getRowMenuOptions}
      extraContent={extraContent}
      onCurrentPathChange={(path) => {
        currentPathRef.current = path;
      }}
    />
  );
};

export default FileTree;
