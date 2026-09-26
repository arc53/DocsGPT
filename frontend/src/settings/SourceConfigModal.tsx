import { CircleAlert, TriangleAlert } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Modal, ModalActions } from '../components/ui/modal';
import { ActiveState, Doc } from '../models/misc';
import type { Model } from '../models/types';
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
  hybridAvailable?: boolean;
  graphRAGAvailable?: boolean;
  availableModels?: Model[];
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
  onEnableGraphRAG,
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

  const footer = reingestPrompt ? (
    <ModalActions
      cancelLabel={t('settings.sources.configModal.reingestLater')}
      onCancel={closeModal}
      submitLabel={t('settings.sources.reingest')}
      onSubmit={handleConfirmReingest}
    />
  ) : (
    <ModalActions
      cancelLabel={t('cancel')}
      onCancel={closeModal}
      cancelProps={{ disabled: saving }}
      submitLabel={t('settings.sources.configModal.save')}
      onSubmit={handleSave}
      pending={saving}
      disabled={isReadOnly || !hasChanges || !prescreenValid}
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
            })
          : t('settings.sources.configModal.subtitleGeneric')
      }
      footer={footer}
      size="lg"
      mobileVariant="sheet"
      isPerformingTask={saving}
    >
      <div>
        {reingestPrompt ? (
          <div className="flex flex-col gap-4">
            <Alert variant="warning">
              <TriangleAlert className="size-4" aria-hidden="true" />
              <AlertDescription>
                {t('settings.sources.configModal.reingestRequired')}
              </AlertDescription>
            </Alert>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
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
              hybridAvailable={hybridAvailable}
              graphRAGAvailable={graphRAGAvailable}
              availableModels={availableModels}
            />
            {willRequireReingest && !isReadOnly && (
              <Alert variant="warning">
                <TriangleAlert className="size-4" aria-hidden="true" />
                <AlertDescription>
                  {t('settings.sources.configModal.chunkingChangeHint')}
                </AlertDescription>
              </Alert>
            )}
            {!prescreenValid && !isReadOnly && (
              <Alert variant="warning">
                <TriangleAlert className="size-4" aria-hidden="true" />
                <AlertDescription>
                  {t('settings.sources.configModal.prescreenInvalidHint')}
                </AlertDescription>
              </Alert>
            )}
            {error && (
              <Alert variant="destructive">
                <CircleAlert className="size-4" aria-hidden="true" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}
