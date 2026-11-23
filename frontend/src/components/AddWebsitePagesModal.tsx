import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import { selectToken } from '../preferences/preferenceSlice';
import WebsiteFields from '../upload/WebsiteFields';
import useWebPageLimits, {
  useReseedMaxPages,
} from '../upload/useWebPageLimits';
import {
  defaultWebsiteDraft,
  isQueueFailed,
  isWebsiteDraftValid,
  type WebsiteDraft,
  websiteConfig,
  websiteRefusal,
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
 * @param graph The source has a knowledge graph: a note says what the LLM
 *   extraction costs (new pages' chunks, or the whole source when it is
 *   rebuilt).
 * @param onClose Closes the dialog.
 * @param onQueued Called once the server accepts, with when the request went
 *   out and the task it queued, so the caller can wait for the ingest to
 *   finish (its event names the pages it touched).
 * @param onQueueFailed Called, before the dialog closes, when the server
 *   saved the pages but couldn't queue their fetch (`queue_failed`; the next
 *   sync fetches them), with the message to warn with.
 */
export default function AddWebsitePagesModal({
  sourceId,
  sourceName,
  graph = false,
  onClose,
  onQueued,
  onQueueFailed,
}: {
  sourceId: string;
  sourceName: string;
  graph?: boolean;
  onClose: () => void;
  onQueued: (startedAt: number, taskId: string | null) => void;
  onQueueFailed: (message: string) => void;
}) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const limits = useWebPageLimits();
  const [draft, setDraft] = useState<WebsiteDraft>(() =>
    defaultWebsiteDraft(limits.defaultPages),
  );
  useReseedMaxPages(limits.defaultPages, setDraft);
  const [pending, setPending] = useState(false);
  // The message to show when the server refused, worded here.
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setPending(true);
    setError(null);
    const startedAt = Date.now();
    const { entries } = websiteConfig(draft, false);
    try {
      const response = await userService.addWebsitePages(
        { source_id: sourceId, entries },
        token,
      );
      const data = await response.json().catch(() => null);
      const refusal = websiteRefusal(t, response.status, data);
      if (refusal && isQueueFailed(data)) {
        // Saved: submitting again would add them twice.
        onQueueFailed(refusal);
        onClose();
        return;
      }
      if (!response.ok || !data?.success) {
        setError(refusal ?? t('settings.sources.website.addFailed'));
        return;
      }
      // `mode: 'sync'` (a site, a new host, or a store that can't add single
      // chunks) rebuilds the source; its task's events end the wait the same way.
      onQueued(
        startedAt,
        typeof data.task_id === 'string' ? data.task_id : null,
      );
      onClose();
    } catch {
      setError(t('settings.sources.website.addFailed'));
    } finally {
      setPending(false);
    }
  };

  return (
    <Modal
      open={true}
      // Once sent, the add can't be called back: the dialog stays until the
      // server answers, so a refusal has somewhere to show.
      onOpenChange={(open) => !open && !pending && onClose()}
      isPerformingTask={pending}
      title={t('settings.sources.website.addPages')}
      description={sourceName}
      size="lg"
      footer={
        <ModalActions
          cancelLabel={t('cancel')}
          onCancel={onClose}
          cancelProps={{ disabled: pending }}
          submitLabel={t('settings.sources.website.addPages')}
          onSubmit={submit}
          pending={pending}
          disabled={!isWebsiteDraftValid(draft, limits.maxPages)}
        />
      }
    >
      <div className="flex flex-col gap-5">
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
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
        {/* A whole site always rebuilds the source, and so its graph; pages
            are appended unless the server rebuilds (another host, or a store
            that can't add single chunks), which graphCost covers too. */}
        {graph && (
          <Alert variant="info" role="note">
            <AlertDescription>
              {draft.mode === 'site'
                ? t('settings.sources.website.graphCostRebuild')
                : t('settings.sources.website.graphCost')}
            </AlertDescription>
          </Alert>
        )}
      </div>
    </Modal>
  );
}
