import { useCallback, useEffect, useRef, useState } from 'react';
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
  selectSourceDocs,
  selectToken,
  setSelectedDocs,
  setSourceDocs,
} from '../preferences/preferenceSlice';
import { IngestorDefaultConfigs, IngestorFormSchemas, getIngestorSchema, IngestorOption } from '../upload/types/ingestor';
import {
  FormField,
  IngestorConfig,
  IngestorType,
} from './types/ingestor';

import {FilePicker}  from '../components/FilePicker';
import GoogleDrivePicker from '../components/GoogleDrivePicker';

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
  
  const [files, setfiles] = useState<File[]>(receivedFile);
  const [activeTab, setActiveTab] = useState<boolean>(true);
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);

  // File picker state
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [selectedFolders, setSelectedFolders] = useState<string[]>([]);


  

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
            size="small"
            className={`mt-2 text-base`}
          />
        );
      case 'local_file_picker':
        return (
          <div key={field.name}>
            <div className="mb-3" {...getRootProps()}>
              <span className="inline-block text-purple-30 dark:text-silver rounded-3xl border border-[#7F7F82] bg-transparent px-4 py-2 font-medium hover:cursor-pointer">
                <input type="button" {...getInputProps()} />
                Choose Files
              </span>
            </div>
            <div className="mt-4 max-w-full">
              <p className="text-eerie-black dark:text-light-gray mb-[14px] text-[14px] font-medium">
                Selected Files
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
                    No files selected
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
            onSelectionChange={(selectedFileIds: string[], selectedFolderIds: string[] = []) => {
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
            onSelectionChange={(selectedFileIds: string[], selectedFolderIds: string[] = []) => {
              setSelectedFiles(selectedFileIds);
              setSelectedFolders(selectedFolderIds);
            }}
            token={token}
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

  const [progress, setProgress] = useState<{
    type: 'UPLOAD' | 'TRAINING';
    percentage: number;
    taskId?: string;
    failed?: boolean;
  }>();

  const { t } = useTranslation();
  const setTimeoutRef = useRef<number | null>(null);

  const ingestorOptions: IngestorOption[] = IngestorFormSchemas
    .filter(schema => schema.validate ? schema.validate() : true)
    .map(schema => ({
      label: schema.label,
      value: schema.key,
      icon: schema.icon,
      heading: schema.heading
    }));

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
                setIngestor({ type: null, name: '', config: {} });
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
                  setIngestor({ type: null, name: '', config: {} });
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
    setIngestor(prev => ({ ...prev, name: acceptedFiles[0]?.name || '' }));

    // If we're in local_file mode, update the ingestor config
    if (ingestor.type === 'local_file') {
      setIngestor((prevState) => ({
        ...prevState,
        config: {
          ...prevState.config,
          files: acceptedFiles,
        },
      }));
    }
  }, [ingestor.type]);

  const doNothing = () => undefined;

  const uploadFile = () => {
    const formData = new FormData();
    files.forEach((file) => {
      formData.append('file', file);
    });

    formData.append('name', ingestor.name);
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
    if (!ingestor.type) return;
    const formData = new FormData();
    formData.append('name', ingestor.name);
    formData.append('user', 'local');
    formData.append('source', ingestor.type as string);

    let configData: any = {};

    const ingestorSchema = getIngestorSchema(ingestor.type as IngestorType);
    if (!ingestorSchema) return;
    const schema: FormField[] = ingestorSchema.fields;
    const hasLocalFilePicker = schema.some((field: FormField) => field.type === 'local_file_picker');
    const hasRemoteFilePicker = schema.some((field: FormField) => field.type === 'remote_file_picker');
    const hasGoogleDrivePicker = schema.some((field: FormField) => field.type === 'google_drive_picker');

    if (hasLocalFilePicker) {
      files.forEach((file) => {
        formData.append('file', file);
      });
      configData = { ...ingestor.config };
    } else if (hasRemoteFilePicker || hasGoogleDrivePicker) {
      const sessionToken = getSessionToken(ingestor.type as string);
      configData = {
        provider: ingestor.type as string,
        session_token: sessionToken,
        file_ids: selectedFiles,
        folder_ids: selectedFolders,
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

    const endpoint = ingestor.type === 'local_file' ? `${apiHost}/api/upload` : `${apiHost}/api/remote`;

    xhr.open('POST', endpoint);
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.send(formData);
  };

  

  const { getRootProps, getInputProps } = useDropzone({
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
    if (!activeTab) return true;

    if (!ingestor.name?.trim()) {
      return true;
    }

    if (!ingestor.type) return true;
    const ingestorSchemaForValidation = getIngestorSchema(ingestor.type as IngestorType);
    if (!ingestorSchemaForValidation) return true;
    const schema: FormField[] = ingestorSchemaForValidation.fields;
    const hasLocalFilePicker = schema.some((field: FormField) => field.type === 'local_file_picker');
    const hasRemoteFilePicker = schema.some((field: FormField) => field.type === 'remote_file_picker');
    const hasGoogleDrivePicker = schema.some((field: FormField) => field.type === 'google_drive_picker');

    if (hasLocalFilePicker) {
      if (files.length === 0) {
        return true;
      }
    } else if (hasRemoteFilePicker || hasGoogleDrivePicker) {
      if (selectedFiles.length === 0 && selectedFolders.length === 0) {
        return true;
      }
    }

    const ingestorSchemaForFields = getIngestorSchema(ingestor.type as IngestorType);
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
      return;
    }

    const defaultConfig = IngestorDefaultConfigs[type];
    setIngestor({
      type,
      name: defaultConfig.name,
      config: defaultConfig.config,
    });

    // Clear files if switching away from local_file
    if (type !== 'local_file') {
      setfiles([]);
    }
  };

  const renderIngestorSelection = () => {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4 w-full">
        {ingestorOptions.map((option) => (
          <div
            key={option.value}
            className={`relative flex flex-col justify-between rounded-2xl cursor-pointer w-full h-[91.2px] border border-solid pt-[21.1px] pr-[21px] pb-[15px] pl-[21px] gap-2 transition-colors duration-300 ease-out mx-auto ${
              ingestor.type === option.value 
                ? 'bg-[#7D54D1] text-white border-[#7D54D1]' 
                : 'bg-transparent hover:bg-[#ECECEC]/30 dark:hover:bg-[#383838]/30 border-[#D7D7D7] dark:border-[#4A4A4A] hover:shadow-[0_0_15px_0_#00000026] transition-shadow duration-300'
            }`}
            onClick={() => handleIngestorTypeChange(option.value as IngestorType)}
          >
            <div className="flex flex-col justify-between h-full">
              <div className="w-6 h-6">
                <img 
                  src={option.icon} 
                  alt={option.label} 
                  className={`${ingestor.type === option.value ? 'filter invert' : ''} dark:filter dark:invert`}
                />
              </div>
              <p className="font-inter font-semibold text-[13px] leading-[18px] self-start">
                {option.label}
              </p>
            </div>
          </div>
        ))}
      </div>
    );
  };
  let view;

  if (progress?.type === 'UPLOAD') {
    view = <UploadProgress></UploadProgress>;
  } else if (progress?.type === 'TRAINING') {
    view = <TrainingProgress></TrainingProgress>;
  }   else {
    view = (
      <div className="flex w-full flex-col gap-6">
        {!ingestor.type && (
          <p className="text-[#18181B] dark:text-[#ECECF1] text-left font-inter font-semibold text-[20px] leading-[28px] tracking-[0.15px]">
            Select the way to add your source
          </p>
        )}
        
        {activeTab && (
          <>
            {!ingestor.type && renderIngestorSelection()}
            {ingestor.type && (
              <div className="flex flex-col gap-4">
                <button
                  onClick={() => handleIngestorTypeChange(null)}
                  className="flex items-center gap-2 text-[#777777] hover:text-[#555555] w-fit"
                >
                  <img 
                    src={ChevronRight} 
                    alt="back" 
                    className="h-3 w-3 transform rotate-180" 
                  />
                  <span>Back</span>
                </button>

                <h2 className="font-inter font-semibold text-[22px] leading-[28px] tracking-[0.15px] text-black dark:text-[#E0E0E0]">
                  {ingestor.type && getIngestorSchema(ingestor.type as IngestorType)?.heading}
                </h2>

                <Input
                  type="text"
                  colorVariant="silver"
                  value={ingestor.name}
                  onChange={(e) => {
                    setIngestor((prevState) => ({
                      ...prevState,
                      name: e.target.value,
                    }));
                  }}
                  borderVariant="thin"
                  placeholder="Name"
                  required={true}
                  labelBgClassName="bg-white dark:bg-charleston-green-2"
                  className="w-full"
                />
                {renderFormFields()}
              </div>
            )}
  
            {ingestor.type && getIngestorSchema(ingestor.type as IngestorType)?.fields.some(
              (field: FormField) => field.advanced,
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
          {activeTab && ingestor.type && (
            <button
              onClick={() => {
                if (!ingestor.type) return;
                const ingestorSchemaForUpload = getIngestorSchema(ingestor.type as IngestorType);
                if (!ingestorSchemaForUpload) return;
                const schema: FormField[] = ingestorSchemaForUpload.fields;
                const hasLocalFilePicker = schema.some((field: FormField) => field.type === 'local_file_picker');

                if (hasLocalFilePicker) {
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
        setIngestor({ type: null, name: '', config: {} });
        setfiles([]);
        setModalState('INACTIVE');
      }}
      className="w-11/12 sm:w-auto sm:min-w-[600px] md:min-w-[700px] max-h-[90vh] sm:max-h-none"
      contentClassName="max-h-[80vh] sm:max-h-none"
    >
      {view}
    </WrapperModal>
  );
}

export default Upload;
