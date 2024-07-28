import { SyntheticEvent, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import {
  selectSourceDocs,
  selectSelectedDocs,
  selectChunks,
  selectPrompt,
} from '../preferences/preferenceSlice';
import Dropdown from '../components/Dropdown';
import { Doc } from '../models/misc';
import Spinner from '../assets/spinner.svg';
import Exit from '../assets/exit.svg';
const apiHost = import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';
const embeddingsName =
  import.meta.env.VITE_EMBEDDINGS_NAME ||
  'huggingface_sentence-transformers/all-mpnet-base-v2';

type StatusType = 'loading' | 'idle' | 'fetched' | 'failed';

import conversationService from '../api/services/conversationService';

export const ShareConversationModal = ({
  close,
  conversationId,
}: {
  close: () => void;
  conversationId: string;
}) => {
  const { t } = useTranslation();

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

  const [sourcePath, setSourcePath] = useState<{
    label: string;
    value: string;
  } | null>(preSelectedDoc ? extractDocPaths([preSelectedDoc])[0] : null);

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
      .shareConversation(isPromptable, payload)
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
    <div
      onClick={(event: SyntheticEvent) => event.stopPropagation()}
      className="z-100 fixed top-0 left-0 flex h-screen w-screen items-center justify-center bg-gray-alpha bg-opacity-50 text-chinese-black dark:text-silver"
    >
      <div className="relative w-11/12 rounded-2xl bg-white p-10 dark:bg-outer-space sm:w-[512px]">
        <button className="absolute top-3 right-4 m-2 w-3" onClick={close}>
          <img className="filter dark:invert" src={Exit} />
        </button>
        <div className="flex flex-col gap-2">
          <h2 className="text-xl font-medium">{t('modals.shareConv.label')}</h2>
          <p className="text-sm">{t('modals.shareConv.note')}</p>
          <div className="flex items-center justify-between">
            <span className="text-lg">{t('modals.shareConv.option')}</span>
            <label className=" cursor-pointer select-none items-center">
              <div className="relative">
                <input
                  type="checkbox"
                  checked={allowPrompt}
                  onChange={togglePromptPermission}
                  className="sr-only"
                />
                <div
                  className={`box block h-8 w-14 rounded-full border border-purple-30 ${
                    allowPrompt
                      ? 'bg-purple-30 dark:bg-purple-30'
                      : 'dark:bg-transparent'
                  }`}
                ></div>
                <div
                  className={`absolute left-1 top-1 flex h-6 w-6 items-center justify-center rounded-full  transition ${
                    allowPrompt ? 'translate-x-full bg-silver' : 'bg-purple-30'
                  }`}
                ></div>
              </div>
            </label>
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
            <span className="no-scrollbar w-full overflow-x-auto whitespace-nowrap rounded-full border-2 py-3 px-4">
              {`${domain}/share/${identifier ?? '....'}`}
            </span>
            {status === 'fetched' ? (
              <button
                className="my-1 h-10 w-28 rounded-full border border-solid border-purple-30 p-2 text-sm text-purple-30 hover:bg-purple-30 hover:text-white"
                onClick={() => handleCopyKey(`${domain}/share/${identifier}`)}
              >
                {isCopied
                  ? t('modals.saveKey.copied')
                  : t('modals.saveKey.copy')}
              </button>
            ) : (
              <button
                className="my-1 flex h-10 w-28 items-center justify-evenly rounded-full  border border-solid border-purple-30 p-2 text-center text-sm font-normal text-purple-30 hover:bg-purple-30 hover:text-white"
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
      </div>
    </div>
  );
};
