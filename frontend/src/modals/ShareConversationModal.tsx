import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import conversationService from '../api/services/conversationService';
import Spinner from '../components/Spinner';
import ToggleSwitch from '../components/ToggleSwitch';
import { Button } from '../components/ui/button';
import { Modal } from '../components/ui/modal';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { Doc } from '../models/misc';
import {
  selectChunks,
  selectPrompt,
  selectSelectedDocs,
  selectSourceDocs,
  selectToken,
} from '../preferences/preferenceSlice';

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
      ? docs.map((doc: Doc) => {
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
    <Modal
      open={true}
      onOpenChange={(open) => {
        if (!open) close();
      }}
      size="xl"
      title={t('modals.shareConv.label')}
      description={t('modals.shareConv.note')}
      contentClassName="!overflow-visible"
    >
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <span className="text-foreground text-lg dark:text-white">
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
            <Select
              value={sourcePath?.value}
              onValueChange={(value) => {
                const opt = extractDocPaths(sourceDocs ?? []).find(
                  (o) => o.value === value,
                );
                if (opt) setSourcePath(opt);
              }}
            >
              <SelectTrigger className="w-full rounded-xl px-5 py-3" size="lg">
                <SelectValue placeholder={t('modals.createAPIKey.sourceDoc')} />
              </SelectTrigger>
              <SelectContent>
                {extractDocPaths(sourceDocs ?? []).map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
        <div className="flex items-baseline justify-between gap-2">
          <span className="no-scrollbar border-border text-foreground dark:border-border w-full overflow-x-auto rounded-full border-2 px-4 py-3 whitespace-nowrap dark:text-white">
            {`${domain}/share/${identifier ?? '....'}`}
          </span>
          {status === 'fetched' ? (
            <Button
              type="button"
              size="lg"
              className="my-1 w-28 rounded-3xl"
              onClick={() => handleCopyKey(`${domain}/share/${identifier}`)}
            >
              {isCopied ? t('modals.saveKey.copied') : t('modals.saveKey.copy')}
            </Button>
          ) : (
            <Button
              type="button"
              size="lg"
              className="my-1 w-28 justify-evenly rounded-3xl text-center"
              onClick={() => {
                shareCoversationPublicly(allowPrompt);
              }}
            >
              {t('modals.shareConv.create')}
              {status === 'loading' && <Spinner size="small" />}
            </Button>
          )}
        </div>
      </div>
    </Modal>
  );
};
