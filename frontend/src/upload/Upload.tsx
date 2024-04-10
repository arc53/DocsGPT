import React from 'react';
import { useCallback, useEffect, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { useDispatch } from 'react-redux';
import { ActiveState } from '../models/misc';
import { getDocs } from '../preferences/preferenceApi';
import { setSourceDocs } from '../preferences/preferenceSlice';
import Dropdown from '../components/Dropdown';

export default function Upload({
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
  const [activeTab, setActiveTab] = useState<string>('file');
  const [files, setfiles] = useState<File[]>([]);
  const [progress, setProgress] = useState<{
    type: 'UPLOAD' | 'TRAINIING';
    percentage: number;
    taskId?: string;
    failed?: boolean;
  }>();

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
      <div className="mt-5 flex flex-col items-center gap-2">
        <p className="text-xl tracking-[0.15px]">{title}...</p>
        <p className="text-sm text-gray-2000">This may take several minutes</p>
        <p className={`ml-5 text-xl text-red-400 ${isFailed ? '' : 'hidden'}`}>
          Over the token limit, please consider uploading smaller document
        </p>
        <p className="mt-10 text-2xl">{progress?.percentage || 0}%</p>

        <div className="mb-10 w-[50%]">
          <div className="h-1 w-[100%] bg-purple-30"></div>
          <div
            className={`relative bottom-1 h-1 bg-purple-30 transition-all`}
            style={{ width: `${progress?.percentage || 0}%` }}
          ></div>
        </div>

        <button
          onClick={() => {
            setDocName('');
            setfiles([]);
            setProgress(undefined);
            setModalState('INACTIVE');
          }}
          className={`rounded-3xl bg-purple-30 px-4 py-2 text-sm font-medium text-white ${
            isCancellable ? '' : 'hidden'
          }`}
        >
          Finish
        </button>
      </div>
    );
  }

  function UploadProgress() {
    return <Progress title="Upload is in progress"></Progress>;
  }

  function TrainingProgress() {
    const dispatch = useDispatch();
    useEffect(() => {
      (progress?.percentage ?? 0) < 100 &&
        setTimeout(() => {
          const apiHost = import.meta.env.VITE_API_HOST;
          fetch(`${apiHost}/api/task_status?task_id=${progress?.taskId}`)
            .then((data) => data.json())
            .then((data) => {
              if (data.status == 'SUCCESS') {
                if (data.result.limited === true) {
                  getDocs().then((data) => dispatch(setSourceDocs(data)));
                  setProgress(
                    (progress) =>
                      progress && {
                        ...progress,
                        percentage: 100,
                        failed: true,
                      },
                  );
                } else {
                  getDocs().then((data) => dispatch(setSourceDocs(data)));
                  setProgress(
                    (progress) =>
                      progress && {
                        ...progress,
                        percentage: 100,
                        failed: false,
                      },
                  );
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
      setProgress({ type: 'TRAINIING', percentage: 0, taskId: task_id });
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
      setProgress({ type: 'TRAINIING', percentage: 0, taskId: task_id });
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
    },
  });
  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    if (name === 'search_queries' && value.length > 0) {
      setRedditData({
        ...redditData,
        [name]: value.split(',').map((item) => item.trim()),
      });
    } else
      setRedditData({
        ...redditData,
        [name]: value,
      });
  };
  let view;
  if (progress?.type === 'UPLOAD') {
    view = <UploadProgress></UploadProgress>;
  } else if (progress?.type === 'TRAINIING') {
    view = <TrainingProgress></TrainingProgress>;
  } else {
    view = (
      <>
        <p className="text-xl text-jet dark:text-bright-gray">
          Upload New Documentation
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
            From File
          </button>
          <button
            onClick={() => setActiveTab('remote')}
            className={`${
              activeTab === 'remote'
                ? 'bg-soap text-purple-30 dark:bg-independence dark:text-purple-400'
                : 'text-sonic-silver  hover:text-purple-30'
            } mr-4 rounded-full px-[20px] py-[5px] text-sm font-semibold`}
          >
            Remote
          </button>
        </div>
        {activeTab === 'file' && (
          <>
            <input
              type="text"
              className="h-10 w-full rounded-full border-2 border-gray-5000 px-3 outline-none dark:bg-transparent dark:text-silver"
              value={docName}
              onChange={(e) => setDocName(e.target.value)}
            ></input>
            <div className="relative bottom-12 left-2 mt-[-18.39px]">
              <span className="bg-white px-2 text-xs text-gray-4000 dark:bg-outer-space dark:text-silver">
                Name
              </span>
            </div>
            <div {...getRootProps()}>
              <span className="rounded-3xl border border-purple-30 px-4 py-2 font-medium text-purple-30 hover:cursor-pointer dark:bg-purple-taupe dark:text-silver">
                <input type="button" {...getInputProps()} />
                Choose Files
              </span>
            </div>
            <p className="mb-0 text-xs italic text-gray-4000">
              Please upload .pdf, .txt, .rst, .docx, .md, .zip limited to 25mb
            </p>
            <div className="mt-0">
              <p className="mb-[14px] font-medium text-eerie-black dark:text-light-gray">
                Uploaded Files
              </p>
              {files.map((file) => (
                <p key={file.name} className="text-gray-6000">
                  {file.name}
                </p>
              ))}
              {files.length === 0 && (
                <p className="text-gray-6000 dark:text-light-gray">None</p>
              )}
            </div>
          </>
        )}
        {activeTab === 'remote' && (
          <>
            <Dropdown
              options={urlOptions}
              selectedValue={urlType}
              onSelect={(value: { label: string; value: string }) =>
                setUrlType(value)
              }
              size="w-full"
              rounded="xl"
            />
            {urlType.label !== 'Reddit' ? (
              <>
                <input
                  placeholder="Enter name"
                  type="text"
                  className="h-10 w-full rounded-full border-2 border-silver px-3 outline-none dark:bg-transparent dark:text-silver"
                  value={urlName}
                  onChange={(e) => setUrlName(e.target.value)}
                ></input>
                <div className="relative bottom-12 left-2 mt-[-18.39px]">
                  <span className="bg-white px-2 text-xs text-silver dark:bg-outer-space dark:text-silver">
                    Name
                  </span>
                </div>
                <input
                  placeholder="URL Link"
                  type="text"
                  className="h-10 w-full rounded-full border-2 border-silver px-3 outline-none dark:bg-transparent dark:text-silver"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                ></input>
                <div className="relative bottom-12 left-2 mt-[-18.39px]">
                  <span className="bg-white px-2 text-xs text-silver dark:bg-outer-space dark:text-silver">
                    Link
                  </span>
                </div>
              </>
            ) : (
              <>
                <input
                  placeholder="Enter client ID"
                  type="text"
                  className="h-10 w-full rounded-full border-2 border-silver px-3 outline-none dark:bg-transparent dark:text-silver"
                  name="client_id"
                  value={redditData.client_id}
                  onChange={handleChange}
                ></input>
                <div className="relative bottom-12 left-2 mt-[-18.39px]">
                  <span className="bg-white px-2 text-xs text-silver dark:bg-outer-space dark:text-silver">
                    Client ID
                  </span>
                </div>
                <input
                  placeholder="Enter client secret"
                  type="text"
                  className="h-10 w-full rounded-full border-2 border-silver px-3 outline-none dark:bg-transparent dark:text-silver"
                  name="client_secret"
                  value={redditData.client_secret}
                  onChange={handleChange}
                ></input>
                <div className="relative bottom-12 left-2 mt-[-18.39px]">
                  <span className="bg-white px-2 text-xs text-silver dark:bg-outer-space dark:text-silver">
                    Client secret
                  </span>
                </div>
                <input
                  placeholder="Enter user agent"
                  type="text"
                  className="h-10 w-full rounded-full border-2 border-silver px-3 outline-none dark:bg-transparent dark:text-silver"
                  name="user_agent"
                  value={redditData.user_agent}
                  onChange={handleChange}
                ></input>
                <div className="relative bottom-12 left-2 mt-[-18.39px]">
                  <span className="bg-white px-2 text-xs text-silver dark:bg-outer-space dark:text-silver">
                    User agent
                  </span>
                </div>
                <input
                  placeholder="Enter search queries"
                  type="text"
                  className="h-10 w-full rounded-full border-2 border-silver px-3 outline-none dark:bg-transparent dark:text-silver"
                  name="search_queries"
                  value={redditData.search_queries}
                  onChange={handleChange}
                ></input>
                <div className="relative bottom-12 left-2 mt-[-18.39px]">
                  <span className="bg-white px-2 text-xs text-silver dark:bg-outer-space dark:text-silver">
                    Search queries
                  </span>
                </div>
                <input
                  placeholder="Enter number of posts"
                  type="number"
                  className="h-10 w-full rounded-full border-2 border-silver px-3 outline-none dark:bg-transparent dark:text-silver"
                  name="number_posts"
                  value={redditData.number_posts}
                  onChange={handleChange}
                ></input>
                <div className="relative bottom-12 left-2 mt-[-18.39px]">
                  <span className="bg-white px-2 text-xs text-silver dark:bg-outer-space dark:text-silver">
                    Number of posts
                  </span>
                </div>
              </>
            )}
          </>
        )}
        <div className="flex flex-row-reverse">
          <button
            onClick={activeTab === 'file' ? uploadFile : uploadRemote}
            className={`ml-6 cursor-pointer rounded-3xl bg-purple-30 text-white ${
              files.length > 0 && docName.trim().length > 0
                ? ''
                : 'bg-opacity-75 text-opacity-80'
            } py-2 px-6`}
            disabled={
              (files.length === 0 || docName.trim().length === 0) &&
              activeTab === 'file'
            } // Disable the button if no file is selected or docName is empty
          >
            Train
          </button>
          <button
            onClick={() => {
              setDocName('');
              setfiles([]);
              setModalState('INACTIVE');
            }}
            className="cursor-pointer font-medium dark:text-light-gray"
          >
            Cancel
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
// TODO: sanitize all inputs
