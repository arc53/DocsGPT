import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import conversationService from '../api/services/conversationService';
import CopyButton from '../components/CopyButton';
import { Button } from '../components/ui/button';
import { FormField } from '../components/ui/form-field';
import { Modal } from '../components/ui/modal';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { SettingRow } from '../components/ui/setting-row';
import { Switch } from '../components/ui/switch';
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
  const [status, setStatus] = useState<StatusType>('idle');
  const [allowPrompt, setAllowPrompt] = useState<boolean>(false);
  const promptSwitchId = useId();

  const sourceDocs = useSelector(selectSourceDocs);
  const preSelectedDoc = useSelector(selectSelectedDocs);
  const selectedPrompt = useSelector(selectPrompt);
  const selectedChunk = useSelector(selectChunks);

  // Only ingested sources (rows with an id) can be shared.
  const extractDocPaths = (docs: Doc[]) =>
    docs
      ? docs
          .filter((doc: Doc) => Boolean(doc.id))
          .map((doc: Doc) => ({ label: doc.name, value: doc.id as string }))
      : [];

  const [sourcePath, setSourcePath] = useState<{
    label: string;
    value: string;
  } | null>(preSelectedDoc ? extractDocPaths(preSelectedDoc)[0] : null);

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
      footer={
        status === 'fetched' ? (
          <CopyButton
            size="lg"
            textToCopy={`${domain}/share/${identifier}`}
            copyLabel={t('modals.saveKey.copy')}
            copiedLabel={t('modals.saveKey.copied')}
          />
        ) : (
          <Button
            type="button"
            size="lg"
            shape="pill"
            loading={status === 'loading'}
            onClick={() => {
              shareCoversationPublicly(allowPrompt);
            }}
          >
            {t('modals.shareConv.create')}
          </Button>
        )
      }
    >
      <div className="flex flex-col gap-2">
        <SettingRow
          label={t('modals.shareConv.option')}
          htmlFor={promptSwitchId}
        >
          <Switch
            id={promptSwitchId}
            checked={allowPrompt}
            onCheckedChange={togglePromptPermission}
          />
        </SettingRow>
        {allowPrompt && (
          <FormField
            label={t('modals.createAPIKey.sourceDoc')}
            className="my-4"
          >
            <Select
              value={sourcePath?.value}
              onValueChange={(value) => {
                const opt = extractDocPaths(sourceDocs ?? []).find(
                  (o) => o.value === value,
                );
                if (opt) setSourcePath(opt);
              }}
            >
              <SelectTrigger className="w-full" size="field">
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
          </FormField>
        )}
        <span className="no-scrollbar border-border text-foreground w-full overflow-x-auto rounded-full border-2 px-4 py-3 whitespace-nowrap">
          {`${domain}/share/${identifier ?? '....'}`}
        </span>
      </div>
    </Modal>
  );
};
