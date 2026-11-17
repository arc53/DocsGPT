import {
  Copy,
  Globe,
  Pencil,
  Power,
  PowerOff,
  Tag,
  Trash2,
  UserRound,
} from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import customModelsService from '../api/services/customModelsService';
import modelService from '../api/services/modelService';
import PageToolbar from '../components/PageToolbar';
import { Pagination, pageRangeParams } from '../components/ui/pagination';
import { SHORT_LIST_PAGE_SIZE, useClientPage } from '../hooks/usePageState';
import SearchInput from '../components/SearchInput';
import SkeletonLoader from '../components/SkeletonLoader';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card, CardFooter, CardTitle } from '../components/ui/card';
import { ActionMenu, type MenuOption } from '../components/ui/dropdown-menu';
import { EmptyState } from '../components/ui/empty-state';
import { useLoaderState } from '../hooks';
import { cn } from '../lib/utils';
import ConfirmationModal from '../modals/ConfirmationModal';
import CustomModelModal from '../modals/CustomModelModal';
import { customModelRequestError } from '../models/customModelErrors';
import { ActiveState } from '../models/misc';
import { addedByText, isTeamModel, modelCan } from '../models/teamModels';
import { showActionToast } from '../notifications/actionToastSlice';
import {
  selectToken,
  setAvailableModels,
} from '../preferences/preferenceSlice';
import { readerIdFromToken } from '../utils/personLabel';
import { captureWorkspace } from '../workspace/requestWorkspace';
import {
  roleAtLeast,
  selectWorkspaceRoleOrNull,
} from '../workspace/workspaceSlice';

import type { CustomModel, CustomModelUsage } from '../models/types';
import CopyModelToTeamModal, { useCopyTargets } from './CopyModelToTeamModal';
import { selectInTeam } from './workspaceAccess';

const noEscape = { interpolation: { escapeValue: false } };

const formatBaseUrlHost = (baseUrl: string | undefined): string => {
  if (!baseUrl) return '';
  try {
    const url = new URL(baseUrl);
    return url.host || url.hostname || baseUrl;
  } catch {
    const stripped = baseUrl.replace(/^https?:\/\//i, '');
    const slashIdx = stripped.indexOf('/');
    return slashIdx >= 0 ? stripped.slice(0, slashIdx) : stripped;
  }
};

/** The names of the agents and workflows in a model's usage, in one line. */
const usageNames = (usage: CustomModelUsage | null | undefined): string =>
  usage
    ? [...usage.agents, ...usage.workflows].map((item) => item.name).join(', ')
    : '';

/**
 * Settings › Custom models: the caller's own models in Personal; in a team,
 * the team's. Every member sees the team's models and who added each; only
 * Admins and the Owner add, edit, test, switch off and delete them, and only
 * they see a model's base URL.
 */
export default function CustomModels() {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const inTeam = useSelector(selectInTeam);
  const teamId = useSelector(
    (state: { workspace?: { current: string } }) =>
      state.workspace?.current ?? '',
  );
  const role = useSelector(selectWorkspaceRoleOrNull);
  // Adding a model for the team is an Admin's.
  const canAdd = !inTeam || roleAtLeast(role, 'admin');
  const me = readerIdFromToken(token);
  // Copying one's own model into a team needs Admin there.
  const copyTeams = useCopyTargets();

  const [models, setModels] = React.useState<CustomModel[]>([]);
  const [searchTerm, setSearchTerm] = React.useState('');
  const [loading, setLoading] = useLoaderState(false);
  // The load failed: an error with Retry, not "no models yet".
  const [loadFailed, setLoadFailed] = React.useState(false);
  const [modalState, setModalState] = React.useState<ActiveState>('INACTIVE');
  const [editingModel, setEditingModel] = React.useState<CustomModel | null>(
    null,
  );
  const [deleteState, setDeleteState] = React.useState<ActiveState>('INACTIVE');
  const [modelToDelete, setModelToDelete] = React.useState<CustomModel | null>(
    null,
  );
  // What the model being deleted is used by: read when the confirm opens,
  // null until it answers (or when it fails).
  const [deleteUsage, setDeleteUsage] = React.useState<{
    id: string;
    usage: CustomModelUsage;
  } | null>(null);
  const [modelToCopy, setModelToCopy] = React.useState<CustomModel | null>(
    null,
  );
  // Only the latest load's answer is applied (a workspace switch mid-load).
  const loadSeq = React.useRef(0);

  // Ref instead of useCallback: useLoaderState returns a fresh setter
  // each render, which would loop the effect (thousands of req/s).
  const fetchModelsRef = React.useRef<() => Promise<void>>(async () => {});
  fetchModelsRef.current = async () => {
    const seq = ++loadSeq.current;
    setLoading(true);
    try {
      const data = inTeam
        ? await customModelsService.listCustomModels(token, {
            owner: 'team',
            workspace: teamId,
          })
        : await customModelsService.listCustomModels(token);
      if (seq !== loadSeq.current) return;
      setModels(data);
      setLoadFailed(false);
    } catch (err) {
      if (seq !== loadSeq.current) return;
      console.error('Failed to load custom models:', err);
      setLoadFailed(true);
    } finally {
      if (seq === loadSeq.current) setLoading(false);
    }
  };

  React.useEffect(() => {
    setModels([]);
    fetchModelsRef.current();
  }, [token, inTeam, teamId]);

  const openAddModal = () => {
    setEditingModel(null);
    setModalState('ACTIVE');
  };

  const openEditModal = (model: CustomModel) => {
    setEditingModel(model);
    setModalState('ACTIVE');
  };

  // Refresh Redux availableModels so the chat dropdown reconciles a
  // selectedModel UUID that was just deleted/disabled. A list answering
  // after a switch is the old workspace's, and the picker would take it as
  // the new one's.
  const refreshGlobalAvailableModels = React.useCallback(async () => {
    const workspace = captureWorkspace();
    try {
      const response = await modelService.getModels(token);
      if (!response.ok || !workspace.isCurrent()) return;
      const data = await response.json();
      if (!workspace.isCurrent()) return;
      const transformed = modelService.transformModels(data.models || []);
      dispatch(setAvailableModels(transformed));
    } catch (err) {
      console.error('Failed to refresh global available models:', err);
    }
  }, [dispatch, token]);

  const handleSaved = (saved: CustomModel) => {
    setModels((prev) => {
      const idx = prev.findIndex((m) => m.id === saved.id);
      if (idx === -1) return [saved, ...prev];
      const next = [...prev];
      next[idx] = saved;
      return next;
    });
    refreshGlobalAvailableModels();
  };

  // Switches a model on or off at once; a refusal says why in a toast.
  const toggleEnabled = async (model: CustomModel) => {
    try {
      const saved = await customModelsService.updateCustomModel(
        model.id,
        { enabled: !model.enabled },
        token,
      );
      handleSaved(saved);
    } catch (err) {
      dispatch(
        showActionToast({
          variant: 'destructive',
          message: customModelRequestError(
            t,
            err,
            t('settings.customModels.errors.saveFailed'),
          ),
        }),
      );
    }
  };

  const requestDelete = (model: CustomModel) => {
    setModelToDelete(model);
    setDeleteUsage(null);
    setDeleteState('ACTIVE');
    // The confirm names what falls back to the default model; a failed read
    // leaves the general warning.
    customModelsService
      .getCustomModelUsage(model.id, token)
      .then((usage) => setDeleteUsage({ id: model.id, usage }))
      .catch((err) => console.error('Failed to read model usage:', err));
  };

  const knownUsage =
    modelToDelete && deleteUsage?.id === modelToDelete.id
      ? deleteUsage.usage
      : null;

  /** The confirm's consequence: what runs on the default model instead. */
  const deleteDescription = (): string => {
    const names = usageNames(knownUsage);
    if (names)
      return t('settings.customModels.team.delete.usedBy', {
        names,
        ...noEscape,
      });
    if (!knownUsage && isTeamModel(modelToDelete))
      return t('settings.customModels.team.delete.mayBeUsed');
    return t('common.cantUndo');
  };

  // Returns the request: ConfirmationModal closes on success and keeps a
  // failure open with its error.
  const confirmDelete = async () => {
    if (!modelToDelete) return;
    const id = modelToDelete.id;
    const named = !!knownUsage;
    const result = await customModelsService.deleteCustomModel(id, token);
    setModels((prev) => prev.filter((m) => m.id !== id));
    setModelToDelete(null);
    refreshGlobalAvailableModels();
    // The confirm couldn't say what fell back: say it now.
    const names = usageNames(result?.usage);
    if (!named && names)
      dispatch(
        showActionToast({
          variant: 'info',
          message: t('settings.customModels.team.delete.fellBack', {
            names,
            ...noEscape,
          }),
        }),
      );
  };

  // A role that may not manage a model gets no ⋯ at all.
  const getMenuOptions = (model: CustomModel): MenuOption[] => {
    if (!modelCan(model, 'manage')) return [];
    const options: MenuOption[] = [
      {
        icon: Pencil,
        label: t('settings.customModels.actions.edit'),
        onClick: () => openEditModal(model),
        variant: 'default',
      },
      {
        icon: model.enabled ? PowerOff : Power,
        label: t(
          model.enabled
            ? 'settings.customModels.team.actions.disable'
            : 'settings.customModels.team.actions.enable',
        ),
        onClick: () => toggleEnabled(model),
        variant: 'default',
      },
    ];
    if (!isTeamModel(model) && copyTeams.length > 0)
      options.push({
        icon: Copy,
        label: t('settings.customModels.team.copy.action'),
        onClick: () => setModelToCopy(model),
        variant: 'default',
      });
    options.push({
      icon: Trash2,
      label: t('settings.customModels.actions.delete'),
      onClick: () => requestDelete(model),
      variant: 'destructive',
      separatorBefore: true,
    });
    return options;
  };

  const filteredModels = models.filter((model) => {
    const q = searchTerm.toLowerCase();
    return (
      model.display_name.toLowerCase().includes(q) ||
      model.upstream_model_id.toLowerCase().includes(q)
    );
  });

  const {
    page: modelsPage,
    setPage: setModelsPage,
    pageItems: pageModels,
  } = useClientPage(filteredModels, SHORT_LIST_PAGE_SIZE, searchTerm);

  const renderEmptyState = () =>
    inTeam && models.length === 0 && !searchTerm ? (
      <EmptyState
        title={t(
          canAdd
            ? 'settings.customModels.team.emptyAdmin'
            : 'settings.customModels.team.emptyMember',
        )}
      />
    ) : (
      <EmptyState title={t('settings.customModels.empty')} />
    );

  return (
    <div>
      <div className="relative flex flex-col">
        <PageToolbar
          intro={
            inTeam
              ? t('settings.customModels.team.notice')
              : t('settings.customModels.subtitle')
          }
          search={
            <SearchInput
              maxLength={256}
              label={t('settings.customModels.searchPlaceholder')}
              name="custom-models-search-input"
              id="custom-models-search-input"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          }
          action={
            canAdd ? (
              <Button
                type="button"
                size="field"
                shape="pill"
                onClick={openAddModal}
              >
                {t('settings.customModels.addModel')}
              </Button>
            ) : undefined
          }
          divider
        />
        {loading ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            <SkeletonLoader component="toolCards" count={3} />
          </div>
        ) : loadFailed ? (
          <EmptyState
            tone="destructive"
            illustration="none"
            title={t('settings.customModels.loadError')}
            onRetry={() => fetchModelsRef.current()}
          />
        ) : filteredModels.length === 0 ? (
          renderEmptyState()
        ) : (
          <>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {pageModels.map((model) => {
                const options = getMenuOptions(model);
                const hasMenu = options.length > 0;
                const addedBy = addedByText(t, model, me);
                const showBaseUrl =
                  modelCan(model, 'manage') && !!model.base_url;
                return (
                  <Card
                    key={model.id}
                    variant="filled"
                    padding="lg"
                    className="relative overflow-hidden"
                  >
                    {hasMenu ? (
                      <ActionMenu
                        options={options}
                        triggerLabel={t(
                          'settings.customModels.actionsMenuAria',
                          { modelName: model.display_name, ...noEscape },
                        )}
                        className="absolute top-3 right-3 z-10"
                      />
                    ) : null}
                    <div className={cn('w-full', hasMenu && 'pr-7')}>
                      <div className="flex items-center gap-2">
                        <CardTitle
                          as="h2"
                          title={model.display_name}
                          className="min-w-0 truncate"
                        >
                          {model.display_name}
                        </CardTitle>
                        {!model.enabled && (
                          <Badge variant="neutral">
                            {t('settings.customModels.disabledBadge')}
                          </Badge>
                        )}
                      </div>
                    </div>
                    <CardFooter
                      className={cn(
                        'flex-col items-stretch gap-1.5',
                        hasMenu && 'pr-7',
                      )}
                    >
                      <div
                        className="flex items-center gap-1.5 leading-relaxed"
                        title={model.upstream_model_id}
                      >
                        <Tag className="size-3.5 shrink-0 opacity-70" />
                        <span className="truncate">
                          {model.upstream_model_id}
                        </span>
                      </div>
                      {showBaseUrl ? (
                        <div
                          className="flex items-center gap-1.5 leading-relaxed"
                          title={model.base_url}
                        >
                          <Globe className="size-3.5 shrink-0 opacity-70" />
                          <span className="truncate">
                            {formatBaseUrlHost(model.base_url)}
                          </span>
                        </div>
                      ) : null}
                      {addedBy ? (
                        <div
                          className="flex items-center gap-1.5 leading-relaxed"
                          title={addedBy}
                        >
                          <UserRound className="size-3.5 shrink-0 opacity-70" />
                          <span className="truncate">{addedBy}</span>
                        </div>
                      ) : null}
                    </CardFooter>
                  </Card>
                );
              })}
            </div>
            <Pagination
              page={modelsPage}
              pageSize={SHORT_LIST_PAGE_SIZE}
              total={filteredModels.length}
              onPageChange={setModelsPage}
              rangeLabel={(range) =>
                t('settings.customModels.pageRange', pageRangeParams(range))
              }
            />
          </>
        )}
      </div>
      <CustomModelModal
        modalState={modalState}
        setModalState={setModalState}
        model={editingModel}
        onSaved={handleSaved}
        owner={inTeam ? 'team' : undefined}
      />
      <ConfirmationModal
        message={t('settings.customModels.deleteWarning', {
          interpolation: { escapeValue: false },
          modelName: modelToDelete?.display_name || '',
        })}
        description={deleteDescription()}
        modalState={deleteState}
        setModalState={setDeleteState}
        handleSubmit={confirmDelete}
        submitLabel={t('settings.customModels.actions.delete')}
        variant="destructive"
        error={(reason) =>
          customModelRequestError(t, reason, t('common.actionFailed'))
        }
      />
      <CopyModelToTeamModal
        model={modelToCopy}
        teams={copyTeams}
        onClose={() => setModelToCopy(null)}
      />
    </div>
  );
}
