import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import FileUpload from '../assets/file_upload.svg';
import WebsiteCollect from '../assets/website_collect.svg';
import Dropdown from '../components/Dropdown';
import Input from '../components/Input';
import ToggleSwitch from '../components/ToggleSwitch';
import WrapperModal from '../modals/WrapperModal';
import { ActiveState, Doc } from '../models/misc';
import { getDocs } from '../preferences/preferenceApi';
import {
  selectSourceDocs,
  selectToken,
  setSelectedDocs,
  setSourceDocs,
} from '../preferences/preferenceSlice';
import { IngestorDefaultConfigs } from '../upload/types/ingestor';
import {
  FormField,
  IngestorConfig,
  IngestorFormSchemas,
  IngestorType,
} from './types/ingestor';
import FileIcon from '../assets/file.svg';
import FolderIcon from '../assets/folder.svg';
import ConnectorAuth from '../components/ConnectorAuth';

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
  const [docName, setDocName] = useState(receivedFile[0]?.name);
  const [remoteName, setRemoteName] = useState('');
  const [files, setfiles] = useState<File[]>(receivedFile);
  const [activeTab, setActiveTab] = useState<string | null>(renderTab);
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);

  // Google Drive state
  const [isGoogleDriveConnected, setIsGoogleDriveConnected] = useState(false);
  const [googleDriveFiles, setGoogleDriveFiles] = useState<any[]>([]);
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [isLoadingFiles, setIsLoadingFiles] = useState(false);
  const [isAuthenticating, setIsAuthenticating] = useState(false);
  const [userEmail, setUserEmail] = useState<string>('');
  const [authError, setAuthError] = useState<string>('');
  const [currentFolderId, setCurrentFolderId] = useState<string | null>(null);
  const [folderPath, setFolderPath] = useState<Array<{id: string | null, name: string}>>([{id: null, name: 'My Drive'}]);

  const renderFormFields = () => {
    const schema = IngestorFormSchemas[ingestor.type];
    if (!schema) return null;

    const generalFields = schema.filter((field) => !field.advanced);
    const advancedFields = schema.filter((field) => field.advanced);

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
            onChange={(e) =>
              handleIngestorChange(
                field.name as keyof IngestorConfig['config'],
                e.target.value,
              )
            }
            borderVariant="thin"
            required={isRequired}
            colorVariant="silver"
            labelBgClassName="bg-white dark:bg-charleston-green-2"
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
            labelBgClassName="bg-white dark:bg-charleston-green-2"
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
            border="border"
            buttonClassName="border-silver bg-white dark:border-dim-gray dark:bg-[#222327]"
            optionsClassName="border-silver bg-white dark:border-dim-gray dark:bg-[#383838]"
            placeholderClassName="text-gray-400 dark:text-silver"
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
            className="mt-2"
          />
        );
      default:
        return null;
    }
  };

  // New unified ingestor state
  const [ingestor, setIngestor] = useState<IngestorConfig>(() => {
    const defaultType: IngestorType = 'crawler';
    const defaultConfig = IngestorDefaultConfigs[defaultType];
    return {
      type: defaultType,
      name: defaultConfig.name,
      config: defaultConfig.config,
    };
  });

  const [progress, setProgress] = useState<{
    type: 'UPLOAD' | 'TRAINING';
    percentage: number;
    taskId?: string;
    failed?: boolean;
  }>();

  const { t } = useTranslation();
  const setTimeoutRef = useRef<number | null>(null);

  const urlOptions: { label: string; value: IngestorType }[] = [
    { label: 'Crawler', value: 'crawler' },
    { label: 'Link', value: 'url' },
    { label: 'GitHub', value: 'github' },
    { label: 'Reddit', value: 'reddit' },
    { label: 'Google Drive', value: 'google_drive' },
  ];

  const sourceDocs = useSelector(selectSourceDocs);
  useEffect(() => {
    if (setTimeoutRef.current) {
      clearTimeout(setTimeoutRef.current);
    }
  }, []);

  function ProgressBar({ progressPercent }: { progressPercent: number }) {
    return (
      <div className="my-8 flex h-full w-full items-center justify-center">
        <div className="relative h-32 w-32 rounded-full">
          <div className="absolute inset-0 rounded-full shadow-[0_0_10px_2px_rgba(0,0,0,0.3)_inset] dark:shadow-[0_0_10px_2px_rgba(0,0,0,0.3)_inset]"></div>
          <div
            className={`absolute inset-0 rounded-full ${progressPercent === 100 ? 'bg-linear-to-r from-white to-gray-400 shadow-xl shadow-lime-300/50 dark:bg-linear-to-br dark:from-gray-500 dark:to-gray-300 dark:shadow-lime-300/50' : 'shadow-[0_4px_0_#7D54D1] dark:shadow-[0_4px_0_#7D54D1]'}`}
            style={{
              animation: `${progressPercent === 100 ? 'none' : 'rotate 2s linear infinite'}`,
            }}
          ></div>
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-2xl font-bold">{progressPercent}%</span>
          </div>
          <style>
            {`@keyframes rotate {
                0% { transform: rotate(0deg); }
                100%{ transform: rotate(360deg); }
              }`}
          </style>
        </div>
      </div>
    );
  }

  function Progress({
    title,
    isCancellable = false,
    isFailed = false,
    isTraining = false,
  }: {
    title: string;
    isCancellable?: boolean;
    isFailed?: boolean;
    isTraining?: boolean;
  }) {
    return (
      <div className="text-gray-2000 dark:text-bright-gray mt-5 flex flex-col items-center gap-2">
        <p className="text-gra text-xl tracking-[0.15px]">
          {isTraining &&
            (progress?.percentage === 100
              ? t('modals.uploadDoc.progress.completed')
              : title)}
          {!isTraining && title}
        </p>
        <p className="text-sm">{t('modals.uploadDoc.progress.wait')}</p>
        <p className={`ml-5 text-xl text-red-400 ${isFailed ? '' : 'hidden'}`}>
          {t('modals.uploadDoc.progress.tokenLimit')}
        </p>
        {/* <p className="mt-10 text-2xl">{progress?.percentage || 0}%</p> */}
        <ProgressBar progressPercent={progress?.percentage || 0} />
        {isTraining &&
          (progress?.percentage === 100 ? (
            <button
              onClick={() => {
                setDocName('');
                setfiles([]);
                setProgress(undefined);
                setModalState('INACTIVE');
              }}
              className="h-[42px] cursor-pointer rounded-3xl bg-[#7D54D1] px-[28px] py-[6px] text-sm text-white shadow-lg hover:bg-[#6F3FD1]"
            >
              {t('modals.uploadDoc.start')}
            </button>
          ) : (
            <button
              className="ml-2 h-[42px] cursor-pointer rounded-3xl bg-[#7D54D14D] px-[28px] py-[6px] text-sm text-white shadow-lg"
              disabled
            >
              {t('modals.uploadDoc.wait')}
            </button>
          ))}
      </div>
    );
  }

  function UploadProgress() {
    return <Progress title={t('modals.uploadDoc.progress.upload')}></Progress>;
  }

  function TrainingProgress() {
    const dispatch = useDispatch();

    useEffect(() => {
      let timeoutID: number | undefined;

      if ((progress?.percentage ?? 0) < 100) {
        timeoutID = setTimeout(() => {
          userService
            .getTaskStatus(progress?.taskId as string, null)
            .then((data) => data.json())
            .then((data) => {
              if (data.status == 'SUCCESS') {
                if (data.result.limited === true) {
                  getDocs(token).then((data) => {
                    dispatch(setSourceDocs(data));
                    dispatch(
                      setSelectedDocs(
                        Array.isArray(data) &&
                          data?.find(
                            (d: Doc) => d.type?.toLowerCase() === 'local',
                          ),
                    ));
                  });
                  setProgress(
                    (progress) =>
                      progress && {
                        ...progress,
                        percentage: 100,
                        failed: true,
                      },
                  );
                } else {
                  getDocs(token).then((data) => {
                    dispatch(setSourceDocs(data));
                    const docIds = new Set(
                      (Array.isArray(sourceDocs) &&
                        sourceDocs?.map((doc: Doc) =>
                          doc.id ? doc.id : null,
                        )) ||
                        [],
                    );
                    if (data && Array.isArray(data)) {
                      data.map((updatedDoc: Doc) => {
                        if (updatedDoc.id && !docIds.has(updatedDoc.id)) {
                          // Select the doc not present in the intersection of current Docs and fetched data
                          dispatch(setSelectedDocs(updatedDoc));
                          return;
                        }
                      });
                    }
                  });
                  setProgress(
                    (progress) =>
                      progress && {
                        ...progress,
                        percentage: 100,
                        failed: false,
                      },
                  );
                  setDocName('');
                  setfiles([]);
                  setProgress(undefined);
                  setModalState('INACTIVE');
                  onSuccessfulUpload?.();
                }
              } else if (data.status == 'PROGRESS') {
                setProgress(
                  (progress) =>
                    progress && {
                      ...progress,
                      percentage: data.result.current,
                    },
                );
              }
            });
        }, 5000);
      }

      // cleanup
      return () => {
        if (timeoutID !== undefined) {
          clearTimeout(timeoutID);
        }
      };
    }, [progress, dispatch]);
    return (
      <Progress
        title={t('modals.uploadDoc.progress.training')}
        isCancellable={progress?.percentage === 100}
        isFailed={progress?.failed === true}
        isTraining={true}
      ></Progress>
    );
  }

  const onDrop = useCallback((acceptedFiles: File[]) => {
    setfiles(acceptedFiles);
    setDocName(acceptedFiles[0]?.name || '');
  }, []);

  const doNothing = () => undefined;

  const uploadFile = () => {
    const formData = new FormData();
    files.forEach((file) => {
      formData.append('file', file);
    });

    formData.append('name', docName);
    formData.append('user', 'local');
    const apiHost = import.meta.env.VITE_API_HOST;
    const xhr = new XMLHttpRequest();
    xhr.upload.addEventListener('progress', (event) => {
      const progress = +((event.loaded / event.total) * 100).toFixed(2);
      setProgress({ type: 'UPLOAD', percentage: progress });
    });
    xhr.onload = () => {
      const { task_id } = JSON.parse(xhr.responseText);
      setTimeoutRef.current = setTimeout(() => {
        setProgress({ type: 'TRAINING', percentage: 0, taskId: task_id });
      }, 3000);
    };
    xhr.open('POST', `${apiHost + '/api/upload'}`);
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.send(formData);
  };

  const uploadRemote = () => {
    const formData = new FormData();
    formData.append('name', remoteName);
    formData.append('user', 'local');
    formData.append('source', ingestor.type);

    let configData;

    if (ingestor.type === 'google_drive') {
      const sessionToken = localStorage.getItem('google_drive_session_token');
      
      const selectedItems = googleDriveFiles.filter(file => selectedFiles.includes(file.id));
      const selectedFolderIds = selectedItems
        .filter(item => item.type === 'application/vnd.google-apps.folder' || item.isFolder)
        .map(folder => folder.id);
      
      const selectedFileIds = selectedItems
        .filter(item => item.type !== 'application/vnd.google-apps.folder' && !item.isFolder)
        .map(file => file.id);
      
      configData = {
        file_ids: selectedFileIds,
        folder_ids: selectedFolderIds,
        recursive: ingestor.config.recursive,
        session_token: sessionToken || null
      };
    } else {
    
      configData = { ...ingestor.config };
    }

    formData.append('data', JSON.stringify(configData));

    const apiHost: string = import.meta.env.VITE_API_HOST;
    const xhr = new XMLHttpRequest();
    xhr.upload.addEventListener('progress', (event: ProgressEvent) => {
      if (event.lengthComputable) {
        const progressPercentage = +(
          (event.loaded / event.total) *
          100
        ).toFixed(2);
        setProgress({ type: 'UPLOAD', percentage: progressPercentage });
      }
    });
    xhr.onload = () => {
      const response = JSON.parse(xhr.responseText) as { task_id: string };
      setTimeoutRef.current = window.setTimeout(() => {
        setProgress({
          type: 'TRAINING',
          percentage: 0,
          taskId: response.task_id,
        });
      }, 3000);
    };
    xhr.open('POST', `${apiHost}/api/remote`);
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.send(formData);
  };

  useEffect(() => {
    if (ingestor.type === 'google_drive') {
      const sessionToken = localStorage.getItem('google_drive_session_token');
      
      if (sessionToken) {
        // Auto-authenticate if session token exists
        setIsGoogleDriveConnected(true);
        setAuthError('');
        
        // Fetch user email and files using the existing session token
        fetchUserEmailAndLoadFiles(sessionToken);
      }
    }
  }, [ingestor.type]);

  const fetchUserEmailAndLoadFiles = async (sessionToken: string) => {
    try {
      const apiHost = import.meta.env.VITE_API_HOST;
      
      const validateResponse = await fetch(`${apiHost}/api/connectors/validate-session`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ provider: 'google_drive', session_token: sessionToken })
      });
      
      if (!validateResponse.ok) {
        localStorage.removeItem('google_drive_session_token');
        setIsGoogleDriveConnected(false);
        setAuthError('Session expired. Please reconnect to Google Drive.');
        return;
      }
      
      const validateData = await validateResponse.json();
      
      if (validateData.success) {
        setUserEmail(validateData.user_email || 'Connected User');
        loadGoogleDriveFiles(sessionToken, null);
      } else {
        localStorage.removeItem('google_drive_session_token');
        setIsGoogleDriveConnected(false);
        setAuthError(validateData.error || 'Session expired. Please reconnect your Google Drive account and make sure to grant offline access.');
      }
    } catch (error) {
      console.error('Error validating Google Drive session:', error);
      setAuthError('Failed to validate session. Please reconnect.');
      setIsGoogleDriveConnected(false);
    }
  };

  const loadGoogleDriveFiles = async (sessionToken: string, folderId?: string | null) => {
    setIsLoadingFiles(true);

    try {
      const apiHost = import.meta.env.VITE_API_HOST;
      const requestBody: any = {
        session_token: sessionToken,
        limit: 50
      };
      if (folderId) {
        requestBody.folder_id = folderId;
      }

      const filesResponse = await fetch(`${apiHost}/api/connectors/files`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ ...requestBody, provider: 'google_drive' })
      });

      if (!filesResponse.ok) {
        throw new Error(`Failed to load files: ${filesResponse.status}`);
      }

      const filesData = await filesResponse.json();

      if (filesData.success && filesData.files) {
        setGoogleDriveFiles(filesData.files);
      } else {
        throw new Error(filesData.error || 'Failed to load files');
      }

    } catch (error) {
      console.error('Error loading Google Drive files:', error);
      setAuthError(error instanceof Error ? error.message : 'Failed to load files. Please make sure your Google Drive account is properly connected and you granted offline access during authorization.');

      // Fallback to mock data for demo purposes
      console.log('Using mock data as fallback...');
      const mockFiles = [
        {
          id: '1',
          name: 'Project Documentation.pdf',
          type: 'application/pdf',
          size: '2.5 MB',
          modifiedTime: '2024-01-15',
          iconUrl: '�'
        },
        {
          id: '2',
          name: 'Meeting Notes.docx',
          type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
          size: '1.2 MB',
          modifiedTime: '2024-01-14',
          iconUrl: '�'
        },
        {
          id: '3',
          name: 'Presentation.pptx',
          type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
          size: '5.8 MB',
          modifiedTime: '2024-01-13',
          iconUrl: '�'
        },
        {
          id: 'folder1',
          name: 'Documents',
          type: 'application/vnd.google-apps.folder',
          size: '0 bytes',
          modifiedTime: '2024-01-13',
          iconUrl: '📁',
          isFolder: true
        }
      ];
      setGoogleDriveFiles(mockFiles);
    } finally {
      setIsLoadingFiles(false);
    }
  };

  // Handle file selection
  const handleFileSelect = (fileId: string) => {
    setSelectedFiles(prev => {
      if (prev.includes(fileId)) {
        return prev.filter(id => id !== fileId);
      } else {
        return [...prev, fileId];
      }
    });
  };

  const handleFolderClick = (folderId: string, folderName: string) => {
    const sessionToken = localStorage.getItem('google_drive_session_token');
    if (sessionToken) {
      setCurrentFolderId(folderId);
      setFolderPath(prev => [...prev, {id: folderId, name: folderName}]);
      loadGoogleDriveFiles(sessionToken, folderId);
    }
  };

  const navigateBack = (index: number) => {
    const sessionToken = localStorage.getItem('google_drive_session_token');
    if (sessionToken) {
      const newPath = folderPath.slice(0, index + 1);
      const targetFolderId = newPath[newPath.length - 1]?.id;

      setCurrentFolderId(targetFolderId);
      setFolderPath(newPath);
      loadGoogleDriveFiles(sessionToken, targetFolderId);
    }
  };

  const handleSelectAll = () => {
    if (selectedFiles.length === googleDriveFiles.length) {
      setSelectedFiles([]);
    } else {
      setSelectedFiles(googleDriveFiles.map(file => file.id));
    }
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    multiple: true,
    onDragEnter: doNothing,
    onDragOver: doNothing,
    onDragLeave: doNothing,
    maxSize: 25000000,
    accept: {
      'application/pdf': ['.pdf'],
      'text/plain': ['.txt'],
      'text/x-rst': ['.rst'],
      'text/x-markdown': ['.md'],
      'application/zip': ['.zip'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document':
        ['.docx'],
      'application/json': ['.json'],
      'text/csv': ['.csv'],
      'text/html': ['.html'],
      'application/epub+zip': ['.epub'],
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': [
        '.xlsx',
      ],
      'application/vnd.openxmlformats-officedocument.presentationml.presentation':
        ['.pptx'],
      'image/png': ['.png'],
      'image/jpeg': ['.jpeg'],
      'image/jpg': ['.jpg'],
    },
  });

  const isUploadDisabled = (): boolean => {
    if (activeTab === 'file') {
      return !docName?.trim() || files.length === 0;
    }
    if (activeTab === 'remote') {
      if (!remoteName?.trim()) {
        return true;
      }
      if (ingestor.type === 'google_drive') {
        return !isGoogleDriveConnected || selectedFiles.length === 0;
      }

      const formFields: FormField[] = IngestorFormSchemas[ingestor.type];
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
    }
    return true;
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
  const handleIngestorTypeChange = (type: IngestorType) => {
    //Updates the ingestor seleced in dropdown and resets the config to the default config for that type
    const defaultConfig = IngestorDefaultConfigs[type];

    setIngestor({
      type,
      name: defaultConfig.name,
      config: defaultConfig.config,
    });
  };

  let view;

  if (progress?.type === 'UPLOAD') {
    view = <UploadProgress></UploadProgress>;
  } else if (progress?.type === 'TRAINING') {
    view = <TrainingProgress></TrainingProgress>;
  } else {
    view = (
      <div className="flex w-full flex-col gap-4">
        <p className="text-jet dark:text-bright-gray text-center text-2xl font-semibold">
          {t('modals.uploadDoc.label')}
        </p>
        {!activeTab && (
          <div>
            <p className="dark text-gray-6000 dark:text-bright-gray text-center text-sm font-medium">
              {t('modals.uploadDoc.select')}
            </p>
            <div className="flex h-full w-full flex-col items-center justify-center gap-4 p-4 md:flex-row md:gap-4">
              <button
                onClick={() => setActiveTab('file')}
                className="hover:border-purple-30 hover:shadow-purple-30/30 flex h-40 w-40 flex-col items-center justify-center gap-4 rounded-3xl border border-[#D7D7D7] bg-transparent p-8 text-sm font-medium text-[#777777] opacity-85 hover:opacity-100 hover:shadow-lg md:h-52 md:w-52 dark:bg-transparent dark:text-[#c3c3c3]"
              >
                <img
                  src={FileUpload}
                  className="mr-2 h-12 w-12 dark:brightness-50 dark:invert dark:filter"
                />
                {t('modals.uploadDoc.file')}
              </button>
              <button
                onClick={() => setActiveTab('remote')}
                className="hover:border-purple-30 hover:shadow-purple-30/30 flex h-40 w-40 flex-col items-center justify-center gap-4 rounded-3xl border border-[#D7D7D7] bg-transparent p-8 text-sm font-medium text-[#777777] opacity-85 hover:opacity-100 hover:shadow-lg md:h-52 md:w-52 dark:bg-transparent dark:text-[#c3c3c3]"
              >
                <img
                  src={WebsiteCollect}
                  className="mr-2 h-14 w-14 dark:brightness-50 dark:invert dark:filter"
                />
                {t('modals.uploadDoc.remote')}
              </button>
            </div>
          </div>
        )}

        {activeTab === 'file' && (
          <>
            <Input
              type="text"
              colorVariant="silver"
              value={docName}
              onChange={(e) => setDocName(e.target.value)}
              borderVariant="thin"
              placeholder={t('modals.uploadDoc.name')}
              labelBgClassName="bg-white dark:bg-charleston-green-2"
              required={true}
            />
            <div className="my-2" {...getRootProps()}>
              <span className="text-purple-30 dark:text-silver rounded-3xl border border-[#7F7F82] bg-transparent px-4 py-2 font-medium hover:cursor-pointer">
                <input type="button" {...getInputProps()} />
                {t('modals.uploadDoc.choose')}
              </span>
            </div>
            <p className="text-gray-4000 mb-0 text-xs italic">
              {t('modals.uploadDoc.info')}
            </p>
            <div className="mt-0 max-w-full">
              <p className="text-eerie-black dark:text-light-gray mb-[14px] text-[14px] font-medium">
                {t('modals.uploadDoc.uploadedFiles')}
              </p>
              <div className="max-w-full overflow-hidden">
                {files.map((file) => (
                  <p
                    key={file.name}
                    className="text-gray-6000 dark:text-[#ececf1] truncate overflow-hidden text-ellipsis"
                    title={file.name}
                  >
                    {file.name}
                  </p>
                ))}
                {files.length === 0 && (
                  <p className="text-gray-6000 dark:text-light-gray text-[14px]">
                    {t('none')}
                  </p>
                )}
              </div>
            </div>
          </>
        )}
        {activeTab === 'remote' && (
          <>
            <Dropdown
              options={urlOptions}
              selectedValue={
                urlOptions.find((opt) => opt.value === ingestor.type) || null
              }
              onSelect={(selected: { label: string; value: string }) =>
                handleIngestorTypeChange(selected.value as IngestorType)
              }
              size="w-full"
              rounded="3xl"
              border="border"
              placeholder="Select ingestor type"
              placeholderClassName="text-gray-400 dark:text-silver"
            />
            {/* Dynamically render form fields based on schema */}

            <Input
              type="text"
              colorVariant="silver"
              value={remoteName}
              onChange={(e) => setRemoteName(e.target.value)}
              borderVariant="thin"
              placeholder="Name"
              required={true}
              labelBgClassName="bg-white dark:bg-charleston-green-2"
            />
            {ingestor.type === 'google_drive' && (
              <div className="space-y-4">
                {authError && (
                  <div className="rounded-lg border border-red-200 bg-red-50 p-3 dark:border-red-600 dark:bg-red-900/20">
                    <p className="text-sm text-red-600 dark:text-red-400">
                      ⚠️ {authError}
                    </p>
                  </div>
                )}

                {!isGoogleDriveConnected ? (
                  <ConnectorAuth
                    provider="google_drive"
                    onSuccess={(data) => {
                      setUserEmail(data.user_email);
                      setIsGoogleDriveConnected(true);
                      setIsAuthenticating(false);
                      setAuthError('');
                      
                      if (data.session_token) {
                        localStorage.setItem('google_drive_session_token', data.session_token);
                        loadGoogleDriveFiles(data.session_token, null);
                      }
                    }}
                    onError={(error) => {
                      setAuthError(error);
                      setIsAuthenticating(false);
                      setIsGoogleDriveConnected(false);
                    }}
                  />
                ) : (
                  <div className="space-y-4">
                    {/* Connection Status */}
                    <div className="w-full flex items-center justify-between rounded-lg bg-green-500 px-4 py-2 text-white text-sm">
                      <div className="flex items-center gap-2">
                        <svg className="h-4 w-4" viewBox="0 0 24 24">
                          <path fill="currentColor" d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
                        </svg>
                        <span>Connected as {userEmail}</span>
                      </div>
                      <button
                        onClick={() => {
                          localStorage.removeItem('google_drive_session_token');
                          
                          setIsGoogleDriveConnected(false);
                          setGoogleDriveFiles([]);
                          setSelectedFiles([]);
                          setUserEmail('');
                          setAuthError('');
                          
                          const apiHost = import.meta.env.VITE_API_HOST;
                          fetch(`${apiHost}/api/connectors/disconnect`, {
                            method: 'POST',
                            headers: {
                              'Content-Type': 'application/json',
                              'Authorization': `Bearer ${token}`
                            },
                            body: JSON.stringify({ provider: 'google_drive', session_token: localStorage.getItem('google_drive_session_token') })
                          }).catch(err => console.error('Error disconnecting from Google Drive:', err));
                        }}
                        className="text-white hover:text-gray-200 text-xs underline"
                      >
                        Disconnect
                      </button>
                    </div>

                    {/* File Browser */}
                    <div className="border border-gray-200 rounded-lg dark:border-gray-600">
                      <div className="p-3 border-b border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-800 rounded-t-lg">
                        {/* Breadcrumb navigation */}
                        <div className="flex items-center gap-1 mb-2">
                          {folderPath.map((path, index) => (
                            <div key={path.id || 'root'} className="flex items-center gap-1">
                              {index > 0 && <span className="text-gray-400">/</span>}
                              <button
                                onClick={() => navigateBack(index)}
                                className="text-sm text-blue-600 hover:text-blue-800 dark:text-blue-400 hover:underline"
                                disabled={index === folderPath.length - 1}
                              >
                                {path.name}
                              </button>
                            </div>
                          ))}
                        </div>

                        <div className="flex items-center justify-between">
                          <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300">
                            Select Files from Google Drive
                          </h4>
                          {googleDriveFiles.length > 0 && (
                            <button
                              onClick={handleSelectAll}
                              className="text-xs text-blue-600 hover:text-blue-800 dark:text-blue-400"
                            >
                              {selectedFiles.length === googleDriveFiles.length ? 'Deselect All' : 'Select All'}
                            </button>
                          )}
                        </div>
                        {selectedFiles.length > 0 && (
                          <p className="text-xs text-gray-500 mt-1">
                            {selectedFiles.length} file{selectedFiles.length !== 1 ? 's' : ''} selected
                          </p>
                        )}
                      </div>

                      <div className="max-h-64 overflow-y-auto">
                        {isLoadingFiles ? (
                          <div className="p-4 text-center">
                            <div className="inline-flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
                              <div className="h-4 w-4 animate-spin rounded-full border-2 border-blue-500 border-t-transparent"></div>
                              Loading files...
                            </div>
                          </div>
                        ) : googleDriveFiles.length === 0 ? (
                          <div className="p-4 text-center text-sm text-gray-500 dark:text-gray-400">
                            No files found in your Google Drive
                          </div>
                        ) : (
                          <div className="divide-y divide-gray-200 dark:divide-gray-600">
                            {googleDriveFiles.map((file) => (
                              <div
                                key={file.id}
                                className={`p-3 transition-colors ${
                                  selectedFiles.includes(file.id) ? 'bg-blue-50 dark:bg-blue-900/20' : ''
                                }`}
                              >
                                <div className="flex items-center gap-3">
                                  <div className="flex-shrink-0">
                                    <input
                                      type="checkbox"
                                      checked={selectedFiles.includes(file.id)}
                                      onChange={() => handleFileSelect(file.id)}
                                      className="h-4 w-4 text-blue-600 rounded border-gray-300 focus:ring-blue-500"
                                    />
                                  </div>
                                  {file.type === 'application/vnd.google-apps.folder' || file.isFolder ? (
                                    <div
                                      className="text-lg cursor-pointer hover:text-blue-600"
                                      onClick={() => handleFolderClick(file.id, file.name)}
                                    >
                                      <img src={FolderIcon} alt="Folder" className="h-6 w-6" />
                                    </div>
                                  ) : (
                                    <div className="text-lg">
                                      <img src={FileIcon} alt="File" className="h-6 w-6" />
                                    </div>
                                  )}
                                  <div className="flex-1 min-w-0">
                                    <p
                                      className={`text-sm font-medium truncate dark:text-[#ececf1] ${
                                        file.type === 'application/vnd.google-apps.folder' || file.isFolder
                                          ? 'cursor-pointer hover:text-blue-600'
                                          : ''
                                      }`}
                                      onClick={() => {
                                        if (file.type === 'application/vnd.google-apps.folder' || file.isFolder) {
                                          handleFolderClick(file.id, file.name);
                                        }
                                      }}
                                    >
                                      {file.name}
                                    </p>
                                    <p className="text-xs text-gray-500 dark:text-gray-400">
                                      {file.size} • Modified {file.modifiedTime}
                                    </p>
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {renderFormFields()}
            {IngestorFormSchemas[ingestor.type].some(
              (field) => field.advanced,
            ) && (
              <button
                onClick={() => setShowAdvancedOptions(!showAdvancedOptions)}
                className="text-purple-30 bg-transparent py-2 pl-0 text-left text-sm font-normal hover:cursor-pointer"
              >
                {showAdvancedOptions
                  ? t('modals.uploadDoc.hideAdvanced')
                  : t('modals.uploadDoc.showAdvanced')}
              </button>
            )}
          </>
        )}
        <div className="flex justify-end gap-4">
          {activeTab && (
            <button
              onClick={() => setActiveTab(null)}
              className="text-purple-30 dark:text-silver rounded-3xl bg-transparent px-4 py-2 text-[14px] font-medium hover:cursor-pointer"
            >
              {t('modals.uploadDoc.back')}
            </button>
          )}
          {activeTab && (
            <button
              onClick={() => {
                if (activeTab === 'file') {
                  uploadFile();
                } else {
                  uploadRemote();
                }
              }}
              disabled={isUploadDisabled()}
              className={`rounded-3xl px-4 py-2 text-[14px] font-medium ${
                isUploadDisabled()
                  ? 'cursor-not-allowed bg-gray-300 text-gray-500'
                  : 'bg-purple-30 hover:bg-violets-are-blue cursor-pointer text-white'
              }`}
            >
              {ingestor.type === 'google_drive' && selectedFiles.length > 0
                ? `Train with ${selectedFiles.length} file${selectedFiles.length !== 1 ? 's' : ''}`
                : t('modals.uploadDoc.train')
              }
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <WrapperModal
      isPerformingTask={progress !== undefined && progress.percentage < 100}
      close={() => {
        close();
        setDocName('');
        setfiles([]);
        setModalState('INACTIVE');
        setActiveTab(null);
      }}
    >
      {view}
    </WrapperModal>
  );
}

export default Upload;
