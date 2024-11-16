import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import ArrowLeft from '../assets/arrow-left.svg';
import FileUpload from '../assets/file_upload.svg';
import WebsiteCollect from '../assets/website_collect.svg';
import Dropdown from '../components/Dropdown';
import Input from '../components/Input';
import { ActiveState, Doc } from '../models/misc';
import { getDocs } from '../preferences/preferenceApi';
import {
  setSelectedDocs,
  setSourceDocs,
  selectSourceDocs,
} from '../preferences/preferenceSlice';
import WrapperModal from '../modals/WrapperModal';

function Upload({
  setModalState,
  isOnboarding,
  close,
}: {
  setModalState: (state: ActiveState) => void;
  isOnboarding: boolean;
  close: () => void;
}) {
  const [docName, setDocName] = useState('');
  const [urlName, setUrlName] = useState('');
  const [url, setUrl] = useState('');
  const [repoUrl, setRepoUrl] = useState(''); // P3f93
  const [redditData, setRedditData] = useState({
    client_id: '',
    client_secret: '',
    user_agent: '',
    search_queries: [''],
    number_posts: 10,
  });
  const [activeTab, setActiveTab] = useState<string | null>(null);
  const [files, setfiles] = useState<File[]>([]);
  const [progress, setProgress] = useState<{
    type: 'UPLOAD' | 'TRAINING';
    percentage: number;
    taskId?: string;
    failed?: boolean;
  }>();

  const { t } = useTranslation();
  const setTimeoutRef = useRef<number | null>();

  const urlOptions: { label: string; value: string }[] = [
    { label: 'Crawler', value: 'crawler' },
    // { label: 'Sitemap', value: 'sitemap' },
    { label: 'Link', value: 'url' },
    { label: 'Reddit', value: 'reddit' },
    { label: 'GitHub', value: 'github' }, // P3f93
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
            className={`absolute inset-0 rounded-full ${progressPercent === 100 ? 'shadow-xl shadow-lime-300/50 dark:shadow-lime-300/50 bg-gradient-to-r from-white to-gray-400 dark:bg-gradient-to-br dark:from-gray-500 dark:to-gray-300' : 'shadow-[0_2px_0_#FF3D00_inset] dark:shadow-[0_2px_0_#FF3D00_inset]'}`}
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
            (progress?.percentage === 100 ? 'Training completed' : title)}
          {!isTraining && title}
        </p>
        <p className="text-sm">This may take several minutes</p>
        <p className={`ml-5 text-xl text-red-400 ${isFailed ? '' : 'hidden'}`}>
          Over the token limit, please consider uploading smaller document
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
    return <Progress title="Upload is in progress"></Progress>;
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
        title="Training is in progress"
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
    xhr.send(formData);
  };

  const uploadRemote = () => {
    const formData = new FormData();
    formData.append('name', urlName);
    formData.append('user', 'local');
    if (urlType !== null) {
      formData.append('source', urlType?.value);
    }
    formData.append('data', url);
    if (
      redditData.client_id.length > 0 &&
      redditData.client_secret.length > 0
    ) {
      formData.set('name', 'other');
      formData.set('data', JSON.stringify(redditData));
    }
    if (urlType.value === 'github') {
      formData.append('repo_url', repoUrl); // Pdeac
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
    },
  });

  const handleChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
  ) => {
    const { name, value } = e.target;
    if (name === 'search_queries' && value.length > 0) {
      setRedditData({
        ...redditData,
        [name]: value.split(',').map((item) => item.trim()),
      });
    } else
      setRedditData({
        ...redditData,
        [name]: name === 'number_posts' ? parseInt(value) : value,
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
            <div className="mt-0">
              <p className="mb-[14px] font-medium text-eerie-black dark:text-light-gray">
                {t('modals.uploadDoc.uploadedFiles')}
              </p>
              {files.map((file) => (
                <p key={file.name} className="text-gray-6000">
                  {file.name}
                </p>
              ))}
              {files.length === 0 && (
                <p className="text-gray-6000 dark:text-light-gray">
                  {t('none')}
                </p>
              )}
            </div>
          </>
        )}
        {activeTab === 'remote' && (
          <>
            <Dropdown
              border="border"
              options={urlOptions}
              selectedValue={urlType}
              onSelect={(value: { label: string; value: string }) =>
                setUrlType(value)
              }
              size="w-full"
              rounded="3xl"
            />
            {urlType.label !== 'Reddit' && urlType.label !== 'GitHub' ? (
              <>
                <Input
                  placeholder={`Enter ${t('modals.uploadDoc.name')}`}
                  type="text"
                  value={urlName}
                  onChange={(e) => setUrlName(e.target.value)}
                  borderVariant="thin"
                ></Input>
                <div className="relative bottom-12 left-2 mt-[-20px]">
                  <span className="bg-white px-2 text-xs text-gray-4000 dark:bg-outer-space dark:text-silver">
                    {t('modals.uploadDoc.name')}
                  </span>
                </div>
                <Input
                  placeholder={t('modals.uploadDoc.urlLink')}
                  type="text"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  borderVariant="thin"
                ></Input>
                <div className="relative bottom-12 left-2 mt-[-20px]">
                  <span className="bg-white px-2 text-xs text-gray-4000 dark:bg-outer-space dark:text-silver">
                    {t('modals.uploadDoc.link')}
                  </span>
                </div>
              </>
            ) : urlType.label === 'GitHub' ? ( // P3f93
              <>
                <Input
                  placeholder={`Enter ${t('modals.uploadDoc.name')}`}
                  type="text"
                  value={urlName}
                  onChange={(e) => setUrlName(e.target.value)}
                  borderVariant="thin"
                ></Input>
                <div className="relative bottom-12 left-2 mt-[-20px]">
                  <span className="bg-white px-2 text-xs text-gray-4000 dark:bg-outer-space dark:text-silver">
                    {t('modals.uploadDoc.name')}
                  </span>
                </div>
                <Input
                  placeholder={t('modals.uploadDoc.repoUrl')}
                  type="text"
                  value={repoUrl}
                  onChange={(e) => setRepoUrl(e.target.value)}
                  borderVariant="thin"
                ></Input>
                <div className="relative bottom-12 left-2 mt-[-20px]">
                  <span className="bg-white px-2 text-xs text-gray-4000 dark:bg-outer-space dark:text-silver">
                    {t('modals.uploadDoc.repoUrl')}
                  </span>
                </div>
              </>
            ) : (
              <div className="flex flex-col gap-1 mt-2">
                <div>
                  <Input
                    placeholder="Enter client ID"
                    type="text"
                    name="client_id"
                    value={redditData.client_id}
                    onChange={handleChange}
                    borderVariant="thin"
                  ></Input>
                  <div className="relative bottom-[52px] left-2">
                    <span className="bg-white px-2 text-xs text-gray-4000 dark:bg-outer-space dark:text-silver">
                      {t('modals.uploadDoc.reddit.id')}
                    </span>
                  </div>
                </div>
                <div>
                  <Input
                    placeholder="Enter client secret"
                    type="text"
                    name="client_secret"
                    value={redditData.client_secret}
                    onChange={handleChange}
                    borderVariant="thin"
                  ></Input>
                  <div className="relative bottom-[52px] left-2">
                    <span className="bg-white px-2 text-xs text-gray-4000 dark:bg-outer-space dark:text-silver">
                      {t('modals.uploadDoc.reddit.secret')}
                    </span>
                  </div>
                </div>
                <div>
                  <Input
                    placeholder="Enter user agent"
                    type="text"
                    name="user_agent"
                    value={redditData.user_agent}
                    onChange={handleChange}
                    borderVariant="thin"
                  ></Input>
                  <div className="relative bottom-[52px] left-2">
                    <span className="bg-white px-2 text-xs text-gray-4000 dark:bg-outer-space dark:text-silver">
                      {t('modals.uploadDoc.reddit.agent')}
                    </span>
                  </div>
                </div>
                <div>
                  <Input
                    placeholder="Enter search queries"
                    type="text"
                    name="search_queries"
                    value={redditData.search_queries}
                    onChange={handleChange}
                    borderVariant="thin"
                  ></Input>
                  <div className="relative bottom-[52px] left-2">
                    <span className="bg-white px-2 text-xs text-gray-4000 dark:bg-outer-space dark:text-silver">
                      {t('modals.uploadDoc.reddit.searchQueries')}
                    </span>
                  </div>
                </div>
                <div>
                  <Input
                    placeholder="Enter number of posts"
                    type="number"
                    name="number_posts"
                    value={redditData.number_posts}
                    onChange={handleChange}
                    borderVariant="thin"
                  ></Input>
                  <div className="relative bottom-[52px] left-2">
                    <span className="bg-white px-2 text-xs text-gray-4000 dark:bg-outer-space dark:text-silver">
                      {t('modals.uploadDoc.reddit.numberOfPosts')}
                    </span>
                  </div>
                </div>
              </div>
            )}
          </>
        )}
        {activeTab && (
          <div className="flex w-full justify-between flex-row-reverse">
            {activeTab === 'file' ? (
              <button
                onClick={uploadFile}
                className={`ml-2 cursor-pointer rounded-3xl bg-purple-30 text-sm text-white ${
                  files.length > 0 && docName.trim().length > 0
                    ? 'hover:bg-[#6F3FD1]'
                    : 'bg-opacity-75 text-opacity-80'
                } py-2 px-6`}
                disabled={
                  (files.length === 0 || docName.trim().length === 0) &&
                  activeTab === 'file'
                }
              >
                {t('modals.uploadDoc.train')}
              </button>
            ) : (
              <button
                onClick={uploadRemote}
                className={`ml-2 cursor-pointer rounded-3xl bg-purple-30 py-2 px-6 text-sm text-white hover:bg-[#6F3FD1] ${
                  urlName.trim().length === 0 ||
                  url.trim().length === 0 ||
                  (urlType.label === 'Reddit' &&
                    (redditData.client_id.length === 0 ||
                      redditData.client_secret.length === 0 ||
                      redditData.user_agent.length === 0 ||
                      redditData.search_queries.length === 0 ||
                      redditData.number_posts === 0)) ||
                  (urlType.label === 'GitHub' && repoUrl.trim().length === 0)
                    ? 'bg-opacity-80 text-opacity-80'
                    : ''
                }`}
                disabled={
                  urlName.trim().length === 0 ||
                  url.trim().length === 0 ||
                  (urlType.label === 'Reddit' &&
                    (redditData.client_id.length === 0 ||
                      redditData.client_secret.length === 0 ||
                      redditData.user_agent.length === 0 ||
                      redditData.search_queries.length === 0 ||
                      redditData.number_posts === 0)) ||
                  (urlType.label === 'GitHub' && repoUrl.trim().length === 0)
                }
              >
                {t('modals.uploadDoc.train')}
              </button>
            )}
            <button
              onClick={() => {
                setDocName('');
                setfiles([]);
                setActiveTab(null);
              }}
              className="cursor-pointer rounded-3xl px-5 py-2 text-sm font-medium hover:bg-gray-100 dark:bg-transparent dark:text-light-gray dark:hover:bg-[#767183]/50 flex items-center gap-1"
            >
              <img
                src={ArrowLeft}
                className="w-[10px] h-[10px] dark:filter dark:invert"
              />
              {t('modals.uploadDoc.back')}
            </button>
          </div>
        )}
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
