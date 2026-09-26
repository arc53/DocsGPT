import { Globe, Pencil, Tag, Trash2 } from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import customModelsService from '../api/services/customModelsService';
import modelService from '../api/services/modelService';
import PageToolbar from '../components/PageToolbar';
import SearchInput from '../components/SearchInput';
import SkeletonLoader from '../components/SkeletonLoader';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card, CardFooter, CardTitle } from '../components/ui/card';
import { ActionMenu, type MenuOption } from '../components/ui/dropdown-menu';
import { EmptyState } from '../components/ui/empty-state';
import { useLoaderState } from '../hooks';
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

  const getMenuOptions = (model: CustomModel): MenuOption[] => [
    {
      icon: Pencil,
      label: t('settings.customModels.actions.edit'),
      onClick: () => openEditModal(model),
      variant: 'default',
    },
    {
      icon: Trash2,
      label: t('settings.customModels.actions.delete'),
      onClick: () => requestDelete(model),
      variant: 'destructive',
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
    <EmptyState title={t('settings.customModels.empty')} />
  );

  return (
    <div>
      <div className="relative flex flex-col">
        <PageToolbar
          intro={t('settings.customModels.subtitle')}
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
            <Button
              type="button"
              size="field"
              shape="pill"
              onClick={openAddModal}
            >
              {t('settings.customModels.addModel')}
            </Button>
          }
          divider
        />
        {loading ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            <SkeletonLoader component="toolCards" count={3} />
          </div>
        ) : filteredModels.length === 0 ? (
          renderEmptyState()
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {filteredModels.map((model) => (
              <Card
                key={model.id}
                variant="filled"
                padding="lg"
                className="relative overflow-hidden"
              >
                <ActionMenu
                  options={getMenuOptions(model)}
                  triggerLabel={t('settings.customModels.actionsMenuAria', {
                    modelName: model.display_name,
                  })}
                  className="absolute top-3 right-3 z-10"
                />
                <div className="w-full pr-7">
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
                <CardFooter className="flex-col items-stretch gap-1.5 pr-7">
                  <div
                    className="flex items-center gap-1.5 leading-relaxed"
                    title={model.upstream_model_id}
                  >
                    <Tag className="size-3.5 shrink-0 opacity-70" />
                    <span className="truncate">{model.upstream_model_id}</span>
                  </div>
                  <div
                    className="flex items-center gap-1.5 leading-relaxed"
                    title={model.base_url}
                  >
                    <Globe className="size-3.5 shrink-0 opacity-70" />
                    <span className="truncate">
                      {formatBaseUrlHost(model.base_url)}
                    </span>
                  </div>
                </CardFooter>
              </Card>
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
        variant="destructive"
      />
    </div>
  );
}
