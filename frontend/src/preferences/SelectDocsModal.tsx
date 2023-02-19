import { useEffect, useState } from 'react';
import { useDispatch } from 'react-redux';
import { ActiveState, Doc } from '../models/misc';
import { setSelectedDocs, selectSelectedDocs } from './preferenceSlice';
import { getDocs } from '../api/docs';

export default function APIKeyModal({
  modalState,
  setModalState,
  isCancellable = true,
}: {
  modalState: ActiveState;
  setModalState: (val: ActiveState) => void;
  isCancellable?: boolean;
}) {
  const dispatch = useDispatch();
  const [isError, setIsError] = useState(false);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [localSelectedDocs, setLocalSelectedDocs] = useState<Doc | null>(null);
  const [isDocsListOpen, setIsDocsListOpen] = useState(false);

  function handleSubmit() {
    if (!localSelectedDocs) {
      setIsError(true);
    } else {
      dispatch(setSelectedDocs(localSelectedDocs));
      setModalState('INACTIVE');
      setLocalSelectedDocs(null);
      setIsError(false);
    }
  }

  function handleCancel() {
    setSelectedDocs(null);
    setIsError(false);
    setModalState('INACTIVE');
  }

  useEffect(() => {
    async function requestDocs() {
      const data = await getDocs();
      setDocs(data);
    }

    requestDocs();
  }, []);

  return (
    <div
      className={`${
        modalState === 'ACTIVE' ? 'visible' : 'hidden'
      } absolute z-30  h-screen w-screen  bg-gray-alpha`}
    >
      <article className="mx-auto mt-24 flex w-[90vw] max-w-lg  flex-col gap-4 rounded-lg bg-white p-6 shadow-lg">
        <p className="text-xl text-jet">Select Source Documentation</p>
        <p className="text-lg leading-5 text-gray-500">
          Please select the library of documentation that you would like to use
          with our app.
        </p>
        <div className="relative">
          <div
            className="h-10 w-full cursor-pointer border-b-2"
            onClick={() => setIsDocsListOpen(!isDocsListOpen)}
          >
            {!localSelectedDocs ? (
              <p className="py-3 text-gray-500">Select</p>
            ) : (
              <p className="py-3">
                {localSelectedDocs.name} {localSelectedDocs.version}
              </p>
            )}
          </div>
          {isDocsListOpen && (
            <div className="absolute top-10 left-0 h-52 w-full overflow-y-scroll bg-white">
              {docs.map((doc, index) => {
                if (doc.model) {
                  return (
                    <div
                      key={index}
                      onClick={() => {
                        setLocalSelectedDocs(doc);
                        setIsDocsListOpen(false);
                      }}
                      className="h-10 w-full cursor-pointer border-x-2 border-b-2 hover:bg-gray-100"
                    >
                      <p className="ml-5 py-3">
                        {doc.name} {doc.version}
                      </p>
                    </div>
                  );
                }
              })}
            </div>
          )}
        </div>
        <div className="flex flex-row-reverse">
          {isCancellable && (
            <button
              onClick={() => handleCancel()}
              className="ml-5 h-10 w-20 rounded-lg border border-violet-700 bg-white text-violet-800 transition-all hover:bg-violet-700 hover:text-white"
            >
              Cancel
            </button>
          )}
          <button
            onClick={() => {
              handleSubmit();
            }}
            className="ml-auto h-10 w-20 rounded-lg bg-violet-800 text-white transition-all hover:bg-violet-700"
          >
            Save
          </button>{' '}
          {isError && (
            <p className="mr-auto text-sm text-red-500">
              Please select source documentation.
            </p>
          )}
        </div>
      </article>
    </div>
  );
}
