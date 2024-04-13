import React from 'react';
import { useSelector } from 'react-redux';
import Dropdown from '../components/Dropdown';
import {
  Doc,
  CreateAPIKeyModalProps,
  SaveAPIKeyModalProps,
} from '../models/misc';
import { selectSourceDocs } from '../preferences/preferenceSlice';
import Exit from '../assets/exit.svg';
import Trash from '../assets/trash.svg';

const apiHost = import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';
const embeddingsName =
  import.meta.env.VITE_EMBEDDINGS_NAME ||
  'huggingface_sentence-transformers/all-mpnet-base-v2';

const APIKeys: React.FC = () => {
  const [isCreateModalOpen, setCreateModal] = React.useState(false);
  const [isSaveKeyModalOpen, setSaveKeyModal] = React.useState(false);
  const [newKey, setNewKey] = React.useState('');
  const [apiKeys, setApiKeys] = React.useState<
    { name: string; key: string; source: string; id: string }[]
  >([]);
  const handleDeleteKey = (id: string) => {
    fetch(`${apiHost}/api/delete_api_key`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ id }),
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error('Failed to delete API Key');
        }
        return response.json();
      })
      .then((data) => {
        data.status === 'ok' &&
          setApiKeys((previous) => previous.filter((elem) => elem.id !== id));
      })
      .catch((error) => {
        console.error(error);
      });
  };
  React.useEffect(() => {
    fetchAPIKeys();
  }, []);
  const fetchAPIKeys = async () => {
    try {
      const response = await fetch(`${apiHost}/api/get_api_keys`);
      if (!response.ok) {
        throw new Error('Failed to fetch API Keys');
      }
      const apiKeys = await response.json();
      setApiKeys(apiKeys);
    } catch (error) {
      console.log(error);
    }
  };
  const createAPIKey = (payload: {
    name: string;
    source: string;
    prompt_id: string;
    chunks: string;
  }) => {
    fetch(`${apiHost}/api/create_api_key`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error('Failed to create API Key');
        }
        return response.json();
      })
      .then((data) => {
        setApiKeys([...apiKeys, data]);
        setCreateModal(false);
        setNewKey(data.key);
        setSaveKeyModal(true);
        fetchAPIKeys();
      })
      .catch((error) => {
        console.error(error);
      });
  };
  return (
    <div className="mt-8">
      <div className="flex w-full flex-col lg:w-max">
        <div className="flex justify-end">
          <button
            onClick={() => setCreateModal(true)}
            className="rounded-full bg-purple-30 px-4 py-3 text-sm text-white hover:opacity-90"
          >
            Create new
          </button>
        </div>
        {isCreateModalOpen && (
          <CreateAPIKeyModal
            close={() => setCreateModal(false)}
            createAPIKey={createAPIKey}
          />
        )}
        {isSaveKeyModalOpen && (
          <SaveAPIKeyModal
            apiKey={newKey}
            close={() => setSaveKeyModal(false)}
          />
        )}
        <div className="mt-[27px] w-full">
          <div className="w-full overflow-x-auto">
            <table className="block w-max table-auto content-center justify-center rounded-xl border text-center dark:border-chinese-silver dark:text-bright-gray">
              <thead>
                <tr>
                  <th className="border-r p-4 md:w-[244px]">Name</th>
                  <th className="w-[244px] border-r px-4 py-2">
                    Source document
                  </th>
                  <th className="w-[244px] border-r px-4 py-2">API Key</th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {apiKeys?.map((element, index) => (
                  <tr key={index}>
                    <td className="border-r border-t p-4">{element.name}</td>
                    <td className="border-r border-t p-4">{element.source}</td>
                    <td className="border-r border-t p-4">{element.key}</td>
                    <td className="border-t p-4">
                      <img
                        src={Trash}
                        alt="Delete"
                        className="h-4 w-4 cursor-pointer hover:opacity-50"
                        id={`img-${index}`}
                        onClick={() => handleDeleteKey(element.id)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
};

const CreateAPIKeyModal: React.FC<CreateAPIKeyModalProps> = ({
  close,
  createAPIKey,
}) => {
  const [APIKeyName, setAPIKeyName] = React.useState<string>('');
  const [sourcePath, setSourcePath] = React.useState<{
    label: string;
    value: string;
  } | null>(null);

  const chunkOptions = ['0', '2', '4', '6', '8', '10'];
  const [chunk, setChunk] = React.useState<string>('2');
  const [activePrompts, setActivePrompts] = React.useState<
    { name: string; id: string; type: string }[]
  >([]);
  const [prompt, setPrompt] = React.useState<{
    name: string;
    id: string;
    type: string;
  } | null>(null);
  const docs = useSelector(selectSourceDocs);
  React.useEffect(() => {
    const fetchPrompts = async () => {
      try {
        const response = await fetch(`${apiHost}/api/get_prompts`);
        if (!response.ok) {
          throw new Error('Failed to fetch prompts');
        }
        const promptsData = await response.json();
        setActivePrompts(promptsData);
      } catch (error) {
        console.error(error);
      }
    };
    fetchPrompts();
  }, []);
  const extractDocPaths = () =>
    docs
      ? docs
          .filter((doc) => doc.model === embeddingsName)
          .map((doc: Doc) => {
            let namePath = doc.name;
            if (doc.language === namePath) {
              namePath = '.project';
            }
            let docPath = 'default';
            if (doc.location === 'local') {
              docPath = 'local' + '/' + doc.name + '/';
            } else if (doc.location === 'remote') {
              docPath =
                doc.language +
                '/' +
                namePath +
                '/' +
                doc.version +
                '/' +
                doc.model +
                '/';
            }
            return {
              label: doc.name,
              value: docPath,
            };
          })
      : [];

  return (
    <div className="fixed top-0 left-0 z-30 flex h-screen w-screen items-center justify-center bg-gray-alpha bg-opacity-50">
      <div className="relative w-11/12 rounded-2xl bg-white p-10 dark:bg-outer-space sm:w-[512px]">
        <button className="absolute top-3 right-4 m-2 w-3" onClick={close}>
          <img className="filter dark:invert" src={Exit} />
        </button>
        <div className="mb-6">
          <span className="text-xl text-jet dark:text-bright-gray">
            Create New API Key
          </span>
        </div>
        <div className="relative mt-5 mb-4">
          <span className="absolute left-2 -top-2 bg-white px-2 text-xs text-gray-4000 dark:bg-outer-space dark:text-silver">
            API Key Name
          </span>
          <input
            type="text"
            className="h-10 w-full rounded-md border-2 border-silver px-3 outline-none dark:bg-transparent dark:text-silver"
            value={APIKeyName}
            onChange={(e) => setAPIKeyName(e.target.value)}
          />
        </div>
        <div className="my-4">
          <Dropdown
            placeholder="Source document"
            selectedValue={sourcePath}
            onSelect={(selection: { label: string; value: string }) =>
              setSourcePath(selection)
            }
            options={extractDocPaths()}
            size="w-full"
            rounded="xl"
          />
        </div>
        <div className="my-4">
          <Dropdown
            options={activePrompts}
            selectedValue={prompt ? prompt.name : null}
            placeholder="Select active prompt"
            onSelect={(value: { name: string; id: string; type: string }) =>
              setPrompt(value)
            }
            size="w-full"
          />
        </div>
        <div className="my-4">
          <p className="mb-2 ml-2 font-bold text-jet dark:text-bright-gray">
            Chunks processed per query
          </p>
          <Dropdown
            options={chunkOptions}
            selectedValue={chunk}
            onSelect={(value: string) => setChunk(value)}
            size="w-full"
          />
        </div>
        <button
          disabled={!sourcePath || APIKeyName.length === 0 || !prompt}
          onClick={() =>
            sourcePath &&
            prompt &&
            createAPIKey({
              name: APIKeyName,
              source: sourcePath.value,
              prompt_id: prompt.id,
              chunks: chunk,
            })
          }
          className="float-right mt-4 rounded-full bg-purple-30 px-4 py-3 text-white disabled:opacity-50"
        >
          Create
        </button>
      </div>
    </div>
  );
};

const SaveAPIKeyModal: React.FC<SaveAPIKeyModalProps> = ({ apiKey, close }) => {
  const [isCopied, setIsCopied] = React.useState(false);
  const handleCopyKey = () => {
    navigator.clipboard.writeText(apiKey);
    setIsCopied(true);
  };
  return (
    <div className="fixed top-0 left-0 z-30 flex h-screen w-screen items-center justify-center bg-gray-alpha bg-opacity-50">
      <div className="relative w-11/12 rounded-3xl bg-white px-6 py-8 dark:bg-outer-space dark:text-bright-gray sm:w-[512px]">
        <button className="absolute top-3 right-4 m-2 w-3" onClick={close}>
          <img className="filter dark:invert" src={Exit} />
        </button>
        <h1 className="my-0 text-xl font-medium">Please save your Key</h1>
        <h3 className="text-sm font-normal text-outer-space">
          This is the only time your key will be shown.
        </h3>
        <div className="flex justify-between py-2">
          <div>
            <h2 className="text-base font-semibold">API Key</h2>
            <span className="text-sm font-normal leading-7 ">{apiKey}</span>
          </div>
          <button
            className="my-1 h-10 w-20 rounded-full border border-purple-30 p-2 text-sm text-purple-30 hover:bg-purple-30 hover:text-white dark:border-purple-500 dark:text-purple-500"
            onClick={handleCopyKey}
          >
            {isCopied ? 'Copied' : 'Copy'}
          </button>
        </div>
        <button
          onClick={close}
          className="rounded-full bg-philippine-yellow px-4 py-3 font-medium text-black hover:bg-[#E6B91A]"
        >
          I saved the Key
        </button>
      </div>
    </div>
  );
};

export default APIKeys;
