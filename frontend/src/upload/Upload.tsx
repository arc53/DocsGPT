import React from 'react';
import { useCallback, useEffect, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { useDispatch } from 'react-redux';
import { ActiveState } from '../models/misc';
import { getDocs } from '../preferences/preferenceApi';
import Arrow2 from '../assets/dropdown-arrow.svg';
import { setSourceDocs } from '../preferences/preferenceSlice';
type urlOption = {
  label: string,
  value: string
} | null
function DropdownUrlType({
  options,
  selectedOption,
  onSelect,
}: {
  options: urlOption[];
  selectedOption: urlOption;
  onSelect: (value: urlOption) => void;
}) {
  const [isOpen, setIsOpen] = useState(false);
  return (
    <div className="relative w-full align-middle">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={`${isOpen ? 'rounded-t-2xl' : 'rounded-full'} flex w-full cursor-pointer justify-between border-2 border-silver dark:border-chinese-silver bg-white p-3 dark:bg-transparent`}
      >
        <span className={`overflow-hidden text-ellipsis dark:text-bright-gray ${!selectedOption && 'text-silver'}`}>
          {selectedOption ? selectedOption.label : 'From URL'}
        </span>
        <img
          src={Arrow2}
          alt="arrow"
          className={`transform ${isOpen ? 'rotate-180' : 'rotate-0'
            } h-3 w-3 transition-transform mt-1`}
        />
      </button>
      {isOpen && (
        <div className="absolute left-0 right-0 z-50 -mt-1 rounded-b-xl border-2 border-silver dark:border-chinese-silver bg-white dark:bg-dark-charcoal  shadow-lg">
          {options.map((option, index) => (
            <div
              key={index}
              className="flex cursor-pointer items-center justify-between hover:bg-gray-100 dark:hover:bg-purple-taupe dark:text-bright-gray text-sonic-silver hover:eerie-black "
            >
              <span
                onClick={() => {
                  onSelect(option);
                  setIsOpen(false);
                }}
                className="ml-2 flex-1 overflow-hidden overflow-ellipsis whitespace-nowrap px-1 py-3"
              >
                {option?.label}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
export default function Upload({
  modalState,
  setModalState,
}: {
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
}) {
  const [docName, setDocName] = useState('');
  const [urlName, setUrlName] = useState('')
  const [url, setUrl] = useState('')
  const urlOptions: urlOption[] = [
    { label: 'Github', value: 'github' },
    { label: 'Sitemap', value: 'Sitemap' },
    { label: 'Link', value: 'link' }]
  const [urlType, setUrlType] = useState<urlOption>(null)
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
          className={`rounded-3xl bg-purple-30 px-4 py-2 text-sm font-medium text-white ${isCancellable ? '' : 'hidden'
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

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    multiple: false,
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
  let view;
  if (progress?.type === 'UPLOAD') {
    view = <UploadProgress></UploadProgress>;
  } else if (progress?.type === 'TRAINIING') {
    view = <TrainingProgress></TrainingProgress>;
  } else {
    view = (
      <>
        <p className="text-xl text-jet dark:text-bright-gray">Upload New Documentation</p>
        <div >
          <button
            onClick={() => setActiveTab('file')}
            className={`${activeTab === 'file' ? 'bg-soap text-purple-30 dark:bg-independence dark:text-purple-400' : 'text-sonic-silver  hover:text-purple-30'} text-sm font-semibold mr-4 px-[20px] py-[5px] rounded-full`}>
            From File
          </button>
          <button
            onClick={() => setActiveTab('remote')}
            className={`${activeTab === 'remote' ? 'bg-soap text-purple-30 dark:bg-independence dark:text-purple-400' : 'text-sonic-silver  hover:text-purple-30'} text-sm font-semibold mr-4 px-[20px] py-[5px] rounded-full`}>
            Remote
          </button>
        </div>
        {
          activeTab === 'file' && (
            <>
              <input
                type="text"
                className="h-10 w-full rounded-full border-2 border-gray-5000 dark:text-silver dark:bg-transparent px-3 outline-none"
                value={docName}
                onChange={(e) => setDocName(e.target.value)}
              ></input>
              <div className="relative bottom-12 left-2 mt-[-18.39px]">
                <span className="bg-white px-2 text-xs text-gray-4000 dark:text-silver dark:bg-outer-space">Name</span>
              </div>
              <div {...getRootProps()}>
                <span className="rounded-3xl border border-purple-30 dark:bg-purple-taupe px-4 py-2 font-medium text-purple-30 dark:text-silver hover:cursor-pointer">
                  <input type="button" {...getInputProps()} />
                  Choose Files
                </span>
              </div>
              <p className="mb-0 italic text-xs text-gray-4000">
                Please upload .pdf, .txt, .rst, .docx, .md, .zip limited to 25mb
              </p>
              <div className="mt-0">
                <p className="mb-[14px] font-medium text-eerie-black dark:text-light-gray">Uploaded Files</p>
                {files.map((file) => (
                  <p key={file.name} className="text-gray-6000">
                    {file.name}
                  </p>
                ))}
                {files.length === 0 && <p className="text-gray-6000 dark:text-light-gray">None</p>}
              </div>
            </>
          )
        }
        {
          activeTab === 'remote' && (
            <>
              <DropdownUrlType onSelect={(value: urlOption) => setUrlType(value)} selectedOption={urlType} options={urlOptions} />
              <input
                placeholder='Enter name'
                type="text"
                className="h-10 w-full rounded-full border-2 border-silver dark:text-silver dark:bg-transparent px-3 outline-none"
                value={urlName}
                onChange={(e) => setUrlName(e.target.value)}
              ></input>
              <div className="relative bottom-12 left-2 mt-[-18.39px]">
                <span className="bg-white px-2 text-xs text-silver dark:text-silver dark:bg-outer-space">Name</span>
              </div>
              <input
                placeholder='URL Link'
                type="text"
                className="h-10 w-full rounded-full border-2 border-silver dark:text-silver dark:bg-transparent px-3 outline-none"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
              ></input>
              <div className="relative bottom-12 left-2 mt-[-18.39px]">
                <span className="bg-white px-2 text-xs text-silver dark:text-silver dark:bg-outer-space">Link</span>
              </div>
            </>
          )
        }
        <div className="flex flex-row-reverse">
          <button
            onClick={uploadFile}
            className={`ml-6 rounded-3xl bg-purple-30 text-white cursor-pointer ${files.length > 0 && docName.trim().length > 0
              ? ''
              : 'bg-opacity-75 text-opacity-80'
              } py-2 px-6`}
            disabled={files.length === 0 || docName.trim().length === 0} // Disable the button if no file is selected or docName is empty
          >
            Train
          </button>
          <button
            onClick={() => {
              setDocName('');
              setfiles([]);
              setModalState('INACTIVE');
            }}
            className="font-medium dark:text-light-gray cursor-pointer"
          >
            Cancel
          </button>
        </div>
      </>
    );
  }

  return (
    <article
      className={`${modalState === 'ACTIVE' ? 'visible' : 'hidden'
        } absolute z-30  h-screen w-screen  bg-gray-alpha`}
    >
      <article className="mx-auto mt-24 flex w-[90vw] max-w-lg  flex-col gap-4 rounded-lg bg-white dark:bg-outer-space p-6 shadow-lg">
        {view}
      </article>
    </article>
  );
}
// TODO: sanitize all inputs
