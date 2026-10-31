import { useEffect, useRef } from 'react';
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
import HeroSuggestions from './hero/HeroSuggestions';
import { useDarkTheme } from './hooks';
import {
  selectAvailableModels,
  selectSelectedModel,
  selectToken,
  setAvailableModels,
  setModelsLoading,
  setSelectedModel,
} from './preferences/preferenceSlice';

import type { Model } from './models/types';

function HeroModelSelect() {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const selectedModel = useSelector(selectSelectedModel);
  const availableModels = useSelector(selectAvailableModels);
  const token = useSelector(selectToken);
  // Tracks which token the cached availableModels were loaded for.
  // Without this, the early-return below pins the anonymous/built-in
  // list forever once it's populated — login/logout never refetches
  // and a user's BYOM models stay invisible.
  const lastLoadedTokenRef = useRef<string | null | undefined>(undefined);

  useEffect(() => {
    const loadModels = async () => {
      if (
        (availableModels?.length ?? 0) > 0 &&
        lastLoadedTokenRef.current === token
      ) {
        return;
      }
      dispatch(setModelsLoading(true));
      try {
        const response = await modelService.getModels(token);
        if (!response.ok) {
          throw new Error(`API error: ${response.status}`);
        }
        const data = await response.json();
        const models = data.models || [];
        const transformed = modelService.transformModels(models);

        dispatch(setAvailableModels(transformed));
        lastLoadedTokenRef.current = token;
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
      } finally {
        dispatch(setModelsLoading(false));
      }
    };

    loadModels();
  }, [availableModels?.length, dispatch, selectedModel, token]);

  const hasModels = availableModels && (availableModels?.length ?? 0) > 0;
  const builtinModels = (availableModels ?? []).filter(
    (m: Model) => m.source !== 'user',
  );
  const userModels = (availableModels ?? []).filter(
    (m: Model) => m.source === 'user',
  );
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
        ) : userModels.length === 0 ? (
          modelItems(builtinModels)
        ) : (
          // Headings only once the user has models of their own to tell apart.
          <>
            {builtinModels.length > 0 && (
              <SelectGroup>
                <SelectLabel>
                  {t('settings.customModels.modelsGroup.builtin')}
                </SelectLabel>
                {modelItems(builtinModels)}
              </SelectGroup>
            )}
            <SelectGroup>
              <SelectLabel>
                {t('settings.customModels.modelsGroup.user')}
              </SelectLabel>
              {modelItems(userModels)}
            </SelectGroup>
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

      <div className="mb-3 w-full max-w-full">
        <HeroSuggestions onAsk={(question) => handleQuestion({ question })} />
      </div>
    </div>
  );
}
