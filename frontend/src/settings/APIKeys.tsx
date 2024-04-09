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
  const createAPIKey = (payload: { name: string; source: string }) => {
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
        setCreateModal(false); //close the create key modal
        setNewKey(data.key);
        setSaveKeyModal(true); // render the newly created key
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
            className="rounded-full bg-purple-30 px-4 py-3 text-sm text-white hover:bg-[#7E66B1]"
          >
            Create New
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
  const docs = useSelector(selectSourceDocs);
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
      <div className="relative w-11/12 rounded-lg bg-white p-5 dark:bg-outer-space sm:w-[512px]">
        <button className="absolute top-2 right-2 m-2 w-4" onClick={close}>
          <img className="filter dark:invert" src={Exit} />
        </button>
        <span className="mb-4 text-xl font-bold text-jet dark:text-bright-gray">
          Create New API Key
        </span>
        <div className="relative my-4">
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
            placeholder="Select the source doc"
            selectedValue={sourcePath}
            onSelect={(selection: { label: string; value: string }) =>
              setSourcePath(selection)
            }
            options={extractDocPaths()}
          />
        </div>
        <button
          disabled={sourcePath === null || APIKeyName.length === 0}
          onClick={() =>
            sourcePath &&
            createAPIKey({ name: APIKeyName, source: sourcePath.value })
          }
          className="float-right my-4 rounded-full bg-purple-30 px-4 py-3 text-white disabled:opacity-50"
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
      <div className="relative w-11/12 rounded-md bg-white p-5 dark:bg-outer-space dark:text-bright-gray sm:w-[512px]">
        <button className="absolute top-4 right-4 w-4" onClick={close}>
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
            className="my-1 h-10 w-20 rounded-full border border-purple-30 p-2 text-sm text-purple-30 dark:border-purple-500 dark:text-purple-500"
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
