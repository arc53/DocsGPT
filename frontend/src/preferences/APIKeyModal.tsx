import { useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { ActiveState } from '../models/misc';
import { selectApiKey, setApiKey } from './preferenceSlice';
import { useOutsideAlerter } from './../hooks';

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
  const apiKey = useSelector(selectApiKey);
  const [key, setKey] = useState(apiKey);
  const [isError, setIsError] = useState(false);
  const modalRef = useRef(null);

  useOutsideAlerter(
    modalRef,
    () => {
      if (
        window.matchMedia('(max-width: 768px)').matches &&
        modalState === 'ACTIVE'
      ) {
        setModalState('INACTIVE');
      }
    },
    [modalState],
  );

  function handleSubmit() {
    if (key.length <= 1) {
      setIsError(true);
    } else {
      dispatch(setApiKey(key));
      setModalState('INACTIVE');
      setIsError(false);
    }
  }

  function handleCancel() {
    setKey(apiKey);
    setIsError(false);
    setModalState('INACTIVE');
  }

  return (
    <div
      className={`${
        modalState === 'ACTIVE' ? 'visible' : 'hidden'
      } absolute z-30  h-screen w-screen  bg-gray-alpha`}
    >
      <article
        ref={modalRef}
        className="mx-auto mt-24 flex w-[90vw] max-w-lg  flex-col gap-4 rounded-lg bg-white p-6 shadow-lg"
      >
        <p className="text-xl text-jet">OpenAI API Key</p>
        <p className="text-md leading-6 text-gray-500">
          Before you can start using DocsGPT we need you to provide an API key
          for llm. Currently, we support only OpenAI but soon many more. You can
          find it here.
        </p>
        <input
          type="text"
          className="h-10 w-full border-b-2 border-jet focus:outline-none"
          value={key}
          maxLength={100}
          placeholder="API Key"
          onChange={(e) => setKey(e.target.value)}
        />
        <div className="flex flex-row-reverse">
          <div>
            <button
              onClick={() => handleSubmit()}
              className="ml-auto h-10 w-20 rounded-lg bg-violet-800 text-white transition-all hover:bg-violet-700"
            >
              Save
            </button>
            {isCancellable && (
              <button
                onClick={() => handleCancel()}
                className="ml-5 h-10 w-20 rounded-lg border border-violet-700 bg-white text-violet-800 transition-all hover:bg-violet-700 hover:text-white"
              >
                Cancel
              </button>
            )}
          </div>
          {isError && (
            <p className="mr-auto text-sm text-red-500">
              Please enter a valid API key
            </p>
          )}
        </div>
      </article>
    </div>
  );
}
