import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import ViewOnlyNotice from '../components/ViewOnlyNotice';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { Modal, ModalActions } from '../components/ui/modal';
import { SettingRows } from '../components/ui/setting-row';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '../components/ui/tooltip';
import { ActiveState, Doc } from '../models/misc';
import type { Model } from '../models/types';
import { cn, focusRing } from '../lib/utils';
import { selectToken } from '../preferences/preferenceSlice';
import {
  type SyncFrequency,
  websiteRefusal,
  websiteRefusalForCode,
} from '../upload/website';
import { can } from '../utils/accessUtils';
import { canSyncSource } from './sourceKinds';
import WebsiteSettingsFields, {
  ScheduleRow,
  useWebsiteSettings,
} from './WebsiteSettingsFields';

import RetrievalOptions, {
  chunkingChanged,
  configToOptions,
  type DecisionFeatures,
  NO_DECISION_FEATURES,
  isPrescreenConfigValid,
  optionsToConfig,
  type RetrievalOptionsValue,
} from './components/RetrievalOptions';

interface SourceConfigModalProps {
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  document: Doc | null;
  // Fired after a save that flips requires_reingest, when the user confirms
  // the re-ingest. Reuses the existing Sources.tsx reingest action.
  onReingest: (document: Doc) => void;
  hybridAvailable?: boolean;
  graphRAGAvailable?: boolean;
  availableModels?: Model[];
  // The decision-model controls the operator turned on (/api/config).
  decision?: DecisionFeatures;
  // Switching the retriever to graphrag on a non-graphrag source can't go
  // through the config PATCH (the backend blocks kind→graphrag); the parent
  // routes it through EnableGraphRAGModal instead.
  onEnableGraphRAG: (document: Doc) => void;
  /**
   * Called after a save with what changed on the source (its schedule, its
   * config), so the list and the open view update in place.
   */
  onSaved?: (patch: Partial<Doc>) => void;
  /** Starts a sync; offered in the footer of a website or synced source. */
  onSyncNow?: () => void;
  /** A sync of this source is still running (its open view waits for it). */
  syncing?: boolean;
}

/**
 * Source settings: one dialog per source. Its first section follows the
 * kind: a website's pages, skips, Keep links and schedule; a synced source's
 * schedule ("Keep up to date"); nothing for an upload. Retrieval, Filtering
 * and Chunking follow. A website or synced source runs Sync now from the
 * footer. Without `edit` it is read-only, and the first section is left out.
 */

export default function SourceConfigModal({
  modalState,
  setModalState,
  document,
  onReingest,
  hybridAvailable = false,
  graphRAGAvailable = false,
  availableModels = [],
  decision = NO_DECISION_FEATURES,
  onEnableGraphRAG,
  onSaved,
  onSyncNow,
  syncing = false,
}: SourceConfigModalProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);

  // Without `edit` (a viewer opening View config) the form is read-only; the
  // backend rejects a write with 403 anyway.
  const isReadOnly = !!document && !can(document, 'edit');
  const open = modalState === 'ACTIVE';
  // The first section, by kind (editors only).
  const section: 'website' | 'schedule' | null =
    !document || isReadOnly
      ? null
      : document.website && document.id
        ? 'website'
        : canSyncSource(document)
          ? 'schedule'
          : null;
  const website = useWebsiteSettings(
    document?.id ?? '',
    open && section === 'website',
  );
  const savedSchedule = (document?.syncFrequency || 'never') as SyncFrequency;
  const [schedule, setSchedule] = useState<SyncFrequency>(savedSchedule);

  const [initial, setInitial] = useState<RetrievalOptionsValue>(() =>
    configToOptions(document?.config),
  );
  const [options, setOptions] = useState<RetrievalOptionsValue>(() =>
    configToOptions(document?.config),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Set after a successful save that requires a re-ingest; gates the prompt.
  const [reingestPrompt, setReingestPrompt] = useState(false);

  useEffect(() => {
    if (modalState === 'ACTIVE') {
      const hydrated = configToOptions(document?.config);
      setInitial(hydrated);
      setOptions(hydrated);
      setSchedule(savedSchedule);
      setSaving(false);
      setError(null);
      setReingestPrompt(false);
    }
  }, [modalState, document, savedSchedule]);

  const closeModal = () => {
    setModalState('INACTIVE');
  };

  // A non-graphrag source flipped to the graphrag retriever can't be saved via
  // PATCH (backend blocks kind→graphrag); it enables graph extraction instead.
  const becomesGraphRAG =
    options.retrieval.retriever === 'graphrag' &&
    initial.retrieval.retriever !== 'graphrag';

  const scheduleChanged = section === 'schedule' && schedule !== savedSchedule;
  const retrievalChanged =
    JSON.stringify(optionsToConfig(initial)) !==
    JSON.stringify(optionsToConfig(options));

  /**
   * Saves the first section (the website's settings or the schedule).
   *
   * @returns The source fields that changed, or null when the save failed
   *   (the error is shown).
   */
  const saveFirstSection = async (): Promise<Partial<Doc> | null> => {
    if (!document?.id) return null;
    if (section === 'website' && website.changed && website.settings) {
      const settings = website.settings;
      const response = await userService.saveWebsite(
        {
          source_id: document.id,
          entries: settings.entries,
          skip: settings.skip,
          keep_links: settings.keepLinks,
          sync_frequency: settings.syncFrequency,
        },
        token,
      );
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        setError(
          websiteRefusal(t, response.status, data) ??
            t('settings.sources.website.saveFailed'),
        );
        return null;
      }
      website.markSaved();
      return { syncFrequency: settings.syncFrequency };
    }
    if (scheduleChanged) {
      const response = await userService.manageSync(
        { source_id: document.id, sync_frequency: schedule },
        token,
      );
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        // A wiki or an unknown schedule is worded; anything else is generic.
        setError(
          response.status === 403
            ? t('settings.sources.configModal.errors.forbidden')
            : (websiteRefusalForCode(t, data) ??
                t('settings.sources.errors.syncFrequency')),
        );
        return null;
      }
      return { syncFrequency: schedule };
    }
    return {};
  };

  const handleSave = async () => {
    if (!document?.id || isReadOnly) return;
    setSaving(true);
    setError(null);
    try {
      const patch = await saveFirstSection();
      if (patch === null) return;
      if (becomesGraphRAG) {
        if (Object.keys(patch).length) onSaved?.(patch);
        closeModal();
        onEnableGraphRAG(document);
        return;
      }
      if (!retrievalChanged) {
        if (Object.keys(patch).length) onSaved?.(patch);
        closeModal();
        return;
      }
      const response = await userService.updateSourceConfig(
        document.id,
        optionsToConfig(options),
        token,
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data?.success) {
        if (Object.keys(patch).length) onSaved?.(patch);
        if (response.status === 403) {
          setError(t('settings.sources.configModal.errors.forbidden'));
        } else {
          setError(
            data?.message ||
              t('settings.sources.configModal.errors.saveFailed'),
          );
        }
        return;
      }
      // The form's stored baseline is now the saved config; settle it so a
      // follow-up edit compares against the new state.
      setInitial(options);
      onSaved?.({
        ...patch,
        config: { ...document.config, ...optionsToConfig(options) },
      });
      if (data.requires_reingest) {
        setReingestPrompt(true);
      } else {
        closeModal();
      }
    } catch {
      setError(t('settings.sources.configModal.errors.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  const handleConfirmReingest = () => {
    if (document) {
      onReingest(document);
    }
    closeModal();
  };

  const hasChanges =
    retrievalChanged ||
    scheduleChanged ||
    (section === 'website' && website.changed);
  // Surface that the pending change will need a re-ingest before saving too.
  const willRequireReingest = chunkingChanged(initial, options);
  // The backend rejects an incoherent prescreen config; block save up-front.
  const prescreenValid = isPrescreenConfigValid(options);

  // A sync fetches with the saved settings: off until the edits are saved,
  // or they'd be lost when the dialog closes behind it.
  const syncNow = (
    <Button
      type="button"
      variant="outline"
      size="lg"
      shape="pill"
      disabled={saving || hasChanges || syncing}
      onClick={() => {
        onSyncNow?.();
        closeModal();
      }}
    >
      {t('settings.sources.syncNow')}
    </Button>
  );
  const syncNowButton = hasChanges ? (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          tabIndex={0}
          className={cn('flex flex-col rounded-full outline-none', focusRing)}
        >
          {syncNow}
        </span>
      </TooltipTrigger>
      <TooltipContent>
        {t('settings.sources.configModal.syncAfterSave')}
      </TooltipContent>
    </Tooltip>
  ) : (
    syncNow
  );

  const footer = reingestPrompt ? (
    <ModalActions
      cancelLabel={t('settings.sources.configModal.reingestLater')}
      onCancel={closeModal}
      submitLabel={t('settings.sources.reingest')}
      onSubmit={handleConfirmReingest}
    />
  ) : isReadOnly ? (
    <ModalActions cancelLabel={t('common.close')} onCancel={closeModal} />
  ) : (
    <ModalActions
      cancelLabel={t('cancel')}
      onCancel={closeModal}
      cancelProps={{ disabled: saving }}
      submitLabel={t('settings.sources.configModal.save')}
      onSubmit={handleSave}
      pending={saving}
      disabled={!hasChanges || !prescreenValid}
      footerStart={section && onSyncNow ? syncNowButton : undefined}
    />
  );

  return (
    <Modal
      open={modalState === 'ACTIVE'}
      onOpenChange={(o) => !o && closeModal()}
      title={t('settings.sources.configModal.title')}
      description={
        // A website or synced source holds more than chunking: its name.
        section && document?.name
          ? document.name
          : document?.name
            ? t('settings.sources.configModal.subtitle', {
                name: document.name,
                // React escapes the text; i18next escaping it too shows "&amp;".
                interpolation: { escapeValue: false },
              })
            : t('settings.sources.configModal.subtitleGeneric')
      }
      footer={footer}
      size="lg"
      isPerformingTask={saving}
    >
      <div>
        {reingestPrompt ? (
          <div className="flex flex-col gap-4">
            <Alert variant="warning">
              <AlertDescription>
                {t('settings.sources.configModal.reingestRequired')}
              </AlertDescription>
            </Alert>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {isReadOnly && <ViewOnlyNotice />}
            {section === 'website' && (
              <WebsiteSettingsFields
                settings={website.settings}
                onChange={website.setSettings}
                reports={website.reports}
                loadFailed={website.loadFailed}
                onRetry={website.retry}
                syncedAt={document?.date}
              />
            )}
            {section === 'schedule' && (
              <SettingRows>
                <ScheduleRow
                  value={schedule}
                  onChange={setSchedule}
                  syncedAt={document?.date}
                />
              </SettingRows>
            )}
            <RetrievalOptions
              value={options}
              onChange={setOptions}
              alwaysOpen
              disabled={isReadOnly}
              hybridAvailable={hybridAvailable}
              graphRAGAvailable={graphRAGAvailable}
              availableModels={availableModels}
              decision={decision}
            />
            {willRequireReingest && !isReadOnly && (
              <Alert variant="warning">
                <AlertDescription>
                  {t('settings.sources.configModal.chunkingChangeHint')}
                </AlertDescription>
              </Alert>
            )}
            {!prescreenValid && !isReadOnly && (
              <Alert variant="warning">
                <AlertDescription>
                  {t('settings.sources.configModal.prescreenInvalidHint')}
                </AlertDescription>
              </Alert>
            )}
            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}
