import { useCallback, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { ActiveState } from '../models/misc';

export default function Upload({
  modalState,
  setModalState,
}: {
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
}) {
  const [docName, setDocName] = useState('');
  const [files, setfiles] = useState<File[]>([]);

  const onDrop = useCallback((acceptedFiles: File[]) => {
    setfiles(acceptedFiles);
    setDocName(acceptedFiles[0]?.name);
  }, []);

  const doNothing = () => undefined;

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    multiple: true,
    onDragEnter: doNothing,
    onDragOver: doNothing,
    onDragLeave: doNothing,
  });
  return (
    <article
      className={`${
        modalState === 'ACTIVE' ? 'visible' : 'hidden'
      } absolute z-30  h-screen w-screen  bg-gray-alpha`}
    >
      <article className="mx-auto mt-24 flex w-[90vw] max-w-lg  flex-col gap-4 rounded-lg bg-white p-6 shadow-lg">
        <p className="mb-7 text-xl text-jet">Upload New Documentation</p>
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
          <label className="rounded-md border border-blue-2000 px-4 py-2 font-medium text-blue-2000 hover:cursor-pointer">
            <input type="button" {...getInputProps()} />
            Choose Files
          </label>
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
          <button className="ml-6 rounded-md bg-blue-3000 py-2 px-6 text-white">
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
      </article>
    </article>
  );
}

// TODO: sanitize all inputs
