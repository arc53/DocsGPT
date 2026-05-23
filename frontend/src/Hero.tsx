import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import modelService from './api/services/modelService';
import DocsGPT3 from './assets/cute_docsgpt3.svg';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from './components/ui/select';
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
        className="bg-muted dark:bg-card text-foreground hover:bg-muted dark:hover:bg-card w-full justify-between rounded-4xl border-0 px-6 py-4 text-base shadow-none data-[state=open]:rounded-b-none"
        size="lg"
      >
        <SelectValue placeholder="Select Model" />
      </SelectTrigger>
      <SelectContent className="bg-muted dark:bg-card border-0 shadow-md">
        {hasModels ? (
          availableModels?.map((model: Model) => (
            <SelectItem key={model.id} value={model.id}>
              {model.display_name}
            </SelectItem>
          ))
        ) : (
          <div className="text-muted-foreground px-3 py-2 text-sm">
            No models available
          </div>
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
  const { t } = useTranslation();
  const demos = t('demo', { returnObjects: true }) as Array<{
    header: string;
    query: string;
  }>;

  return (
    <div className="text-black-1000 dark:text-foreground flex h-full w-full flex-col items-center justify-between">
      {/* Header Section */}
      <div className="flex grow flex-col items-center justify-center pt-8 md:pt-0">
        <div className="mb-px flex items-center">
          <span className="text-4xl font-semibold">DocsGPT</span>
          <img className="mb-1 inline w-14" src={DocsGPT3} alt="docsgpt" />
        </div>
        {/* Model Selector */}
        <div className="relative w-72">
          <HeroModelSelect />
        </div>
      </div>

      {/* Demo Buttons Section */}
      <div className="mb-3 w-full max-w-full md:mb-3">
        <div className="grid grid-cols-1 gap-3 text-xs md:grid-cols-1 md:gap-4 lg:grid-cols-2">
          {demos?.map(
            (demo: { header: string; query: string }, key: number) =>
              demo.header &&
              demo.query && (
                <button
                  key={key}
                  onClick={() => handleQuestion({ question: demo.query })}
                  className={`border-border text-foreground hover:bg-muted dark:hover:bg-muted/50 bg-card w-full rounded-[66px] border px-6 py-3.5 text-left transition-colors dark:bg-transparent ${key >= 2 ? 'hidden md:block' : ''}`}
                >
                  <p className="text-black-1000 dark:text-foreground mb-2 font-semibold">
                    {demo.header}
                  </p>
                  <span className="line-clamp-2 text-gray-700 opacity-60 dark:text-gray-300">
                    {demo.query}
                  </span>
                </button>
              ),
          )}
        </div>
      </div>
    </div>
  );
}
