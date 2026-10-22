import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import { selectToken } from '../preferences/preferenceSlice';
import WebsiteFields from '../upload/WebsiteFields';
import useWebPageLimits from '../upload/useWebPageLimits';
import {
  defaultWebsiteDraft,
  isWebsiteDraftValid,
  type WebsiteDraft,
  websiteConfig,
} from '../upload/website';
import { Alert, AlertDescription } from './ui/alert';
import { Modal, ModalActions } from './ui/modal';

/**
 * "Add pages" on a Website source: the Website form without its name or
 * schedule, which the source already has. Pages are fetched now and stay in
 * every sync; a whole site rebuilds the source (see /api/website/pages).
 *
 * @param sourceId The source.
 * @param sourceName Shown under the title.
 * @param onClose Closes the dialog.
 * @param onQueued Called once the server accepts, with when the request went
 *   out, so the caller can wait for the ingest to finish.
 */
export default function AddWebsitePagesModal({
  sourceId,
  sourceName,
  onClose,
  onQueued,
}: {
  sourceId: string;
  sourceName: string;
  onClose: () => void;
  onQueued: (startedAt: number) => void;
}) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const limits = useWebPageLimits();
  const [draft, setDraft] = useState<WebsiteDraft>(() =>
    defaultWebsiteDraft(limits.defaultPages),
  );
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);

  const submit = async () => {
    setPending(true);
    setFailed(false);
    const startedAt = Date.now();
    try {
      const response = await userService.addWebsitePages(
        {
          source_id: sourceId,
          entries: websiteConfig(draft, false).entries,
        },
        token,
      );
      const data = await response.json();
      if (!response.ok || !data?.success) throw new Error('add failed');
      onQueued(startedAt);
      onClose();
    } catch {
      setFailed(true);
    } finally {
      setPending(false);
    }
  };

  return (
    <Modal
      open={true}
      onOpenChange={(open) => !open && onClose()}
      title={t('settings.sources.website.addPages')}
      description={sourceName}
      size="lg"
      footer={
        <ModalActions
          cancelLabel={t('cancel')}
          onCancel={onClose}
          submitLabel={t('settings.sources.website.addPages')}
          onSubmit={submit}
          pending={pending}
          disabled={!isWebsiteDraftValid(draft, limits.maxPages)}
        />
      }
    >
      <div className="flex flex-col gap-5">
        {failed && (
          <Alert variant="destructive">
            <AlertDescription>
              {t('settings.sources.website.addFailed')}
            </AlertDescription>
          </Alert>
        )}
        <WebsiteFields
          draft={draft}
          onChange={setDraft}
          maxPages={limits.maxPages}
        />
        <p className="text-muted-foreground text-xs">
          {t('settings.sources.website.addPagesHint')}
        </p>
      </div>
    </Modal>
  );
}
