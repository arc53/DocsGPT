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
import { ActiveState, Doc } from '../models/misc';
import { getDocs } from '../preferences/preferenceApi';
import {
  setSelectedDocs,
  setSourceDocs,
  selectSourceDocs,
} from '../preferences/preferenceSlice';
import WrapperModal from '../modals/WrapperModal';
import {
  IngestorType,
  IngestorConfig,
  RedditIngestorConfig,
  GithubIngestorConfig,
  CrawlerIngestorConfig,
  UrlIngestorConfig,
  IngestorFormSchemas,
  FormField,
} from './types/ingestor';
import { IngestorDefaultConfigs } from '../upload/types/ingestor';

type IngestorState = {
  type: IngestorType;
  name: string;
  config:
    | RedditIngestorConfig
    | GithubIngestorConfig
    | CrawlerIngestorConfig
    | UrlIngestorConfig;
};

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
  const [docName, setDocName] = useState(receivedFile[0]?.name);
  const [files, setfiles] = useState<File[]>(receivedFile);
  const [activeTab, setActiveTab] = useState<string | null>(renderTab);

  const renderFormFields = () => {
    const schema = IngestorFormSchemas[ingestor.type];

    return schema.map((field: FormField) => {
      switch (field.type) {
        case 'string':
          return (
            <div key={field.name} className="mb-4">
              <Input
                placeholder={field.label}
                type="text"
                name={field.name}
                value={(ingestor.config as any)[field.name]}
                onChange={(e) =>
                  handleIngestorChange(field.name, e.target.value)
                }
                borderVariant="thin"
                label={field.label}
                colorVariant="gray"
              />
            </div>
          );
        case 'number':
          return (
            <div key={field.name} className="mb-4">
              <Input
                placeholder={field.label}
                type="number"
                name={field.name}
                value={(ingestor.config as any)[field.name]}
                onChange={(e) =>
                  handleIngestorChange(field.name, parseInt(e.target.value))
                }
                borderVariant="thin"
                label={field.label}
                colorVariant="gray"
              />
            </div>
          );
        case 'enum':
          return (
            <div key={field.name} className="mb-4">
              <Dropdown
                key={field.name}
                options={field.options || []}
                selectedValue={(ingestor.config as any)[field.name]}
                onSelect={(
                  selected: { label: string; value: string } | string,
                ) => {
                  const value =
                    typeof selected === 'string' ? selected : selected.value;
                  handleIngestorChange(field.name, value);
                }}
                size="w-full"
                rounded="3xl"
                placeholder={field.label}
                border="border"
                borderColor="gray-5000"
              />
            </div>
          );
        case 'boolean':
          return (
            <div key={field.name} className="mb-4">
              <ToggleSwitch
                label={field.label}
                checked={(ingestor.config as any)[field.name]}
                onChange={(checked: boolean) => {
                  const syntheticEvent = {
                    target: {
                      name: field.name,
                      value: checked,
                    },
                  } as unknown as React.ChangeEvent<HTMLInputElement>;
                  handleIngestorChange(field.name, syntheticEvent.target.value);
                }}
                className="mt-2"
              />
            </div>
          );
        default:
          return null;
      }
    });
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
  const setTimeoutRef = useRef<number | null>();

  const urlOptions: { label: string; value: IngestorType }[] = [
    { label: 'Crawler', value: 'crawler' },
    { label: 'Link', value: 'url' },
    { label: 'GitHub', value: 'github' },
    { label: 'Reddit', value: 'reddit' },
  ];

  const [urlType, setUrlType] = useState<{ label: string; value: string }>({
    label: 'Crawler',
    value: 'crawler',
  });

  const sourceDocs = useSelector(selectSourceDocs);
  useEffect(() => {
    if (setTimeoutRef.current) {
      clearTimeout(setTimeoutRef.current);
    }
  }, []);

  function ProgressBar({ progressPercent }: { progressPercent: number }) {
    return (
      <div className="flex items-center justify-center h-full w-full my-8">
        <div className="relative w-32 h-32 rounded-full">
          <div className="absolute inset-0 rounded-full shadow-[0_0_10px_2px_rgba(0,0,0,0.3)_inset] dark:shadow-[0_0_10px_2px_rgba(0,0,0,0.3)_inset]"></div>
          <div
            className={`absolute inset-0 rounded-full ${progressPercent === 100 ? 'shadow-xl shadow-lime-300/50 dark:shadow-lime-300/50 bg-gradient-to-r from-white to-gray-400 dark:bg-gradient-to-br dark:from-gray-500 dark:to-gray-300' : 'shadow-[0_4px_0_#7D54D1] dark:shadow-[0_4px_0_#7D54D1]'}`}
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
      <div className="mt-5 flex flex-col items-center gap-2 text-gray-2000 dark:text-bright-gray">
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
              className="cursor-pointer rounded-3xl text-sm h-[42px] px-[28px] py-[6px] bg-[#7D54D1] text-white hover:bg-[#6F3FD1] shadow-lg"
            >
              {t('modals.uploadDoc.start')}
            </button>
          ) : (
            <button
              className="ml-2 cursor-pointer rounded-3xl text-sm h-[42px] px-[28px] py-[6px] bg-[#7D54D14D] text-white shadow-lg"
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
            .getTaskStatus(progress?.taskId as string)
            .then((data) => data.json())
            .then((data) => {
              if (data.status == 'SUCCESS') {
                if (data.result.limited === true) {
                  getDocs().then((data) => {
                    dispatch(setSourceDocs(data));
                    dispatch(
                      setSelectedDocs(
                        Array.isArray(data) &&
                          data?.find(
                            (d: Doc) => d.type?.toLowerCase() === 'local',
                          ),
                      ),
                    );
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
                  getDocs().then((data) => {
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
    setDocName(acceptedFiles[0]?.name);
  }, []);

  const doNothing = () => undefined;

  const uploadFile = () => {
    const formData = new FormData();
    files.forEach((file) => {
      formData.append('file', file);
    });

    formData.append('name', activeTab === 'file' ? docName : ingestor.name);
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
    xhr.send(formData);
  };

  const uploadRemote = () => {
    const formData = new FormData();
    formData.append('name', ingestor.name);
    formData.append('user', 'local');
    formData.append('source', ingestor.type);

    if (ingestor.type === 'reddit') {
      const redditConfig = ingestor.config as RedditIngestorConfig;
      redditConfig.name = ingestor.name;
      formData.set('data', JSON.stringify(redditConfig));
    } else if (ingestor.type === 'github') {
      const githubConfig = ingestor.config as GithubIngestorConfig;
      githubConfig.name = ingestor.name;
      formData.append('repo_url', githubConfig.repo_url);
      formData.append('data', githubConfig.repo_url);
    } else {
      const urlBasedConfig = ingestor.config as
        | CrawlerIngestorConfig
        | UrlIngestorConfig;
      urlBasedConfig.name = ingestor.name;
      formData.append('data', urlBasedConfig.url);
    }

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
    xhr.open('POST', `${apiHost + '/api/remote'}`);
    xhr.send(formData);
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

  const isUploadDisabled = () => {
    if (activeTab === 'file') {
      return !docName || files.length === 0;
    }

    if (activeTab !== 'remote') return false;

    if (!ingestor.name) return true;

    return Object.values(ingestor.config).some((value) => {
      if (Array.isArray(value)) {
        return value.length === 0;
      }
      return !value;
    });
  };

  const handleIngestorChange = (key: string, value: any) => {
    setIngestor((prevState: IngestorConfig): IngestorConfig => {
      if (key === 'name') {
        return {
          ...prevState,
          name: value,
        };
      }

      return {
        ...prevState,
        config: {
          ...(prevState.config as any),
          [key]: value,
        },
      };
    });
  };

  const handleIngestorTypeChange = (type: IngestorType) => {
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
      <div className="flex flex-col gap-4 w-full">
        <p className="text-2xl text-jet dark:text-bright-gray text-center font-semibold">
          {t('modals.uploadDoc.label')}
        </p>
        {!activeTab && (
          <div>
            <p className="text-gray-6000 dark:text-bright-gray text-sm text-center font-medium">
              {t('modals.uploadDoc.select')}
            </p>
            <div className="w-full gap-4 h-full p-4 flex flex-col md:flex-row md:gap-4 justify-center items-center">
              <button
                onClick={() => setActiveTab('file')}
                className="opacity-85 hover:opacity-100 rounded-3xl text-sm font-medium border flex flex-col items-center justify-center hover:shadow-purple-30/30 hover:shadow-lg p-8 gap-4 bg-white text-[#777777] dark:bg-outer-space dark:text-[#c3c3c3] hover:border-purple-30 border-[#D7D7D7] h-40 w-40 md:w-52 md:h-52"
              >
                <img
                  src={FileUpload}
                  className="w-12 h-12 mr-2 dark:filter dark:invert dark:brightness-50"
                />
                {t('modals.uploadDoc.file')}
              </button>
              <button
                onClick={() => setActiveTab('remote')}
                className="opacity-85 hover:opacity-100 rounded-3xl text-sm font-medium border flex flex-col items-center justify-center hover:shadow-purple-30/30 hover:shadow-lg p-8 gap-4 bg-white text-[#777777] dark:bg-outer-space dark:text-[#c3c3c3] hover:border-purple-30 border-[#D7D7D7] h-40 w-40 md:w-52 md:h-52"
              >
                <img
                  src={WebsiteCollect}
                  className="w-14 h-14 mr-2 dark:filter dark:invert dark:brightness-50"
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
              colorVariant="gray"
              value={docName}
              onChange={(e) => setDocName(e.target.value)}
              borderVariant="thin"
            ></Input>
            <div className="relative bottom-12 left-2 mt-[-20px]">
              <span className="bg-white px-2 text-xs text-gray-4000 dark:bg-outer-space dark:text-silver">
                {t('modals.uploadDoc.name')}
              </span>
            </div>
            <div {...getRootProps()}>
              <span className="rounded-3xl border border-purple-30 px-4 py-2 font-medium text-purple-30 hover:cursor-pointer dark:bg-purple-taupe dark:text-silver">
                <input type="button" {...getInputProps()} />
                {t('modals.uploadDoc.choose')}
              </span>
            </div>
            <p className="mb-0 text-xs italic text-gray-4000">
              {t('modals.uploadDoc.info')}
            </p>
            <div className="mt-0 max-w-full">
              <p className="mb-[14px] font-medium text-eerie-black dark:text-light-gray">
                {t('modals.uploadDoc.uploadedFiles')}
              </p>
              <div className="max-w-full overflow-hidden">
                {files.map((file) => (
                  <p
                    key={file.name}
                    className="text-gray-6000 truncate overflow-hidden text-ellipsis"
                    title={file.name}
                  >
                    {file.name}
                  </p>
                ))}
                {files.length === 0 && (
                  <p className="text-gray-6000 dark:text-light-gray">
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
              border="border"
              options={urlOptions}
              selectedValue={
                urlOptions.find((opt) => opt.value === ingestor.type) || null
              }
              onSelect={(selected: { label: string; value: string }) =>
                handleIngestorTypeChange(selected.value as IngestorType)
              }
              size="w-full"
              rounded="3xl"
            />
            {/* Dynamically render form fields based on schema */}

            <Input
              type="text"
              colorVariant="gray"
              value={ingestor['name']}
              onChange={(e) =>
                setIngestor({ ...ingestor, name: e.target.value })
              }
              borderVariant="thin"
              placeholder="Name"
              label="Name"
            />
            {renderFormFields()}
          </>
        )}
        <div className="flex justify-between">
          {activeTab && (
            <button
              onClick={() => setActiveTab(null)}
              className="rounded-3xl border border-purple-30 px-4 py-2 font-medium text-purple-30 hover:cursor-pointer dark:bg-purple-taupe dark:text-silver"
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
              className={`rounded-3xl px-4 py-2 font-medium ${
                isUploadDisabled()
                  ? 'cursor-not-allowed bg-gray-300 text-gray-500'
                  : 'cursor-pointer bg-purple-30 text-white hover:bg-purple-40'
              }`}
            >
              {t('modals.uploadDoc.train')}
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
