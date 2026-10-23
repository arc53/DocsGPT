import {
  BookOpen,
  Eye,
  Network,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Trash2,
  Users,
} from 'lucide-react';
import { type ReactNode, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import modelService from '../api/services/modelService';
import userService from '../api/services/userService';
import type { MenuOption } from '../components/ui/dropdown-menu';
import { syncRefusal } from '../connectors/syncRefusal';
import ConfirmationModal from '../modals/ConfirmationModal';
import type { Doc } from '../models/misc';
import type { Model } from '../models/types';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';
import ShareToTeamModal from '../teams/ShareToTeamModal';
import {
  addUploadTask,
  removeUploadTask,
  selectUploadTasks,
  updateUploadTask,
} from '../upload/uploadSlice';
import { can } from '../utils/accessUtils';
import {
  type DecisionFeatures,
  NO_DECISION_FEATURES,
  decisionFeatures,
} from './components/RetrievalOptions';
import ConvertToWikiModal from './ConvertToWikiModal';
import EnableGraphRAGModal from './EnableGraphRAGModal';
import SourceConfigModal from './SourceConfigModal';
import {
  canSyncSource,
  isGraphSource,
  isWikiSource,
  sourcePrimary,
} from './sourceKinds';
import TestRetrievalModal from './TestRetrievalModal';
import WikiSettingsModal from './WikiSettingsModal';

/** Where a source's menu shows: its card in the grid, or its opened view. */
export type SourceMenuPlace = 'card' | 'view';

/** A sync the server accepted: when its request went out and its task. */
export type StartedSync = { startedAt: number; taskId: string | null };

interface UseSourceActionsOptions {
  /** Opens the source (the card's View). */
  onView: (doc: Doc) => void;
  /** Deletes the source; a rejection keeps the confirm open with its message. */
  onDelete: (doc: Doc) => void | Promise<unknown>;
  /** After a delete: re-read the list and leave an open view of it. */
  onDeleted: (doc: Doc) => void;
  /** Re-reads the list (after a reingest, a conversion or a graph enable). */
  onChanged: () => void;
  /** Updates the source in place (a saved schedule or config), no refetch. */
  onPatched: (id: string, patch: Partial<Doc>) => void;
  /**
   * A sync the server accepted (Sync now from a menu or Source settings), so
   * an open view of the source can wait for it to finish.
   */
  onSyncStarted?: (doc: Doc, sync: StartedSync) => void;
}

/**
 * Every source-level action, for the card's menu and the opened source's ⋯,
 * so the two can't drift apart: the menu options, the dialogs they open
 * (Source settings, Wiki settings, Test retrieval, Share, Convert to wiki,
 * Enable GraphRAG, the delete confirm) and Sync now and Reingest with their
 * toasts. Render `modals` once wherever the menus show.
 *
 * @returns `menuOptions(doc, place)`, `openTestRetrieval`, `syncNow` and
 *   `modals`.
 */
export function useSourceActions({
  onView,
  onDelete,
  onDeleted,
  onChanged,
  onPatched,
  onSyncStarted,
}: UseSourceActionsOptions) {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const uploadTasks = useSelector(selectUploadTasks);

  const [toConfigure, setToConfigure] = useState<Doc | null>(null);
  const [toTest, setToTest] = useState<Doc | null>(null);
  const [toShare, setToShare] = useState<Doc | null>(null);
  const [toConvert, setToConvert] = useState<Doc | null>(null);
  const [toGraph, setToGraph] = useState<Doc | null>(null);
  const [wikiSettingsOf, setWikiSettingsOf] = useState<Doc | null>(null);
  const [toDelete, setToDelete] = useState<Doc | null>(null);

  // What the instance offers the settings and tester dialogs.
  const [graphRAGAvailable, setGraphRAGAvailable] = useState(false);
  const [hybridAvailable, setHybridAvailable] = useState(false);
  const [decision, setDecision] =
    useState<DecisionFeatures>(NO_DECISION_FEATURES);
  const [availableModels, setAvailableModels] = useState<Model[]>([]);

  useEffect(() => {
    let cancelled = false;
    userService
      .getConfig()
      .then((response) => response.json())
      .then((config) => {
        if (cancelled) return;
        setGraphRAGAvailable(!!config?.graphrag_available);
        setHybridAvailable(!!config?.hybrid_available);
        setDecision(decisionFeatures(config));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  // Models back the graph extraction-model picker in Source settings; only
  // fetched when the instance supports GraphRAG.
  useEffect(() => {
    if (!graphRAGAvailable) return;
    let cancelled = false;
    modelService
      .getModels(token)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (!cancelled && data)
          setAvailableModels(modelService.transformModels(data.models || []));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [graphRAGAvailable, token]);

  /** A failed action as a destructive toast: the forbidden message on a 403. */
  const showActionError = (message: string, status?: number) =>
    dispatch(
      showActionToast({
        variant: 'destructive',
        message:
          status === 403 ? t('settings.sources.errors.forbidden') : message,
      }),
    );

  /**
   * Starts a sync and says so, or says why it couldn't. An accepted one goes
   * to `onSyncStarted`, with when the request went out (before it, so the
   * sync's own events can't predate it) and its task.
   */
  const syncNow = async (doc: Doc) => {
    if (!doc.id) return;
    const failed = t('settings.sources.errors.sync');
    const startedAt = Date.now();
    try {
      // The server finds a connector source's connection itself.
      const response = doc.type?.startsWith('connector')
        ? await userService.syncConnector(doc.id, token)
        : await userService.syncSource({ source_id: doc.id }, token);
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data?.success) {
        showActionError(
          syncRefusal(t, data, { status: response.status, fallback: failed }),
          response.status,
        );
        return;
      }
      dispatch(
        showActionToast({
          variant: 'success',
          message: t('settings.sources.syncStarted', {
            name: doc.name,
            interpolation: { escapeValue: false },
          }),
        }),
      );
      onSyncStarted?.(doc, {
        startedAt,
        taskId: typeof data?.task_id === 'string' ? data.task_id : null,
      });
    } catch {
      showActionError(failed);
    }
  };

  const reingest = async (doc: Doc) => {
    if (!doc.id) return;
    const sourceId = doc.id;
    // Drop stale toast rows for this source (a finished/dismissed task
    // would swallow the reingest's SSE events), then open a fresh one.
    uploadTasks
      .filter((task) => task.sourceId === sourceId)
      .forEach((task) => dispatch(removeUploadTask(task.id)));
    const taskId = `reingest-${sourceId}-${Date.now()}`;
    dispatch(
      addUploadTask({
        id: taskId,
        fileName: doc.name || sourceId,
        progress: 0,
        status: 'training',
        sourceId,
      }),
    );
    const fail = (errorMessage?: string) =>
      dispatch(
        updateUploadTask({
          id: taskId,
          updates: { status: 'failed', errorMessage },
        }),
      );
    try {
      const response = await userService.reingestSource(
        { source_id: sourceId },
        token,
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data?.success) {
        fail(data?.error || data?.message);
        showActionError(t('settings.sources.errors.reingest'), response.status);
        return;
      }
      onChanged();
    } catch {
      showActionError(t('settings.sources.errors.reingest'));
      fail();
    }
  };

  const openTestRetrieval = (doc: Doc) => setToTest(doc);

  /**
   * The source's actions. On the card: View, Reingest (failed), Sync now,
   * Settings, Test retrieval, Convert to wiki, Share with team, then Delete
   * set apart. In the opened view the same, less View and Test retrieval
   * (a button beside it), and less Sync now where it is the view's primary.
   */
  const menuOptions = (doc: Doc, place: SourceMenuPlace): MenuOption[] => {
    const wiki = isWikiSource(doc);
    const graph = isGraphSource(doc);
    // The server's allowed_actions decide every write (utils/accessUtils).
    const canEdit = can(doc, 'edit');
    const card = place === 'card';
    const options: MenuOption[] = [];

    if (card) {
      options.push({
        icon: graph ? Network : Eye,
        label: wiki
          ? t('settings.sources.wiki.view')
          : graph
            ? t('settings.sources.graphrag.view.action')
            : t('settings.sources.view'),
        onClick: () => onView(doc),
      });
    }

    if (canEdit && doc.ingestStatus === 'failed') {
      options.push({
        icon: RefreshCw,
        label: t('settings.sources.reingest'),
        onClick: () => void reingest(doc),
      });
    }

    if (
      canEdit &&
      doc.id &&
      canSyncSource(doc) &&
      (card || sourcePrimary(doc) !== 'syncNow')
    ) {
      options.push({
        icon: RefreshCw,
        label: t('settings.sources.syncNow'),
        onClick: () => void syncNow(doc),
      });
    }

    if (doc.id && wiki) {
      // A wiki's own settings are the owner's (manage_settings).
      if (can(doc, 'manage_settings'))
        options.push({
          icon: SlidersHorizontal,
          label: t('settings.sources.editConfig'),
          onClick: () => setWikiSettingsOf(doc),
        });
    } else if (doc.id && (canEdit || can(doc, 'view_config'))) {
      // Editors edit the settings; a viewer may read them (view_config).
      options.push({
        icon: canEdit ? SlidersHorizontal : Eye,
        label: canEdit
          ? t('settings.sources.editConfig')
          : t('settings.sources.viewConfig'),
        onClick: () => setToConfigure(doc),
      });
    }

    if (card && doc.id) {
      options.push({
        icon: Search,
        label: t('settings.sources.testRetrieval.action'),
        onClick: () => openTestRetrieval(doc),
      });
    }

    if (
      doc.id &&
      !wiki &&
      canEdit &&
      doc.ingestStatus !== 'processing' &&
      doc.ingestStatus !== 'failed'
    ) {
      options.push({
        icon: BookOpen,
        label: t('settings.sources.wiki.convert.action'),
        onClick: () => setToConvert(doc),
      });
    }

    // Owner-only unless the owner lets editors share (editors_can_share).
    if (doc.id && can(doc, 'share')) {
      options.push({
        icon: Users,
        label: t('settings.sources.shareWithTeam'),
        onClick: () => setToShare(doc),
      });
    }

    if (can(doc, 'delete')) {
      options.push({
        icon: Trash2,
        label: card
          ? t('settings.sources.delete')
          : t('settings.sources.deleteSource'),
        onClick: () => setToDelete(doc),
        variant: 'destructive',
        separatorBefore: true,
      });
    }

    return options;
  };

  // Returned to ConfirmationModal: it stays pending while the delete runs
  // and keeps a failure (its message) in the dialog.
  const confirmDelete = async () => {
    if (!toDelete) return;
    const doc = toDelete;
    await onDelete(doc);
    setToDelete(null);
    onDeleted(doc);
  };

  const modals: ReactNode = (
    <>
      {toDelete && (
        <ConfirmationModal
          message={t('settings.sources.deleteWarning', {
            interpolation: { escapeValue: false },
            name: toDelete.name,
          })}
          description={t('settings.sources.deleteConsequence')}
          modalState="ACTIVE"
          setModalState={(state) => state === 'INACTIVE' && setToDelete(null)}
          handleSubmit={confirmDelete}
          error={(error) =>
            error instanceof Error && error.message
              ? error.message
              : t('settings.sources.errors.delete')
          }
          handleCancel={() => setToDelete(null)}
          submitLabel={t('settings.sources.delete')}
          variant="destructive"
        />
      )}

      {toShare?.id && (
        <ShareToTeamModal
          resourceType="source"
          resourceId={toShare.id}
          resourceName={toShare.name}
          onClose={() => setToShare(null)}
        />
      )}

      <SourceConfigModal
        modalState={toConfigure ? 'ACTIVE' : 'INACTIVE'}
        setModalState={(state) => state === 'INACTIVE' && setToConfigure(null)}
        document={toConfigure}
        onReingest={(doc) => void reingest(doc)}
        hybridAvailable={hybridAvailable}
        graphRAGAvailable={graphRAGAvailable}
        availableModels={availableModels}
        decision={decision}
        onEnableGraphRAG={setToGraph}
        onSaved={(patch) => toConfigure?.id && onPatched(toConfigure.id, patch)}
        onSyncNow={() => toConfigure && void syncNow(toConfigure)}
      />

      <TestRetrievalModal
        modalState={toTest ? 'ACTIVE' : 'INACTIVE'}
        setModalState={(state) => state === 'INACTIVE' && setToTest(null)}
        document={toTest}
        hybridAvailable={hybridAvailable}
        graphRAGAvailable={graphRAGAvailable}
        availableModels={availableModels}
        decision={decision}
        // The open source and the list both show the saved config.
        onSaved={(retrieval) =>
          toTest?.id &&
          onPatched(toTest.id, { config: { ...toTest.config, retrieval } })
        }
      />

      {wikiSettingsOf && (
        <WikiSettingsModal
          document={wikiSettingsOf}
          onClose={() => setWikiSettingsOf(null)}
        />
      )}

      <ConvertToWikiModal
        modalState={toConvert ? 'ACTIVE' : 'INACTIVE'}
        setModalState={(state) => state === 'INACTIVE' && setToConvert(null)}
        document={toConvert}
        onConverted={onChanged}
      />

      <EnableGraphRAGModal
        modalState={toGraph ? 'ACTIVE' : 'INACTIVE'}
        setModalState={(state) => state === 'INACTIVE' && setToGraph(null)}
        document={toGraph}
        // The "building" badge follows SSE progress; the refresh flips the
        // source to its graph kind in the list.
        onEnabled={onChanged}
      />
    </>
  );

  return { menuOptions, openTestRetrieval, syncNow, modals };
}
