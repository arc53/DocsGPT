import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import Dropdown from '../components/Dropdown';
import Input from '../components/Input';
import { CreateAPIKeyModalProps, Doc } from '../models/misc';
import { selectSourceDocs, selectToken } from '../preferences/preferenceSlice';
import WrapperModal from './WrapperModal';

const embeddingsName =
  import.meta.env.VITE_EMBEDDINGS_NAME ||
  'huggingface_sentence-transformers/all-mpnet-base-v2';

export default function CreateAPIKeyModal({
  close,
  createAPIKey,
}: CreateAPIKeyModalProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const docs = useSelector(selectSourceDocs);

  const [APIKeyName, setAPIKeyName] = React.useState<string>('');
  const [sourcePath, setSourcePath] = React.useState<{
    name: string;
    id: string;
    type: string;
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
            if ('id' in doc) {
              return {
                name: doc.name,
                id: doc.id as string,
                type: 'local',
              };
            }
            return {
              name: doc.name,
              id: doc.id ?? 'default',
              type: doc.type ?? 'default',
            };
          })
      : [];

  React.useEffect(() => {
    const handleFetchPrompts = async () => {
      try {
        const response = await userService.getPrompts(token);
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
    <WrapperModal close={close} className="p-4">
      <div className="mb-6">
        <span className="text-xl text-jet dark:text-bright-gray">
          {t('modals.createAPIKey.label')}
        </span>
      </div>
      <div className="relative mb-4 mt-5">
        <Input
          type="text"
          className="rounded-md"
          value={APIKeyName}
          placeholder={t('modals.createAPIKey.apiKeyName')}
          onChange={(e) => setAPIKeyName(e.target.value)}
          borderVariant="thin"
          labelBgClassName="bg-white dark:bg-charleston-green-2"
        ></Input>
      </div>
      <div className="my-4">
        <Dropdown
          placeholder={t('modals.createAPIKey.sourceDoc')}
          selectedValue={sourcePath ? sourcePath.name : null}
          onSelect={(selection: { name: string; id: string; type: string }) => {
            setSourcePath(selection);
          }}
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
        onClick={() => {
          if (sourcePath && prompt) {
            const payload: any = {
              name: APIKeyName,
              prompt_id: prompt.id,
              chunks: chunk,
            };
            if (sourcePath.type === 'default') {
              payload.retriever = sourcePath.id;
            }
            if (sourcePath.type === 'local') {
              payload.source = sourcePath.id;
            }
            createAPIKey(payload);
          }
        }}
        className="float-right mt-4 rounded-full bg-purple-30 px-5 py-2 text-sm text-white hover:bg-violets-are-blue disabled:opacity-50"
      >
        {t('modals.createAPIKey.create')}
      </button>
    </WrapperModal>
  );
}
