import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import Exit from '../assets/exit.svg';
import Dropdown from '../components/Dropdown';
import Input from '../components/Input';
import { CreateAPIKeyModalProps, Doc } from '../models/misc';
import { selectSourceDocs } from '../preferences/preferenceSlice';

const embeddingsName =
  import.meta.env.VITE_EMBEDDINGS_NAME ||
  'huggingface_sentence-transformers/all-mpnet-base-v2';

export default function CreateAPIKeyModal({
  close,
  createAPIKey,
}: CreateAPIKeyModalProps) {
  const { t } = useTranslation();
  const docs = useSelector(selectSourceDocs);

  const [APIKeyName, setAPIKeyName] = React.useState<string>('');
  const [sourcePath, setSourcePath] = React.useState<{
    label: string;
    value: string;
  } | null>(null);
  const [prompt, setPrompt] = React.useState<{
    name: string;
    id: string;
    type: string;
  } | null>(null);
  const [activePrompts, setActivePrompts] = React.useState<
    { name: string; id: string; type: string }[]
  >([]);
  const [chunk, setChunk] = React.useState<string>('2');
  const chunkOptions = ['0', '2', '4', '6', '8', '10'];

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

  React.useEffect(() => {
    const handleFetchPrompts = async () => {
      try {
        const response = await userService.getPrompts();
        if (!response.ok) {
          throw new Error('Failed to fetch prompts');
        }
        const promptsData = await response.json();
        setActivePrompts(promptsData);
      } catch (error) {
        console.error(error);
      }
    };
    handleFetchPrompts();
  }, []);
  return (
    <div className="fixed top-0 left-0 z-30 flex h-screen w-screen items-center justify-center bg-gray-alpha bg-opacity-50">
      <div className="relative w-11/12 rounded-2xl bg-white p-10 dark:bg-outer-space sm:w-[512px]">
        <button className="absolute top-3 right-4 m-2 w-3" onClick={close}>
          <img className="filter dark:invert" src={Exit} />
        </button>
        <div className="mb-6">
          <span className="text-xl text-jet dark:text-bright-gray">
            {t('modals.createAPIKey.label')}
          </span>
        </div>
        <div className="relative mt-5 mb-4">
          <span className="absolute left-2 -top-2 bg-white px-2 text-xs text-gray-4000 dark:bg-outer-space dark:text-silver">
            {t('modals.createAPIKey.apiKeyName')}
          </span>
          <Input
            type="text"
            className="rounded-md"
            value={APIKeyName}
            onChange={(e) => setAPIKeyName(e.target.value)}
          ></Input>
        </div>
        <div className="my-4">
          <Dropdown
            placeholder={t('modals.createAPIKey.sourceDoc')}
            selectedValue={sourcePath}
            onSelect={(selection: { label: string; value: string }) =>
              setSourcePath(selection)
            }
            options={extractDocPaths()}
            size="w-full"
            rounded="xl"
            border="border"
          />
        </div>
        <div className="my-4">
          <Dropdown
            options={activePrompts}
            selectedValue={prompt ? prompt.name : null}
            placeholder={t('modals.createAPIKey.prompt')}
            onSelect={(value: { name: string; id: string; type: string }) =>
              setPrompt(value)
            }
            size="w-full"
            border="border"
          />
        </div>
        <div className="my-4">
          <p className="mb-2 ml-2 font-semibold text-jet dark:text-bright-gray">
            {t('modals.createAPIKey.chunks')}
          </p>
          <Dropdown
            options={chunkOptions}
            selectedValue={chunk}
            onSelect={(value: string) => setChunk(value)}
            size="w-full"
            border="border"
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
          className="float-right mt-4 rounded-full bg-purple-30 px-5 py-2 text-sm text-white hover:bg-[#6F3FD1] disabled:opacity-50"
        >
          {t('modals.createAPIKey.create')}
        </button>
      </div>
    </div>
  );
}
