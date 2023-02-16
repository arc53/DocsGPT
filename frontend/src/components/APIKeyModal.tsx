import { useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  setApiKey,
  toggleApiKeyModal,
  selectIsApiKeyModalOpen,
} from '../store';

export default function APIKeyModal() {
  //TODO - Add form validation?
  //TODO - Connect to backend
  //TODO - Add link to OpenAI API Key page

  const dispatch = useDispatch();
  const isApiModalOpen = useSelector(selectIsApiKeyModalOpen);
  const [key, setKey] = useState('');
  const [formError, setFormError] = useState(false);

  function handleSubmit() {
    if (key.length < 1) {
      setFormError(true);
      return;
    }
    dispatch(setApiKey(key));
    dispatch(toggleApiKeyModal());
  }

  return (
    <div
      className={`${
        isApiModalOpen ? 'visible' : 'hidden'
      } absolute z-30  h-screen w-screen  bg-gray-alpha`}
    >
      <article className="mx-auto mt-24 flex w-[90vw] max-w-lg  flex-col gap-4 rounded-lg bg-white p-6 shadow-lg">
        <p className="text-xl text-jet">OpenAI API Key</p>
        <p className="text-lg leading-5 text-gray-500">
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
        <div className="flex justify-between">
          {formError && (
            <p className="text-sm text-red-500">Please enter a valid API key</p>
          )}
          <button
            onClick={() => handleSubmit()}
            className="ml-auto h-10 w-20 rounded-lg bg-violet-800 text-white transition-all hover:bg-violet-700"
          >
            Save
          </button>
        </div>
      </article>
    </div>
  );
}
