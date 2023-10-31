import React from 'react';
import { useCallback, useEffect, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { useDispatch } from 'react-redux';
import { ActiveState } from '../models/misc';
import { getDocs } from '../preferences/preferenceApi';
import { setSourceDocs } from '../preferences/preferenceSlice';

export default function Upload({
  modalState,
  setModalState,
}: {
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
}) {
  const [docName, setDocName] = useState('');
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
        <p className="text-xl text-jet">Upload New Documentation</p>
        <p className="mb-3 text-xs text-gray-4000">
          Please upload .pdf, .txt, .rst, .docx, .md, .zip limited to 25mb
        </p>
        <input
          type="text"
          className="h-10 w-[60%] rounded-md border-2 border-gray-5000 px-3 outline-none"
          value={docName}
          onChange={(e) => setDocName(e.target.value)}
        ></input>
        <div className="relative bottom-12 left-2 mt-[-18.39px]">
          <span className="bg-white px-2 text-xs text-gray-4000">Name</span>
        </div>
        <div {...getRootProps()}>
          <span className="rounded-3xl border border-purple-30 px-4 py-2 font-medium text-purple-30 hover:cursor-pointer">
            <input type="button" {...getInputProps()} />
            Choose Files
          </span>
        </div>
        <div className="mt-9">
          <p className="mb-5 font-medium text-eerie-black">Uploaded Files</p>
          {files.map((file) => (
            <p key={file.name} className="text-gray-6000">
              {file.name}
            </p>
          ))}
          {files.length === 0 && <p className="text-gray-6000">None</p>}
        </div>
        <div className="flex flex-row-reverse">
          <button
            onClick={uploadFile}
            className={`ml-6 rounded-3xl bg-purple-30 text-white ${
              files.length > 0 ? '' : 'bg-opacity-75 text-opacity-80'
            } py-2 px-6`}
            disabled={files.length === 0} // Disable the button if no file is selected
          >
            Train
          </button>
          <button
            onClick={() => {
              setDocName('');
              setfiles([]);
              setModalState('INACTIVE');
            }}
            className="font-medium"
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
      <article className="mx-auto mt-24 flex w-[90vw] max-w-lg  flex-col gap-4 rounded-lg bg-white p-6 shadow-lg">
        {view}
      </article>
    </article>
  );
}
// TODO: sanitize all inputs
