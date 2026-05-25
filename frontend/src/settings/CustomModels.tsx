import { Globe, Tag, Trash } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
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
import SkeletonLoader from '../components/SkeletonLoader';
import { Button } from '../components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '../components/ui/dropdown-menu';
import { Input } from '../components/ui/input';
import { useDarkTheme, useLoaderState } from '../hooks';
import ConfirmationModal from '../modals/ConfirmationModal';
import CustomModelModal from '../modals/CustomModelModal';
import { ActiveState } from '../models/misc';
import {
  selectToken,
  setAvailableModels,
} from '../preferences/preferenceSlice';

import type { CustomModel } from '../models/types';

type CustomModelMenuOption = {
  icon: string | LucideIcon;
  label: string;
  onClick: () => void;
  variant: 'default' | 'destructive';
  iconWidth?: number;
  iconHeight?: number;
};

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

  const getMenuOptions = (model: CustomModel): CustomModelMenuOption[] => [
    {
      icon: Edit,
      label: t('settings.customModels.actions.edit'),
      onClick: () => openEditModal(model),
      variant: 'default',
      iconWidth: 14,
      iconHeight: 14,
    },
    {
      icon: Trash,
      label: t('settings.customModels.actions.delete'),
      onClick: () => requestDelete(model),
      variant: 'destructive',
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
        <p className="text-muted-foreground mb-5 text-sm leading-6">
          {t('settings.customModels.subtitle')}
        </p>
        <div className="my-3 flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="w-full max-w-md">
            <Input
              maxLength={256}
              label={t('settings.customModels.searchPlaceholder')}
              name="custom-models-search-input"
              type="text"
              id="custom-models-search-input"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              labelBgClassName="bg-background"
              className="rounded-full"
              leftIcon={
                <img src={SearchIcon} alt="" className="h-4 w-4 opacity-40" />
              }
            />
          </div>
          <Button
            type="button"
            className="h-11 min-w-[108px] rounded-full whitespace-normal text-white"
            onClick={openAddModal}
          >
            {t('settings.customModels.addModel')}
          </Button>
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
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <button
                          type="button"
                          onClick={(e) => e.stopPropagation()}
                          className="absolute top-3 right-3 z-10 cursor-pointer"
                          aria-label={t(
                            'settings.customModels.actionsMenuAria',
                            { modelName: model.display_name },
                          )}
                        >
                          <img
                            src={ThreeDotsIcon}
                            alt={t('settings.customModels.actionsMenuAria', {
                              modelName: model.display_name,
                            })}
                            className="h-[19px] w-[19px]"
                          />
                        </button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent
                        align="end"
                        className="min-w-[144px]"
                      >
                        {getMenuOptions(model).map((option, index) => {
                          const IconCmp =
                            typeof option.icon !== 'string'
                              ? option.icon
                              : null;
                          return (
                            <DropdownMenuItem
                              key={index}
                              variant={option.variant}
                              onSelect={() => option.onClick()}
                            >
                              {typeof option.icon === 'string' ? (
                                <img
                                  src={option.icon}
                                  alt=""
                                  width={option.iconWidth ?? 16}
                                  height={option.iconHeight ?? 16}
                                />
                              ) : (
                                IconCmp && (
                                  <IconCmp
                                    size={Math.max(
                                      option.iconWidth ?? 16,
                                      option.iconHeight ?? 16,
                                    )}
                                    strokeWidth={1.75}
                                    aria-hidden="true"
                                  />
                                )
                              )}
                              <span>{option.label}</span>
                            </DropdownMenuItem>
                          );
                        })}
                      </DropdownMenuContent>
                    </DropdownMenu>
                    <div className="w-full pr-7">
                      <div className="flex items-center gap-2">
                        <p
                          title={model.display_name}
                          className="text-foreground dark:text-foreground truncate text-sm leading-snug font-semibold"
                        >
                          {model.display_name}
                        </p>
                        {!model.enabled && (
                          <span className="bg-muted-foreground/15 text-muted-foreground shrink-0 rounded-full px-2 py-0.5 text-xs leading-none font-medium">
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
