import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import Spinner from '../components/Spinner';
import { Button } from '../components/ui/button';
import { Modal } from '../components/ui/modal';
import { ActiveState, Doc } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';

import RetrievalOptions, {
  chunkingChanged,
  configToOptions,
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
}

export default function SourceConfigModal({
  modalState,
  setModalState,
  document,
  onReingest,
}: SourceConfigModalProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);

  // 'team' viewers cannot write; the backend rejects with 403, but we also
  // disable the form up-front for a clearer read-only experience.
  const isReadOnly =
    document?.ownership === 'team' && document?.team_access !== 'editor';

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
      setSaving(false);
      setError(null);
      setReingestPrompt(false);
    }
  }, [modalState, document]);

  const closeModal = () => {
    setModalState('INACTIVE');
  };

  const handleSave = async () => {
    if (!document?.id || isReadOnly) return;
    setSaving(true);
    setError(null);
    try {
      const response = await userService.updateSourceConfig(
        document.id,
        optionsToConfig(options),
        token,
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data?.success) {
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
    JSON.stringify(optionsToConfig(initial)) !==
    JSON.stringify(optionsToConfig(options));
  // Surface that the pending change will need a re-ingest before saving too.
  const willRequireReingest = chunkingChanged(initial, options);
  // The backend rejects an incoherent prescreen config; block save up-front.
  const prescreenValid = isPrescreenConfigValid(options);

  return (
    <Modal
      open={modalState === 'ACTIVE'}
      onOpenChange={(o) => !o && closeModal()}
      hideTitle
      title={t('settings.sources.configModal.title')}
      size="lg"
      mobileVariant="sheet"
      className="max-h-[90vh] max-w-[600px] md:w-[80vw] lg:w-[60vw]"
      contentClassName="max-h-[80vh]"
      isPerformingTask={saving}
    >
      <div className="flex h-full flex-col">
        <div className="px-2 py-2">
          <h2 className="text-foreground dark:text-foreground text-xl font-semibold">
            {t('settings.sources.configModal.title')}
          </h2>
          <p className="text-muted-foreground mt-2 text-sm">
            {document?.name
              ? t('settings.sources.configModal.subtitle', {
                  name: document.name,
                })
              : t('settings.sources.configModal.subtitleGeneric')}
          </p>
        </div>

        <div className="flex-1 px-2">
          {reingestPrompt ? (
            <div className="flex flex-col gap-4 px-0.5 py-4">
              <div className="rounded-xl bg-amber-50 p-4 text-sm text-amber-800 dark:bg-amber-900/30 dark:text-amber-200">
                {t('settings.sources.configModal.reingestRequired')}
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-4 px-0.5 py-4">
              {isReadOnly && (
                <div className="bg-muted text-muted-foreground rounded-xl p-3 text-sm">
                  {t('settings.sources.configModal.readOnly')}
                </div>
              )}
              <RetrievalOptions
                value={options}
                onChange={setOptions}
                alwaysOpen
                disabled={isReadOnly}
              />
              {willRequireReingest && !isReadOnly && (
                <div className="rounded-xl bg-amber-50 p-3 text-xs text-amber-800 dark:bg-amber-900/30 dark:text-amber-200">
                  {t('settings.sources.configModal.chunkingChangeHint')}
                </div>
              )}
              {!prescreenValid && !isReadOnly && (
                <div className="rounded-xl bg-amber-50 p-3 text-xs text-amber-800 dark:bg-amber-900/30 dark:text-amber-200">
                  {t('settings.sources.configModal.prescreenInvalidHint')}
                </div>
              )}
              {error && (
                <div className="rounded-xl bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/40 dark:text-red-300">
                  {error}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="px-2 py-4">
          {reingestPrompt ? (
            <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end sm:gap-3">
              <Button
                type="button"
                variant="ghost"
                onClick={closeModal}
                className="w-full rounded-3xl px-6 sm:w-auto"
              >
                {t('settings.sources.configModal.reingestLater')}
              </Button>
              <Button
                type="button"
                onClick={handleConfirmReingest}
                className="w-full rounded-3xl px-6 sm:w-auto"
              >
                {t('settings.sources.reingest')}
              </Button>
            </div>
          ) : (
            <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end sm:gap-3">
              <Button
                type="button"
                variant="ghost"
                onClick={closeModal}
                disabled={saving}
                className="w-full rounded-3xl px-6 sm:w-auto"
              >
                {t('cancel')}
              </Button>
              <Button
                type="button"
                onClick={handleSave}
                disabled={
                  saving || isReadOnly || !hasChanges || !prescreenValid
                }
                className="w-full rounded-3xl px-6 sm:w-auto"
              >
                {saving ? (
                  <div className="flex items-center justify-center">
                    <Spinner size="small" />
                    <span className="ml-2">
                      {t('settings.sources.configModal.saving')}
                    </span>
                  </div>
                ) : (
                  t('settings.sources.configModal.save')
                )}
              </Button>
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}
