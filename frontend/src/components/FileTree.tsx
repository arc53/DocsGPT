import React, { SyntheticEvent, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import userService from '../api/services/userService';
import Trash from '../assets/red-trash.svg';
import { SOURCE_FILE_TREE_ACCEPT_ATTR } from '../constants/fileUpload';
import ConfirmationModal from '../modals/ConfirmationModal';
import { selectToken } from '../preferences/preferenceSlice';
import TreeBrowser from './tree/TreeBrowser';
import type {
  RowMenuContext,
  TreeBrowserController,
  TreeMenuOption,
} from './tree/types';
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
}

const FileTree: React.FC<FileTreeProps> = ({
  docId,
  sourceName,
  onBackToDocuments,
}) => {
  const { t } = useTranslation();
  const token = useSelector(selectToken);

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
  }: RowMenuContext): TreeMenuOption[] => {
    return [
      defaultViewOption,
      {
        icon: Trash,
        label: t('convTile.delete'),
        onClick: (event: SyntheticEvent) => {
          event.stopPropagation();
          confirmDeleteItem(name, isFile);
        },
        iconWidth: 18,
        iconHeight: 18,
        variant: 'destructive',
      },
    ];
  };

  const statusLabel = isProcessing
    ? currentOpRef.current === 'add'
      ? t('settings.sources.uploadingFilesTitle')
      : t('settings.sources.deletingTitle')
    : null;

  const topRightAction = !isProcessing ? (
    <button
      onClick={handleAddFile}
      className="bg-primary hover:bg-primary/90 flex h-[38px] min-w-[108px] items-center justify-center rounded-full px-4 text-sm font-medium whitespace-nowrap text-white"
      title={t('settings.sources.addFile')}
    >
      {t('settings.sources.addFile')}
    </button>
  ) : null;

  const extraContent = (
    <ConfirmationModal
      message={
        itemToDelete?.isFile
          ? t('settings.sources.confirmDelete')
          : t('settings.sources.deleteDirectoryWarning', {
              name: itemToDelete?.name,
            })
      }
      modalState={deleteModalState}
      setModalState={setDeleteModalState}
      handleSubmit={handleConfirmedDelete}
      handleCancel={handleCancelDelete}
      submitLabel={t('convTile.delete')}
      variant="danger"
    />
  );

  return (
    <TreeBrowser
      docId={docId}
      sourceName={sourceName}
      onBackToDocuments={onBackToDocuments}
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
