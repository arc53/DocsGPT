import { useState } from 'react';

export default function APIKeyModal({
  isApiModalOpen,
  setIsApiModalOpen,
  apiKey,
  setApiKey,
}: {
  isApiModalOpen: boolean;
  setIsApiModalOpen: React.Dispatch<React.SetStateAction<boolean>>;
  apiKey: string;
  setApiKey: React.Dispatch<React.SetStateAction<string>>;
}) {
  //TODO - Add form validation
  //TODO - Connect to backend
  //TODO - Add link to OpenAI API Key page

  const [formError, setFormError] = useState(false);

  const handleResetKey = () => {
    if (!apiKey) {
      setFormError(true);
    } else {
      setFormError(false);
      setIsApiModalOpen(false);
    }
  };

  return (
    <div
      className={`${
        isApiModalOpen ? 'visible' : 'hidden'
      } absolute z-30  h-screen w-screen  bg-gray-alpha`}
    >
      <article className="mx-auto mt-24 flex w-128 flex-col gap-4 rounded-lg bg-white p-6 shadow-lg">
        <p className="text-xl text-jet">OpenAI API Key</p>
        <p className="text-lg leading-5 text-gray-500">
          Before you can start using DocsGPT we need you to provide an API key
          for llm. Currently, we support only OpenAI but soon many more. You can
          find it here.
        </p>
        <input
          type="text"
          className="h-10 w-full border-b-2 border-jet focus:outline-none"
          value={apiKey}
          maxLength={100}
          placeholder="API Key"
          onChange={(e) => setApiKey(e.target.value)}
        />
        <div className="flex justify-between">
          {formError && (
            <p className="text-sm text-red-500">Please enter a valid API key</p>
          )}
          <button
            onClick={handleResetKey}
            className="ml-auto h-10 w-20 rounded-lg bg-violet-800 text-white transition-all hover:bg-violet-700"
          >
            Save
          </button>
        </div>
      </article>
    </div>
  );
}
