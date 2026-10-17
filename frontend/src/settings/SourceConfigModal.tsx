import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import ViewOnlyNotice from '../components/ViewOnlyNotice';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Modal, ModalActions } from '../components/ui/modal';
import { SettingRow, SettingRows } from '../components/ui/setting-row';
import { Switch } from '../components/ui/switch';
import { ActiveState, Doc } from '../models/misc';
import type { Model } from '../models/types';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';
import { can } from '../utils/accessUtils';

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
}

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
}: SourceConfigModalProps) {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);

  // Without `edit` (a viewer opening View config) the form is read-only; the
  // backend rejects a write with 403 anyway.
  const isReadOnly = !!document && !can(document, 'edit');

  const [initial, setInitial] = useState<RetrievalOptionsValue>(() =>
    configToOptions(document?.config),
  );
  const [options, setOptions] = useState<RetrievalOptionsValue>(() =>
    configToOptions(document?.config),
  );
  // The source's prompt-injection scan, a guardrails setting beside the
  // retrieval form; saved only while the operator has the model on.
  const savedScan = Boolean(document?.config?.guardrails?.injection_scan);
  const [initialScan, setInitialScan] = useState(savedScan);
  const [injectionScan, setInjectionScan] = useState(savedScan);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Set after a successful save that requires a re-ingest; gates the prompt.
  const [reingestPrompt, setReingestPrompt] = useState(false);

  useEffect(() => {
    if (modalState === 'ACTIVE') {
      const hydrated = configToOptions(document?.config);
      setInitial(hydrated);
      setOptions(hydrated);
      setInitialScan(Boolean(document?.config?.guardrails?.injection_scan));
      setInjectionScan(Boolean(document?.config?.guardrails?.injection_scan));
      setSaving(false);
      setError(null);
      setReingestPrompt(false);
    }
  }, [modalState, document]);

  const closeModal = () => {
    setModalState('INACTIVE');
  };

  // A non-graphrag source flipped to the graphrag retriever can't be saved via
  // PATCH (backend blocks kind→graphrag); it enables graph extraction instead.
  const becomesGraphRAG =
    options.retrieval.retriever === 'graphrag' &&
    initial.retrieval.retriever !== 'graphrag';

  const handleSave = async () => {
    if (!document?.id || isReadOnly) return;
    if (becomesGraphRAG) {
      closeModal();
      onEnableGraphRAG(document);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const response = await userService.updateSourceConfig(
        document.id,
        {
          ...optionsToConfig(options),
          // Left out, the server keeps the saved value.
          ...(decision.injection
            ? { guardrails: { injection_scan: injectionScan } }
            : {}),
        },
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
      setInitialScan(injectionScan);
      // The scan of the chunks already indexed runs after the modal closes.
      if (
        data.injection_backfill === 'queued' ||
        data.injection_backfill === 'lazy'
      ) {
        dispatch(
          showActionToast({
            variant: 'success',
            message: t(
              data.injection_backfill === 'queued'
                ? 'settings.sources.configModal.backfillQueued'
                : 'settings.sources.configModal.backfillLazy',
            ),
          }),
        );
      }
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
      JSON.stringify(optionsToConfig(options)) ||
    (decision.injection && injectionScan !== initialScan);
  // Surface that the pending change will need a re-ingest before saving too.
  const willRequireReingest = chunkingChanged(initial, options);
  // The backend rejects an incoherent prescreen config; block save up-front.
  const prescreenValid = isPrescreenConfigValid(options);

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
    />
  );

  return (
    <Modal
      open={modalState === 'ACTIVE'}
      onOpenChange={(o) => !o && closeModal()}
      title={t('settings.sources.configModal.title')}
      description={
        document?.name
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
            {decision.injection && (
              <SettingRows>
                <SettingRow
                  label={t('settings.sources.configModal.injectionScan')}
                  description={t(
                    'settings.sources.configModal.injectionScanDescription',
                  )}
                  alignStart
                >
                  <Switch
                    checked={injectionScan}
                    disabled={isReadOnly}
                    onCheckedChange={setInjectionScan}
                    data-testid="source-injection-scan"
                  />
                </SettingRow>
              </SettingRows>
            )}
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
