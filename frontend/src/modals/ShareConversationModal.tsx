import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import conversationService from '../api/services/conversationService';
import Spinner from '../assets/spinner.svg';
import Dropdown from '../components/Dropdown';
import ToggleSwitch from '../components/ToggleSwitch';
import { Doc } from '../models/misc';
import {
  selectChunks,
  selectPrompt,
  selectSelectedDocs,
  selectSourceDocs,
  selectToken,
} from '../preferences/preferenceSlice';
import WrapperModal from './WrapperModal';

const apiHost = import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';
const embeddingsName =
  import.meta.env.VITE_EMBEDDINGS_NAME ||
  'huggingface_sentence-transformers/all-mpnet-base-v2';

type StatusType = 'loading' | 'idle' | 'fetched' | 'failed';

export const ShareConversationModal = ({
  close,
  conversationId,
}: {
  close: () => void;
  conversationId: string;
}) => {
  const { t } = useTranslation();
  const token = useSelector(selectToken);

  const domain = window.location.origin;

  const [identifier, setIdentifier] = useState<null | string>(null);
  const [isCopied, setIsCopied] = useState(false);
  const [status, setStatus] = useState<StatusType>('idle');
  const [allowPrompt, setAllowPrompt] = useState<boolean>(false);

  const sourceDocs = useSelector(selectSourceDocs);
  const preSelectedDoc = useSelector(selectSelectedDocs);
  const selectedPrompt = useSelector(selectPrompt);
  const selectedChunk = useSelector(selectChunks);

  const extractDocPaths = (docs: Doc[]) =>
    docs
      ? docs
          .filter((doc) => doc.model === embeddingsName)
          .map((doc: Doc) => {
            return {
              label: doc.name,
              value: doc.id ?? 'default',
            };
          })
      : [];

  const [sourcePath, setSourcePath] = useState<{
    label: string;
    value: string;
  } | null>(preSelectedDoc ? extractDocPaths(preSelectedDoc)[0] : null);

  const handleCopyKey = (url: string) => {
    navigator.clipboard.writeText(url);
    setIsCopied(true);
  };

  const togglePromptPermission = () => {
    setAllowPrompt(!allowPrompt);
    setStatus('idle');
    setIdentifier(null);
  };

  const shareCoversationPublicly: (isPromptable: boolean) => void = (
    isPromptable = false,
  ) => {
    setStatus('loading');
    const payload: {
      conversation_id: string;
      chunks?: string;
      prompt_id?: string;
      source?: string;
    } = { conversation_id: conversationId };
    if (isPromptable) {
      payload.chunks = selectedChunk;
      payload.prompt_id = selectedPrompt.id;
      sourcePath && (payload.source = sourcePath.value);
    }
    conversationService
      .shareConversation(isPromptable, payload, token)
      .then((res) => {
        return res.json();
      })
      .then((data) => {
        if (data.success && data.identifier) {
          setIdentifier(data.identifier);
          setStatus('fetched');
        } else setStatus('failed');
      })
      .catch((err) => setStatus('failed'));
  };

  return (
    <WrapperModal close={close}>
      <div className="flex flex-col gap-2">
        <h2 className="text-eerie-black dark:text-chinese-white text-xl font-medium">
          {t('modals.shareConv.label')}
        </h2>
        <p className="text-eerie-black dark:text-silver/60 text-sm">
          {t('modals.shareConv.note')}
        </p>
        <div className="flex items-center justify-between">
          <span className="text-eerie-black text-lg dark:text-white">
            {t('modals.shareConv.option')}
          </span>
          <ToggleSwitch
            checked={allowPrompt}
            onChange={togglePromptPermission}
            size="medium"
          />
        </div>
        {allowPrompt && (
          <div className="my-4">
            <Dropdown
              placeholder={t('modals.createAPIKey.sourceDoc')}
              selectedValue={sourcePath}
              onSelect={(selection: { label: string; value: string }) =>
                setSourcePath(selection)
              }
              options={extractDocPaths(sourceDocs ?? [])}
              size="w-full"
              rounded="xl"
            />
          </div>
        )}
        <div className="flex items-baseline justify-between gap-2">
          <span className="no-scrollbar border-silver text-eerie-black dark:border-silver/40 w-full overflow-x-auto rounded-full border-2 px-4 py-3 whitespace-nowrap dark:text-white">
            {`${domain}/share/${identifier ?? '....'}`}
          </span>
          {status === 'fetched' ? (
            <button
              className="bg-purple-30 hover:bg-violets-are-blue my-1 h-10 w-28 rounded-full p-2 text-sm text-white"
              onClick={() => handleCopyKey(`${domain}/share/${identifier}`)}
            >
              {isCopied ? t('modals.saveKey.copied') : t('modals.saveKey.copy')}
            </button>
          ) : (
            <button
              className="bg-purple-30 hover:bg-violets-are-blue my-1 flex h-10 w-28 items-center justify-evenly rounded-full p-2 text-center text-sm font-normal text-white"
              onClick={() => {
                shareCoversationPublicly(allowPrompt);
              }}
            >
              {t('modals.shareConv.create')}
              {status === 'loading' && (
                <img
                  src={Spinner}
                  className="inline animate-spin cursor-pointer bg-transparent filter dark:invert"
                ></img>
              )}
            </button>
          )}
        </div>
      </div>
    </WrapperModal>
  );
};
