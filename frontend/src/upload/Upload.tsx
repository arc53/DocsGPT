import React, { useCallback, useState, useRef } from 'react';
import { nanoid } from '@reduxjs/toolkit';
import { useDropzone } from 'react-dropzone';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import { getSessionToken } from '../utils/providerUtils';
import Dropdown from '../components/Dropdown';
import Input from '../components/Input';
import ToggleSwitch from '../components/ToggleSwitch';
import WrapperModal from '../modals/WrapperModal';
import { ActiveState, Doc } from '../models/misc';

import { getDocs } from '../preferences/preferenceApi';
import {
  selectSelectedDocs,
  selectSourceDocs,
  selectToken,
  setSelectedDocs,
  setSourceDocs,
} from '../preferences/preferenceSlice';
import {
  IngestorDefaultConfigs,
  IngestorFormSchemas,
  getIngestorSchema,
  IngestorOption,
} from '../upload/types/ingestor';
import { addUploadTask, updateUploadTask } from './uploadSlice';

import { FormField, IngestorConfig, IngestorType } from './types/ingestor';

import { FilePicker } from '../components/FilePicker';
import GoogleDrivePicker from '../components/GoogleDrivePicker';
import { FILE_UPLOAD_ACCEPT, FILE_UPLOAD_ACCEPT_ATTR } from '../constants/fileUpload';

import ChevronRight from '../assets/chevron-right.svg';

function Upload({
  receivedFile = [],
  setModalState,
  isOnboarding,
  renderTab = null,
  close,
  onSuccessfulUpload = () => undefined,
}: {
  receivedFile: File[];
  setModalState: (state: ActiveState) => void;
  isOnboarding: boolean;
  renderTab: string | null;
  close: () => void;
  onSuccessfulUpload?: () => void;
}) {
  const token = useSelector(selectToken);
  const selectedDocs = useSelector(selectSelectedDocs);

  const [files, setfiles] = useState<File[]>(receivedFile);
  const [activeTab, setActiveTab] = useState<boolean>(true);
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);

  // File picker state
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [selectedFolders, setSelectedFolders] = useState<string[]>([]);
  const folderInputRef = useRef<HTMLInputElement>(null);

  const isSupportedFile = (file: File) => {
    const extension = '.' + file.name.split('.').pop()?.toLowerCase();
    return (
      FILE_UPLOAD_ACCEPT_ATTR.split(',').includes(extension) ||
      file.name.toLowerCase().endsWith('.zip')
    );
  };

  const traverseDirectory = useCallback(
    async (entry: any, path = ''): Promise<File[]> => {
      const filesList: File[] = [];
      if (entry.isFile) {
        const file = await new Promise<File>((resolve) => entry.file(resolve));
        const relativePath = path ? `${path}/${file.name}` : file.name;
        // We use Object.defineProperty to set webkitRelativePath as it's often read-only
        try {
          Object.defineProperty(file, 'webkitRelativePath', {
            value: relativePath,
            writable: true,
            configurable: true,
          });
        } catch (e) {
          // Fallback if defineProperty fails
          (file as any).relativePath = relativePath;
        }
        filesList.push(file);
      } else if (entry.isDirectory) {
        const reader = entry.createReader();
        const entries = await new Promise<any[]>((resolve) => {
          const allEntries: any[] = [];
          const read = () => {
            reader.readEntries((results: any[]) => {
              if (results.length) {
                allEntries.push(...results);
                read();
              } else {
                resolve(allEntries);
              }
            });
          };
          read();
        });
        for (const subEntry of entries) {
          const subFiles = await traverseDirectory(
            subEntry,
            path ? `${path}/${entry.name}` : entry.name,
          );
          filesList.push(...subFiles);
        }
      }
      return filesList;
    },
    [],
  );

  const handleFolderButtonClick = () => {
    if (folderInputRef.current) {
      folderInputRef.current.click();
    }
  };

  const onFolderSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const selectedFilesList = (Array.from(e.target.files) as File[]).filter(
        isSupportedFile,
      );
      setfiles(selectedFilesList);
      if (!nameTouched && selectedFilesList.length > 0) {
        // Find the root folder name from webkitRelativePath
        const firstPath = selectedFilesList[0].webkitRelativePath;
        const rootFolder = firstPath.split('/')[0];
        setIngestor((prev: IngestorConfig) => ({
          ...prev,
          name: rootFolder || prev.name,
        }));
      }
    }
  };

  const renderFormFields = () => {
    if (!ingestor.type) return null;
    const ingestorSchema = getIngestorSchema(ingestor.type as IngestorType);
    if (!ingestorSchema) return null;
    const schema: FormField[] = ingestorSchema.fields;

    const generalFields = schema.filter((field: FormField) => !field.advanced);
    const advancedFields = schema.filter((field: FormField) => field.advanced);

    return (
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-4">
          {generalFields.map((field: FormField) => renderField(field))}
        </div>

        {advancedFields.length > 0 && (
          <div
            className={`grid transition-all duration-300 ease-in-out ${
              showAdvancedOptions
                ? 'grid-rows-[1fr] opacity-100'
                : 'grid-rows-[0fr] opacity-0'
            }`}
          >
            <div className="flex flex-col gap-4 overflow-hidden">
              <hr className="my-4 border border-[#C4C4C4]/40" />
              <div className="flex flex-col gap-4">
                {advancedFields.map((field: FormField) => renderField(field))}
              </div>
            </div>
          </div>
        )}
      </div>
    );
  };

  const renderField = (field: FormField) => {
    const isRequired = field.required ?? false;
    switch (field.type) {
      case 'string':
        return (
          <Input
            key={field.name}
            placeholder={field.label}
            type="text"
            name={field.name}
            value={String(
              ingestor.config[field.name as keyof typeof ingestor.config],
            )}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
              handleIngestorChange(
                field.name as keyof IngestorConfig['config'],
                e.target.value,
              )
            }
            borderVariant="thin"
            required={isRequired}
            colorVariant="silver"
            labelBgClassName="bg-card"
          />
        );
      case 'number':
        return (
          <Input
            key={field.name}
            placeholder={field.label}
            type="number"
            name={field.name}
            value={String(
              ingestor.config[field.name as keyof typeof ingestor.config],
            )}
            onChange={(e) =>
              handleIngestorChange(
                field.name as keyof IngestorConfig['config'],
                Number(e.target.value),
              )
            }
            borderVariant="thin"
            required={isRequired}
            colorVariant="silver"
            labelBgClassName="bg-card"
          />
        );
      case 'enum':
        return (
          <Dropdown
            key={field.name}
            options={field.options || []}
            selectedValue={
              field.options?.find(
                (opt) =>
                  opt.value ===
                  ingestor.config[field.name as keyof typeof ingestor.config],
              ) || null
            }
            onSelect={(selected: { label: string; value: string }) => {
              handleIngestorChange(
                field.name as keyof IngestorConfig['config'],
                selected.value,
              );
            }}
            size="w-full"
            rounded="3xl"
            placeholder={field.label}
            contentSize="text-sm"
          />
        );
      case 'boolean':
        return (
          <ToggleSwitch
            key={field.name}
            label={field.label}
            checked={Boolean(
              ingestor.config[field.name as keyof typeof ingestor.config],
            )}
            onChange={(checked: boolean) => {
              handleIngestorChange(
                field.name as keyof IngestorConfig['config'],
                checked,
              );
            }}
            size="small"
            className={`mt-2 text-base`}
          />
        );
      case 'local_file_picker':
        return (
          <div key={field.name}>
            <div className="mb-3" {...getRootProps()}>
              <span className="text-primary dark:text-muted-foreground inline-block rounded-3xl border border-[#7F7F82] bg-transparent px-4 py-2 font-medium hover:cursor-pointer">
                <input type="button" {...getInputProps()} />
                {t('modals.uploadDoc.choose')}
              </span>
              <span
                className="text-purple-30 dark:text-silver ml-2 inline-block rounded-3xl border border-[#7F7F82] bg-transparent px-4 py-2 font-medium hover:cursor-pointer"
                onClick={handleFolderButtonClick}
              >
                <input
                  type="file"
                  ref={folderInputRef}
                  className="hidden"
                  onChange={onFolderSelect}
                  {...({
                    webkitdirectory: 'true',
                    directory: 'true',
                  } as any)}
                />
                {t('modals.uploadDoc.chooseFolder')}
              </span>
            </div>
            <div className="mt-4 max-w-full">
              <p className="text-foreground dark:text-foreground mb-3.5 text-[14px] font-medium">
                {t('modals.uploadDoc.selectedFiles')}
              </p>
              <div className="max-w-full overflow-hidden">
                {files.map((file) => (
                  <p
                    key={file.name}
                    className="text-muted-foreground truncate overflow-hidden text-ellipsis"
                    title={file.name}
                  >
                    {file.name}
                  </p>
                ))}
                {files.length === 0 && (
                  <p className="text-muted-foreground text-[14px]">
                    {t('modals.uploadDoc.noFilesSelected')}
                  </p>
                )}
              </div>
            </div>
          </div>
        );
      case 'remote_file_picker':
        return (
          <FilePicker
            key={field.name}
            onSelectionChange={(
              selectedFileIds: string[],
              selectedFolderIds: string[] = [],
            ) => {
              setSelectedFiles(selectedFileIds);
              setSelectedFolders(selectedFolderIds);
            }}
            provider={ingestor.type as unknown as string}
            token={token}
            initialSelectedFiles={selectedFiles}
            initialSelectedFolders={selectedFolders}
          />
        );
      case 'google_drive_picker':
        return (
          <GoogleDrivePicker
            key={field.name}
            onSelectionChange={(
              selectedFileIds: string[],
              selectedFolderIds: string[] = [],
            ) => {
              setSelectedFiles(selectedFileIds);
              setSelectedFolders(selectedFolderIds);
            }}
            token={token}
          />
        );
      case 'share_point_picker':
        return (
          <FilePicker
            key={field.name}
            onSelectionChange={(
              selectedFileIds: string[],
              selectedFolderIds: string[] = [],
            ) => {
              setSelectedFiles(selectedFileIds);
              setSelectedFolders(selectedFolderIds);
            }}
            provider="share_point"
            token={token}
            initialSelectedFiles={selectedFiles}
            initialSelectedFolders={selectedFolders}
          />
        );
      default:
        return null;
    }
  };

  // New unified ingestor state
  const [ingestor, setIngestor] = useState<IngestorConfig>(() => ({
    type: null,
    name: '',
    config: {},
  }));
  const [nameTouched, setNameTouched] = useState(false);

  const { t } = useTranslation();
  const dispatch = useDispatch();

  const ingestorOptions: IngestorOption[] = IngestorFormSchemas.filter(
    (schema) => (schema.validate ? schema.validate() : true),
  ).map((schema) => ({
    label: schema.label,
    value: schema.key,
    icon: schema.icon,
    heading: schema.heading,
  }));

  const sourceDocs = useSelector(selectSourceDocs);

  const resetUploaderState = useCallback(() => {
    setIngestor({ type: null, name: '', config: {} });
    setfiles([]);
    setSelectedFiles([]);
    setSelectedFolders([]);
    setShowAdvancedOptions(false);
    setNameTouched(false);
  }, []);

  const handleTaskFailure = useCallback(
    (clientTaskId: string, errorMessage?: string) => {
      dispatch(
        updateUploadTask({
          id: clientTaskId,
          updates: {
            status: 'failed',
            errorMessage: errorMessage,
          },
        }),
      );
    },
    [dispatch],
  );

  const trackTraining = useCallback(
    (backendTaskId: string, clientTaskId: string) => {
      let timeoutId: number | null = null;

      const poll = () => {
        userService
          .getTaskStatus(backendTaskId, null)
          .then((response) => response.json())
          .then(async (data) => {
            if (!data.success && data.message) {
              if (timeoutId !== null) {
                clearTimeout(timeoutId);
                timeoutId = null;
              }
              handleTaskFailure(clientTaskId, data.message);
              return;
            }

            if (data.status === 'SUCCESS') {
              if (timeoutId !== null) {
                clearTimeout(timeoutId);
                timeoutId = null;
              }

              const docs = await getDocs(token);
              dispatch(setSourceDocs(docs));

              if (Array.isArray(docs)) {
                const existingDocIds = new Set(
                  (Array.isArray(sourceDocs) ? sourceDocs : [])
                    .map((doc: Doc) => doc?.id)
                    .filter((id): id is string => Boolean(id)),
                );
                const newDoc = docs.find(
                  (doc: Doc) => doc.id && !existingDocIds.has(doc.id),
                );
                if (newDoc) {
                  // If only one doc is selected, replace it completely
                  // If multiple docs are selected, append the new doc
                  if (selectedDocs.length === 1) {
                    dispatch(setSelectedDocs([newDoc]));
                  } else {
                    dispatch(setSelectedDocs([...selectedDocs, newDoc]));
                  }
                }
              }

              if (data.result?.limited) {
                dispatch(
                  updateUploadTask({
                    id: clientTaskId,
                    updates: {
                      status: 'failed',
                      progress: 100,
                      errorMessage: t('modals.uploadDoc.progress.tokenLimit'),
                    },
                  }),
                );
              } else {
                dispatch(
                  updateUploadTask({
                    id: clientTaskId,
                    updates: {
                      status: 'completed',
                      progress: 100,
                      errorMessage: undefined,
                    },
                  }),
                );
                onSuccessfulUpload?.();
              }
            } else if (data.status === 'FAILURE') {
              if (timeoutId !== null) {
                clearTimeout(timeoutId);
                timeoutId = null;
              }
              handleTaskFailure(clientTaskId, data.result?.message);
            } else if (data.status === 'PROGRESS') {
              dispatch(
                updateUploadTask({
                  id: clientTaskId,
                  updates: {
                    status: 'training',
                    progress: Math.min(100, data.result?.current ?? 0),
                  },
                }),
              );
              timeoutId = window.setTimeout(poll, 5000);
            } else {
              timeoutId = window.setTimeout(poll, 5000);
            }
          })
          .catch((error) => {
            if (timeoutId !== null) {
              clearTimeout(timeoutId);
              timeoutId = null;
            }
            handleTaskFailure(clientTaskId, error?.message);
          });
      };

      timeoutId = window.setTimeout(poll, 3000);
    },
    [dispatch, handleTaskFailure, onSuccessfulUpload, sourceDocs, t, token],
  );

  const onDrop = useCallback(
    async (acceptedFiles: File[], fileRejections: any[], event: any) => {
      let finalFiles = acceptedFiles;

      // Handle directory drops via webkitGetAsEntry if available
      if (event.dataTransfer && event.dataTransfer.items) {
        const items = event.dataTransfer.items;
        const traversePromises = [];
        for (let i = 0; i < items.length; i++) {
          const entry = items[i].webkitGetAsEntry();
          if (entry) {
            traversePromises.push(traverseDirectory(entry));
          }
        }
        if (traversePromises.length > 0) {
          const results = await Promise.all(traversePromises);
          finalFiles = results.flat();
        }
      }

      setfiles(finalFiles);
      const pickedName =
        finalFiles[0]?.webkitRelativePath?.split('/')[0] || finalFiles[0]?.name;
      if (!nameTouched && pickedName) {
        setIngestor((prev: IngestorConfig) => ({ ...prev, name: pickedName }));
      }

      // If we're in local_file mode, update the ingestor config
      if (ingestor.type === 'local_file') {
        setIngestor((prevState: IngestorConfig) => ({
          ...prevState,
          config: {
            ...prevState.config,
            files: finalFiles,
          },
        }));
      }
    },
    [ingestor.type, nameTouched, traverseDirectory],
  );

  const doNothing = () => undefined;

  const uploadFile = (clientTaskId: string) => {
    const formData = new FormData();
    files.forEach((file) => {
      const relativePath =
        file.webkitRelativePath || (file as any).relativePath || file.name;
      formData.append('file', file, relativePath);
    });

    formData.append('name', ingestor.name);
    formData.append('user', 'local');

    const apiHost = import.meta.env.VITE_API_HOST;
    const xhr = new XMLHttpRequest();

    dispatch(
      updateUploadTask({
        id: clientTaskId,
        updates: { status: 'uploading', progress: 0 },
      }),
    );

    xhr.upload.addEventListener('progress', (event) => {
      if (!event.lengthComputable) return;
      const progressPercentage = Number(
        ((event.loaded / event.total) * 100).toFixed(2),
      );
      dispatch(
        updateUploadTask({
          id: clientTaskId,
          updates: { progress: progressPercentage },
        }),
      );
    });

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const parsed = JSON.parse(xhr.responseText) as { task_id?: string };
          if (parsed.task_id) {
            dispatch(
              updateUploadTask({
                id: clientTaskId,
                updates: {
                  taskId: parsed.task_id,
                  status: 'training',
                  progress: 0,
                },
              }),
            );
            trackTraining(parsed.task_id, clientTaskId);
          } else {
            dispatch(
              updateUploadTask({
                id: clientTaskId,
                updates: { status: 'completed', progress: 100 },
              }),
            );
            onSuccessfulUpload?.();
          }
        } catch (error) {
          handleTaskFailure(clientTaskId);
        }
      } else {
        handleTaskFailure(clientTaskId, xhr.statusText || undefined);
      }
    };

    xhr.onerror = () => {
      handleTaskFailure(clientTaskId);
    };

    xhr.open('POST', `${apiHost}/api/upload`);
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.send(formData);
  };

  const uploadRemote = (clientTaskId: string) => {
    if (!ingestor.type) {
      handleTaskFailure(clientTaskId);
      return;
    }

    const formData = new FormData();
    formData.append('name', ingestor.name);
    formData.append('user', 'local');
    formData.append('source', ingestor.type as string);

    const ingestorSchema = getIngestorSchema(ingestor.type as IngestorType);
    if (!ingestorSchema) {
      handleTaskFailure(clientTaskId);
      return;
    }

    const schema: FormField[] = ingestorSchema.fields;
    const hasLocalFilePicker = schema.some(
      (field: FormField) => field.type === 'local_file_picker',
    );
    const hasRemoteFilePicker = schema.some(
      (field: FormField) => field.type === 'remote_file_picker',
    );
    const hasGoogleDrivePicker = schema.some(
      (field: FormField) => field.type === 'google_drive_picker',
    );
    const hasSharePointPicker = schema.some(
      (field: FormField) => field.type === 'share_point_picker',
    );

    let configData: Record<string, unknown> = { ...ingestor.config };

    if (hasLocalFilePicker) {
      files.forEach((file) => {
        formData.append('file', file);
      });
    } else if (
      hasRemoteFilePicker ||
      hasGoogleDrivePicker ||
      hasSharePointPicker
    ) {
      const sessionToken = getSessionToken(ingestor.type as string);
      configData = {
        provider: ingestor.type as string,
        session_token: sessionToken,
        file_ids: selectedFiles,
        folder_ids: selectedFolders,
      };
    }

    formData.append('data', JSON.stringify(configData));

    const apiHost: string = import.meta.env.VITE_API_HOST;
    const endpoint =
      ingestor.type === 'local_file'
        ? `${apiHost}/api/upload`
        : `${apiHost}/api/remote`;

    const xhr = new XMLHttpRequest();

    dispatch(
      updateUploadTask({
        id: clientTaskId,
        updates: { status: 'uploading', progress: 0 },
      }),
    );

    xhr.upload.addEventListener('progress', (event: ProgressEvent) => {
      if (!event.lengthComputable) return;
      const progressPercentage = Number(
        ((event.loaded / event.total) * 100).toFixed(2),
      );
      dispatch(
        updateUploadTask({
          id: clientTaskId,
          updates: { progress: progressPercentage },
        }),
      );
    });

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const response = JSON.parse(xhr.responseText) as { task_id?: string };
          if (response.task_id) {
            dispatch(
              updateUploadTask({
                id: clientTaskId,
                updates: {
                  taskId: response.task_id,
                  status: 'training',
                  progress: 0,
                },
              }),
            );
            trackTraining(response.task_id, clientTaskId);
          } else {
            dispatch(
              updateUploadTask({
                id: clientTaskId,
                updates: { status: 'completed', progress: 100 },
              }),
            );
            onSuccessfulUpload?.();
          }
        } catch (error) {
          handleTaskFailure(clientTaskId);
        }
      } else {
        handleTaskFailure(clientTaskId, xhr.statusText || undefined);
      }
    };

    xhr.onerror = () => {
      handleTaskFailure(clientTaskId);
    };

    xhr.open('POST', endpoint);
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.send(formData);
  };

  const handleClose = useCallback(() => {
    resetUploaderState();
    setModalState('INACTIVE');
    close();
  }, [close, resetUploaderState, setModalState]);

  const handleUpload = () => {
    if (!ingestor.type) return;

    const ingestorSchemaForUpload = getIngestorSchema(
      ingestor.type as IngestorType,
    );
    if (!ingestorSchemaForUpload) return;

    const schema: FormField[] = ingestorSchemaForUpload.fields;
    const hasLocalFilePicker = schema.some(
      (field: FormField) => field.type === 'local_file_picker',
    );

    const displayName =
      ingestor.name?.trim() || files[0]?.name || t('modals.uploadDoc.label');

    const clientTaskId = nanoid();

    dispatch(
      addUploadTask({
        id: clientTaskId,
        fileName: displayName,
        progress: 0,
        status: 'preparing',
      }),
    );

    if (hasLocalFilePicker) {
      uploadFile(clientTaskId);
    } else {
      uploadRemote(clientTaskId);
    }

    handleClose();
  };

  const { getRootProps, getInputProps } = useDropzone({
    onDrop,
    multiple: true,
    onDragEnter: doNothing,
    onDragOver: doNothing,
    onDragLeave: doNothing,
    maxSize: 25000000,
    accept: FILE_UPLOAD_ACCEPT,
  });

  const isUploadDisabled = (): boolean => {
    if (!activeTab) return true;

    if (!ingestor.name?.trim()) {
      return true;
    }

    if (!ingestor.type) return true;
    const ingestorSchemaForValidation = getIngestorSchema(
      ingestor.type as IngestorType,
    );
    if (!ingestorSchemaForValidation) return true;
    const schema: FormField[] = ingestorSchemaForValidation.fields;
    const hasLocalFilePicker = schema.some(
      (field: FormField) => field.type === 'local_file_picker',
    );
    const hasRemoteFilePicker = schema.some(
      (field: FormField) => field.type === 'remote_file_picker',
    );
    const hasGoogleDrivePicker = schema.some(
      (field: FormField) => field.type === 'google_drive_picker',
    );
    const hasSharePointPicker = schema.some(
      (field: FormField) => field.type === 'share_point_picker',
    );

    if (hasLocalFilePicker) {
      if (files.length === 0) {
        return true;
      }
    } else if (
      hasRemoteFilePicker ||
      hasGoogleDrivePicker ||
      hasSharePointPicker
    ) {
      if (selectedFiles.length === 0 && selectedFolders.length === 0) {
        return true;
      }
    }

    const ingestorSchemaForFields = getIngestorSchema(
      ingestor.type as IngestorType,
    );
    if (!ingestorSchemaForFields) return false;
    const formFields: FormField[] = ingestorSchemaForFields.fields;
    for (const field of formFields) {
      if (field.required) {
        // Validate only required fields
        const value =
          ingestor.config[field.name as keyof typeof ingestor.config];

        if (typeof value === 'string' && !value.trim()) {
          return true;
        }

        if (
          typeof value === 'number' &&
          (value === null || value === undefined || value <= 0)
        ) {
          return true;
        }

        if (typeof value === 'boolean' && value === undefined) {
          return true;
        }
      }
    }
    return false;
  };
  const handleIngestorChange = (
    key: keyof IngestorConfig['config'],
    value: string | number | boolean,
  ) => {
    setIngestor((prevState) => ({
      ...prevState,
      config: {
        ...prevState.config,
        [key]: value,
      },
    }));
  };
  const handleIngestorTypeChange = (type: IngestorType | null) => {
    if (type === null) {
      setIngestor({
        type: null,
        name: '',
        config: {},
      });
      setfiles([]);
      setNameTouched(false);
      return;
    }

    const defaultConfig = IngestorDefaultConfigs[type];
    setIngestor({
      type,
      name: defaultConfig.name,
      config: defaultConfig.config,
    });
    setNameTouched(false);

    // Clear files if switching away from local_file
    if (type !== 'local_file') {
      setfiles([]);
    }
  };

  const renderIngestorSelection = () => {
    return (
      <div className="grid w-full grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3">
        {ingestorOptions.map((option) => (
          <div
            key={option.value}
            className={`relative mx-auto flex h-[91.2px] w-full cursor-pointer flex-col justify-between gap-2 rounded-2xl border border-solid pt-[21.1px] pr-[21px] pb-[15px] pl-[21px] transition-colors duration-300 ease-out ${
              ingestor.type === option.value
                ? 'border-[#7D54D1] bg-[#7D54D1] text-white'
                : 'border-border hover:bg-accent/30 dark:border-border/30 bg-transparent transition-shadow duration-300 hover:shadow-[0_0_15px_0_#00000026]'
            }`}
            onClick={() =>
              handleIngestorTypeChange(option.value as IngestorType)
            }
          >
            <div className="flex h-full flex-col justify-between">
              <div className="h-6 w-6">
                <img
                  src={option.icon}
                  alt={option.label}
                  className={`${ingestor.type === option.value ? 'invert filter' : ''} dark:invert dark:filter`}
                />
              </div>
              <p className="font-inter self-start text-[13px] leading-[18px] font-semibold">
                {t(`modals.uploadDoc.ingestors.${option.value}.label`)}
              </p>
            </div>
          </div>
        ))}
      </div>
    );
  };
  return (
    <WrapperModal
      close={handleClose}
      className="max-h-[90vh] w-11/12 sm:max-h-none sm:w-auto sm:min-w-[600px] md:min-w-[700px]"
      contentClassName="max-h-[80vh] sm:max-h-none"
    >
      <div className="flex w-full flex-col gap-6">
        {!ingestor.type && (
          <p className="font-inter text-foreground dark:text-foreground text-left text-[20px] leading-7 font-semibold tracking-[0.15px]">
            {t('modals.uploadDoc.selectSource')}
          </p>
        )}

        {activeTab && (
          <>
            {!ingestor.type && renderIngestorSelection()}
            {ingestor.type && (
              <div className="flex flex-col gap-4">
                <button
                  onClick={() => handleIngestorTypeChange(null)}
                  className="flex w-fit items-center gap-2 text-[#777777] hover:text-[#555555]"
                >
                  <img
                    src={ChevronRight}
                    alt="back"
                    className="h-3 w-3 rotate-180 transform"
                  />
                  <span>{t('modals.uploadDoc.back')}</span>
                </button>

                <h2 className="font-inter text-foreground text-[22px] leading-7 font-semibold tracking-[0.15px]">
                  {ingestor.type &&
                    t(`modals.uploadDoc.ingestors.${ingestor.type}.heading`)}
                </h2>

                <Input
                  type="text"
                  colorVariant="silver"
                  value={ingestor.name}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                    setNameTouched(true);
                    setIngestor((prevState: IngestorConfig) => ({
                      ...prevState,
                      name: e.target.value,
                    }));
                  }}
                  borderVariant="thin"
                  placeholder={t('modals.uploadDoc.name')}
                  required={true}
                  labelBgClassName="bg-card"
                  className="w-full"
                />
                {renderFormFields()}
              </div>
            )}

            {ingestor.type &&
              getIngestorSchema(ingestor.type as IngestorType)?.fields.some(
                (field: FormField) => field.advanced,
              ) && (
                <button
                  onClick={() => setShowAdvancedOptions(!showAdvancedOptions)}
                  className="text-primary bg-transparent py-2 pl-0 text-left text-sm font-normal hover:cursor-pointer"
                >
                  {showAdvancedOptions
                    ? t('modals.uploadDoc.hideAdvanced')
                    : t('modals.uploadDoc.showAdvanced')}
                </button>
              )}
          </>
        )}
        <div className="flex justify-end gap-4">
          {activeTab && ingestor.type && (
            <button
              onClick={handleUpload}
              disabled={isUploadDisabled()}
              className={`rounded-3xl px-4 py-2 text-[14px] font-medium ${
                isUploadDisabled()
                  ? 'dark:bg-muted dark:text-muted-foreground cursor-not-allowed bg-gray-300 text-gray-500'
                  : 'bg-primary hover:bg-primary/90 cursor-pointer text-white'
              }`}
            >
              {t('modals.uploadDoc.train')}
            </button>
          )}
        </div>
      </div>
    </WrapperModal>
  );
}

export default Upload;
