import { Globe, Tag, Trash } from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import customModelsService from '../api/services/customModelsService';
import modelService from '../api/services/modelService';
import Edit from '../assets/edit.svg';
import NoFilesDarkIcon from '../assets/no-files-dark.svg';
import NoFilesIcon from '../assets/no-files.svg';
import SearchIcon from '../assets/search.svg';
import ThreeDotsIcon from '../assets/three-dots.svg';
import ContextMenu, { MenuOption } from '../components/ContextMenu';
import SkeletonLoader from '../components/SkeletonLoader';
import { useDarkTheme, useLoaderState } from '../hooks';
import ConfirmationModal from '../modals/ConfirmationModal';
import CustomModelModal from '../modals/CustomModelModal';
import { ActiveState } from '../models/misc';
import {
  selectToken,
  setAvailableModels,
} from '../preferences/preferenceSlice';

import type { CustomModel } from '../models/types';

const formatBaseUrlHost = (baseUrl: string): string => {
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

export default function CustomModels() {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const [isDarkTheme] = useDarkTheme();

  const [models, setModels] = React.useState<CustomModel[]>([]);
  const [searchTerm, setSearchTerm] = React.useState('');
  const [loading, setLoading] = useLoaderState(false);
  const [modalState, setModalState] = React.useState<ActiveState>('INACTIVE');
  const [editingModel, setEditingModel] = React.useState<CustomModel | null>(
    null,
  );
  const [activeMenuId, setActiveMenuId] = React.useState<string | null>(null);
  const menuRefs = React.useRef<{
    [key: string]: React.RefObject<HTMLDivElement | null>;
  }>({});
  const [deleteState, setDeleteState] = React.useState<ActiveState>('INACTIVE');
  const [modelToDelete, setModelToDelete] = React.useState<CustomModel | null>(
    null,
  );

  // Ref instead of useCallback: useLoaderState returns a fresh setter
  // each render, which would loop the effect (thousands of req/s).
  const fetchModelsRef = React.useRef<() => Promise<void>>(async () => {});
  fetchModelsRef.current = async () => {
    setLoading(true);
    try {
      const data = await customModelsService.listCustomModels(token);
      setModels(data);
    } catch (err) {
      console.error('Failed to load custom models:', err);
      setModels([]);
    } finally {
      setLoading(false);
    }
  };

  React.useEffect(() => {
    fetchModelsRef.current();
  }, [token]);

  React.useEffect(() => {
    models.forEach((model) => {
      if (!menuRefs.current[model.id]) {
        menuRefs.current[model.id] = React.createRef<HTMLDivElement>();
      }
    });
  }, [models]);

  const openAddModal = () => {
    setEditingModel(null);
    setModalState('ACTIVE');
  };

  const openEditModal = (model: CustomModel) => {
    setEditingModel(model);
    setModalState('ACTIVE');
  };

  // Refresh Redux availableModels so the chat dropdown reconciles a
  // selectedModel UUID that was just deleted/disabled.
  const refreshGlobalAvailableModels = React.useCallback(async () => {
    try {
      const response = await modelService.getModels(token);
      if (!response.ok) return;
      const data = await response.json();
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

  const requestDelete = (model: CustomModel) => {
    setModelToDelete(model);
    setDeleteState('ACTIVE');
  };

  const confirmDelete = async () => {
    if (!modelToDelete) return;
    try {
      await customModelsService.deleteCustomModel(modelToDelete.id, token);
      setModels((prev) => prev.filter((m) => m.id !== modelToDelete.id));
      refreshGlobalAvailableModels();
    } catch (err) {
      console.error('Failed to delete custom model:', err);
    } finally {
      setModelToDelete(null);
      setDeleteState('INACTIVE');
    }
  };

  const getMenuOptions = (model: CustomModel): MenuOption[] => [
    {
      icon: Edit,
      label: t('settings.customModels.actions.edit'),
      onClick: () => openEditModal(model),
      variant: 'primary',
      iconWidth: 14,
      iconHeight: 14,
    },
    {
      icon: Trash,
      label: t('settings.customModels.actions.delete'),
      onClick: () => requestDelete(model),
      variant: 'danger',
      iconWidth: 16,
      iconHeight: 16,
    },
  ];

  const filteredModels = models.filter((model) => {
    const q = searchTerm.toLowerCase();
    return (
      model.display_name.toLowerCase().includes(q) ||
      model.upstream_model_id.toLowerCase().includes(q)
    );
  });

  const renderEmptyState = () => (
    <div className="flex w-full flex-col items-center justify-center py-12">
      <img
        src={isDarkTheme ? NoFilesDarkIcon : NoFilesIcon}
        alt={t('settings.customModels.empty')}
        className="mx-auto mb-6 h-32 w-32"
      />
      <p className="text-center text-lg text-gray-500 dark:text-gray-400">
        {t('settings.customModels.empty')}
      </p>
    </div>
  );

  return (
    <div className="mt-8">
      <div className="relative flex flex-col">
        <p className="text-muted-foreground mb-5 text-[15px] leading-6">
          {t('settings.customModels.subtitle')}
        </p>
        <div className="my-3 flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="relative w-full max-w-md">
            <img
              src={SearchIcon}
              alt=""
              className="absolute top-1/2 left-4 h-5 w-5 -translate-y-1/2 opacity-40"
            />
            <input
              maxLength={256}
              placeholder={t('settings.customModels.searchPlaceholder')}
              name="custom-models-search-input"
              type="text"
              id="custom-models-search-input"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="border-border bg-card text-foreground placeholder:text-muted-foreground h-11 w-full rounded-full border py-2 pr-5 pl-11 text-sm shadow-[0_1px_4px_rgba(0,0,0,0.06)] transition-shadow outline-none focus:shadow-[0_2px_8px_rgba(0,0,0,0.1)] dark:shadow-none"
            />
          </div>
          <button
            className="bg-primary hover:bg-primary/90 flex h-11 min-w-[108px] items-center justify-center rounded-full px-4 text-sm whitespace-normal text-white"
            onClick={openAddModal}
          >
            {t('settings.customModels.addModel')}
          </button>
        </div>
        <div className="border-border dark:border-border mt-5 mb-8 border-b" />
        {loading ? (
          <div className="flex flex-wrap justify-center gap-4 sm:justify-start">
            <SkeletonLoader component="toolCards" count={3} />
          </div>
        ) : (
          <div className="flex flex-wrap justify-center gap-4 sm:justify-start">
            {filteredModels.length === 0
              ? renderEmptyState()
              : filteredModels.map((model) => (
                  <div
                    key={model.id}
                    className="bg-muted hover:bg-accent relative flex w-[300px] flex-col overflow-hidden rounded-2xl p-5"
                  >
                    <div
                      ref={menuRefs.current[model.id]}
                      onClick={(e) => {
                        e.stopPropagation();
                        setActiveMenuId(
                          activeMenuId === model.id ? null : model.id,
                        );
                      }}
                      className="absolute top-3 right-3 z-10 cursor-pointer"
                    >
                      <img
                        src={ThreeDotsIcon}
                        alt={t('settings.customModels.actionsMenuAria', {
                          modelName: model.display_name,
                        })}
                        className="h-[19px] w-[19px]"
                      />
                      <ContextMenu
                        isOpen={activeMenuId === model.id}
                        setIsOpen={(isOpen) => {
                          setActiveMenuId(isOpen ? model.id : null);
                        }}
                        options={getMenuOptions(model)}
                        anchorRef={menuRefs.current[model.id]}
                        position="bottom-right"
                        offset={{ x: 0, y: 0 }}
                      />
                    </div>
                    <div className="w-full pr-7">
                      <div className="flex items-center gap-2">
                        <p
                          title={model.display_name}
                          className="text-foreground dark:text-foreground truncate text-[15px] leading-snug font-semibold"
                        >
                          {model.display_name}
                        </p>
                        {!model.enabled && (
                          <span className="bg-muted-foreground/15 text-muted-foreground shrink-0 rounded-full px-2 py-0.5 text-[10px] leading-none font-medium">
                            {t('settings.customModels.disabledBadge')}
                          </span>
                        )}
                      </div>
                      <div className="mt-3 space-y-1.5">
                        <div
                          className="text-muted-foreground/80 flex items-center gap-1.5 text-xs leading-relaxed"
                          title={model.upstream_model_id}
                        >
                          <Tag className="h-3.5 w-3.5 shrink-0 opacity-70" />
                          <span className="truncate">
                            {model.upstream_model_id}
                          </span>
                        </div>
                        <div
                          className="text-muted-foreground/80 flex items-center gap-1.5 text-xs leading-relaxed"
                          title={model.base_url}
                        >
                          <Globe className="h-3.5 w-3.5 shrink-0 opacity-70" />
                          <span className="truncate">
                            {formatBaseUrlHost(model.base_url)}
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
          </div>
        )}
      </div>
      <CustomModelModal
        modalState={modalState}
        setModalState={setModalState}
        model={editingModel}
        onSaved={handleSaved}
      />
      <ConfirmationModal
        message={t('settings.customModels.deleteWarning', {
          modelName: modelToDelete?.display_name || '',
        })}
        modalState={deleteState}
        setModalState={setDeleteState}
        handleSubmit={confirmDelete}
        submitLabel={t('settings.customModels.actions.delete')}
        variant="danger"
      />
    </div>
  );
}
