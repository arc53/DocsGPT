import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import modelService from './api/services/modelService';
import DocsGPTLogo from './assets/full-logo-b.svg';
import DocsGPTLogoWhite from './assets/full-logo-w.svg';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from './components/ui/select';
import { selectFolderWorkspaceId } from './components/folders/folderWorkspace';
import HeroSuggestions from './hero/HeroSuggestions';
import { useDarkTheme } from './hooks';
import { groupModels } from './models/modelGroups';
import {
  selectAvailableModels,
  selectSelectedModel,
  selectToken,
  setAvailableModels,
  setSelectedModel,
} from './preferences/preferenceSlice';
import { captureWorkspace } from './workspace/requestWorkspace';

import type { Model } from './models/types';

/**
 * The model picker of the empty chat. The list is the workspace's (a team
 * offers no one's own custom models): it loads again after a sign-in or a
 * switch, and an answer from before a switch is dropped.
 */
export function HeroModelSelect() {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const selectedModel = useSelector(selectSelectedModel);
  const availableModels = useSelector(selectAvailableModels);
  const token = useSelector(selectToken);
  const workspaceId = useSelector(selectFolderWorkspaceId);
  // Tracks which token and workspace the cached availableModels were loaded
  // for. Without this, the early-return below pins the anonymous/built-in
  // list forever once it's populated — login/logout never refetches
  // and a user's BYOM models stay invisible; a switch would keep the old
  // workspace's list.
  const [loadedFor, setLoadedFor] = useState<{
    token: string | null;
    workspace: string;
  } | null>(null);
  const listIsCurrent =
    loadedFor?.token === token && loadedFor?.workspace === workspaceId;

  useEffect(() => {
    const loadModels = async () => {
      if ((availableModels?.length ?? 0) > 0 && listIsCurrent) {
        return;
      }
      const workspace = captureWorkspace();
      try {
        const response = await modelService.getModels(token);
        if (!response.ok) {
          throw new Error(`API error: ${response.status}`);
        }
        const data = await response.json();
        // Switched meanwhile: the list is the old workspace's.
        if (!workspace.isCurrent()) return;
        const models = data.models || [];
        const transformed = modelService.transformModels(models);

        dispatch(setAvailableModels(transformed));
        setLoadedFor({ token, workspace: workspace.id });
        if (!selectedModel && transformed.length > 0) {
          const defaultModel =
            transformed.find((m: Model) => m.id === data.default_model_id) ||
            transformed[0];
          dispatch(setSelectedModel(defaultModel));
        } else if (selectedModel && transformed.length > 0) {
          const isValid = transformed.find(
            (m: Model) => m.id === selectedModel.id,
          );
          if (!isValid) {
            const defaultModel =
              transformed.find((m: Model) => m.id === data.default_model_id) ||
              transformed[0];
            dispatch(setSelectedModel(defaultModel));
          }
        }
      } catch (error) {
        console.error('Failed to load models:', error);
      }
    };

    loadModels();
  }, [
    availableModels?.length,
    dispatch,
    listIsCurrent,
    selectedModel,
    token,
    workspaceId,
  ]);

  const hasModels = availableModels && (availableModels?.length ?? 0) > 0;
  const groups = groupModels(availableModels ?? []);
  const builtinModels = groups.builtin;
  // Until the list is this workspace's, custom models (a person's own or a
  // team's) wait: the old list may hold Personal's in a team, or another
  // team's.
  const userModels = listIsCurrent ? groups.user : [];
  const teamModels = listIsCurrent ? groups.team : [];
  const modelItems = (models: Model[]) =>
    models.map((model) => (
      <SelectItem key={model.id} value={model.id}>
        {model.display_name}
      </SelectItem>
    ));

  return (
    <Select
      value={selectedModel?.id}
      onValueChange={(value) => {
        const model = availableModels?.find((m: Model) => m.id === value);
        if (model) dispatch(setSelectedModel(model));
      }}
      disabled={!hasModels}
    >
      <SelectTrigger
        shape="pill"
        className="w-full"
        /* Model names are product names, and a page translator rewrapping
           this text as the model list loads breaks React's next commit. */
        translate="no"
      >
        <SelectValue placeholder={t('conversation.selectModel')} />
      </SelectTrigger>
      <SelectContent capped translate="no">
        {!hasModels ? (
          <div className="text-muted-foreground px-2 py-1.5 text-sm">
            {t('agents.form.modelsPopup.noOptionsMessage')}
          </div>
        ) : userModels.length === 0 && teamModels.length === 0 ? (
          modelItems(builtinModels)
        ) : (
          // Headings only once there are custom models to tell apart.
          <>
            {builtinModels.length > 0 && (
              <SelectGroup>
                <SelectLabel>
                  {t('settings.customModels.modelsGroup.builtin')}
                </SelectLabel>
                {modelItems(builtinModels)}
              </SelectGroup>
            )}
            {teamModels.length > 0 && (
              <SelectGroup>
                <SelectLabel>
                  {t('settings.customModels.team.pickerGroup')}
                </SelectLabel>
                {modelItems(teamModels)}
              </SelectGroup>
            )}
            {userModels.length > 0 && (
              <SelectGroup>
                <SelectLabel>
                  {t('settings.customModels.modelsGroup.user')}
                </SelectLabel>
                {modelItems(userModels)}
              </SelectGroup>
            )}
          </>
        )}
      </SelectContent>
    </Select>
  );
}

export default function Hero({
  handleQuestion,
}: {
  handleQuestion: ({
    question,
    isRetry,
  }: {
    question: string;
    isRetry?: boolean;
  }) => void;
}) {
  const [isDarkTheme] = useDarkTheme();

  return (
    <div className="text-foreground flex h-full w-full flex-col items-center justify-between">
      {/* Header Section */}
      <div className="flex grow flex-col items-center justify-center pt-8 md:pt-0">
        <div className="mb-4 flex items-center">
          <img
            className="h-7 w-auto"
            src={isDarkTheme ? DocsGPTLogoWhite : DocsGPTLogo}
            alt="DocsGPT"
          />
        </div>
        {/* Model Selector */}
        <div className="relative w-72">
          <HeroModelSelect />
        </div>
      </div>

      {/* Room for the most rows there can be (four 40px rows), filled from
          the bottom, so the logo above doesn't move as rows come and go. */}
      <div
        className="mb-3 flex min-h-40 w-full max-w-full flex-col justify-end"
        data-testid="hero-suggestions-slot"
      >
        <HeroSuggestions onAsk={(question) => handleQuestion({ question })} />
      </div>
    </div>
  );
}
