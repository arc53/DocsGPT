import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { useTranslation } from 'react-i18next';
import { useDispatch } from 'react-redux';

import userService from '../api/services/userService';
import Dropdown from '../components/Dropdown';
import Input from '../components/Input';
import { ActiveState } from '../models/misc';
import { getDocs } from '../preferences/preferenceApi';
import { setSelectedDocs, setSourceDocs } from '../preferences/preferenceSlice';

function Upload({
  modalState,
  setModalState,
}: {
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
}) {
  const [docName, setDocName] = useState('');
  const [urlName, setUrlName] = useState('');
  const [url, setUrl] = useState('');
  const [redditData, setRedditData] = useState({
    client_id: '',
    client_secret: '',
    user_agent: '',
    search_queries: [''],
    number_posts: 10,
  });
  const [activeTab, setActiveTab] = useState<string>('file');
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
  ];

  const [urlType, setUrlType] = useState<{ label: string; value: string }>({
    label: 'Link',
    value: 'url',
  });

  useEffect(() => {
    if (setTimeoutRef.current) {
      clearTimeout(setTimeoutRef.current);
    }
  }, []);

  function ProgressBar({ progressPercent }: { progressPercent: number }) {
    return (
      <div className="my-5 w-[50%]">
        <div
          className={`h-8 overflow-hidden rounded-xl border border-purple-30 text-xs text-bright-gray outline-none `}
        >
          <div
            className={`h-full border-none text-xl w-${
              progress || 0
            }%  flex items-center justify-center bg-purple-30 outline-none transition-all`}
            style={{ width: `${progressPercent || 0}%` }}
          >
            {progressPercent >= 5 && `${progressPercent}%`}
          </div>
        </div>
      </div>
    );
  }

  function Progress({
    title,
    isCancellable = false,
    isFailed = false,
  }: {
    title: string;
    isCancellable?: boolean;
    isFailed?: boolean;
  }) {
    return (
      <div className="mt-5 flex flex-col items-center gap-2 text-gray-2000 dark:text-bright-gray">
        <p className="text-gra text-xl tracking-[0.15px]">{title}...</p>
        <p className="text-sm">This may take several minutes</p>
        <p className={`ml-5 text-xl text-red-400 ${isFailed ? '' : 'hidden'}`}>
          Over the token limit, please consider uploading smaller document
        </p>
        {/* <p className="mt-10 text-2xl">{progress?.percentage || 0}%</p> */}
        <ProgressBar progressPercent={progress?.percentage as number} />
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
                        data?.find((d) => d.type?.toLowerCase() === 'local'),
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
                    dispatch(
                      setSelectedDocs(
                        data?.find((d) => d.type?.toLowerCase() === 'local'),
                      ),
                    );
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
      'text/csv': ['.csv'],
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
      <>
        <p className="text-xl text-jet dark:text-bright-gray">
          {t('modals.uploadDoc.label')}
        </p>
        <div>
          <button
            onClick={() => setActiveTab('file')}
            className={`${
              activeTab === 'file'
                ? 'bg-soap text-purple-30 dark:bg-independence dark:text-purple-400'
                : 'text-sonic-silver  hover:text-purple-30'
            } mr-4 rounded-full px-[20px] py-[5px] text-sm font-semibold`}
          >
            {t('modals.uploadDoc.file')}
          </button>
          <button
            onClick={() => setActiveTab('remote')}
            className={`${
              activeTab === 'remote'
                ? 'bg-soap text-purple-30 dark:bg-independence dark:text-purple-400'
                : 'text-sonic-silver  hover:text-purple-30'
            } mr-4 rounded-full px-[20px] py-[5px] text-sm font-semibold`}
          >
            {t('modals.uploadDoc.remote')}
          </button>
        </div>

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
            {urlType.label !== 'Reddit' ? (
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

        <div className="flex flex-row-reverse">
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
              className={`ml-2 cursor-pointer rounded-3xl bg-purple-30 py-2 px-6 text-sm text-white hover:bg-[#6F3FD1]`}
            >
              {t('modals.uploadDoc.train')}
            </button>
          )}
          <button
            onClick={() => {
              setDocName('');
              setfiles([]);
              setModalState('INACTIVE');
            }}
            className="cursor-pointer rounded-3xl px-5 py-2 text-sm font-medium hover:bg-gray-100 dark:bg-transparent dark:text-light-gray dark:hover:bg-[#767183]/50"
          >
            {t('modals.uploadDoc.cancel')}
          </button>
        </div>
      </>
    );
  }

  return (
    <article
      className={`${
        modalState === 'ACTIVE' ? 'visible' : 'hidden'
      } absolute z-30  h-screen w-screen  bg-gray-alpha`}
    >
      <article className="mx-auto mt-24 flex w-[90vw] max-w-lg  flex-col gap-4 rounded-lg bg-white p-6 shadow-lg dark:bg-outer-space">
        {view}
      </article>
    </article>
  );
}

export default Upload;
