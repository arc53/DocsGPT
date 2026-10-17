import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useDispatch, useSelector } from 'react-redux';

import modelService from './api/services/modelService';
import DocsGPTLogo from './assets/full-logo-b.svg';
import DocsGPTLogoWhite from './assets/full-logo-w.svg';
import { Button } from './components/ui/button';
import { cn } from './lib/utils';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from './components/ui/select';
import {
  selectConnections,
  selectConnectorCatalog,
  selectConnectorsEnabled,
  selectConnectorsLoaded,
} from './connectors/connectorsSlice';
import { catalogCards } from './connectors/catalogCards';
import { connectorName } from './connectors/i18n';
import type { ConnectorDefinition } from './connectors/types';
import { useDarkTheme } from './hooks';
import {
  selectAvailableModels,
  selectSelectedModel,
  selectToken,
  setAvailableModels,
  setModelsLoading,
  setSelectedModel,
} from './preferences/preferenceSlice';
import { intlLocale } from './utils/dateTimeUtils';

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
  const { t, i18n } = useTranslation();
  const [isDarkTheme] = useDarkTheme();
  const navigate = useNavigate();
  const demos = t('demo', { returnObjects: true }) as Array<{
    header: string;
    query: string;
  }>;
  // Nothing connected yet: the last card offers connecting a service, named
  // after what this install can actually connect.
  const connectorsEnabled = useSelector(selectConnectorsEnabled);
  const connectorsLoaded = useSelector(selectConnectorsLoaded);
  const connections = useSelector(selectConnections);
  const catalog = useSelector(selectConnectorCatalog);
  const connectable = catalog.filter(
    (connector) => connector.available && connector.publisher !== 'custom',
  );
  const offerConnect =
    connectorsEnabled &&
    connectorsLoaded &&
    connections.length === 0 &&
    connectable.length > 0;
  // Named after services whose data you chat with (files, docs, issues),
  // not a web search or a bot that sends messages; one card per service.
  const holdsData = (connector: ConnectorDefinition) =>
    connector.category !== 'search' &&
    (connector.capabilities ?? []).some((c) => c === 'sync' || c === 'read');
  const dataServices = catalogCards(connectable).filter(holdsData);
  const named = (dataServices.length > 0 ? dataServices : connectable).map(
    (connector) => connectorName(t, connector),
  );
  const NAMED = 2;
  const connectNames = new Intl.ListFormat(intlLocale(i18n.language), {
    type: 'conjunction',
  }).format(
    named.length > NAMED
      ? [...named.slice(0, NAMED), t('connectHero.more')]
      : named,
  );
  const cards = (demos ?? []).filter((demo) => demo.header && demo.query);
  const shown = offerConnect ? cards.slice(0, 3) : cards;

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

      {/* Demo Buttons Section */}
      <div className="mb-3 w-full max-w-full md:mb-3">
        <div className="grid grid-cols-1 gap-3 text-xs md:grid-cols-1 md:gap-4 lg:grid-cols-2">
          {shown.map(
            (demo: { header: string; query: string }, key: number) =>
              demo.header &&
              demo.query && (
                <Button
                  key={key}
                  type="button"
                  variant="outline"
                  size="lg"
                  shape="pill"
                  onClick={() => handleQuestion({ question: demo.query })}
                  className={cn(
                    /* eslint-disable-next-line shadcn/no-restyle --
                       The demo card is a two-line pill (title over a clamped
                       query at 12px), so it undoes lg's one-line height, the
                       base's row layout, weight and nowrap. */
                    'h-auto w-full flex-col items-start gap-0 py-3.5 text-left text-xs font-normal whitespace-normal',
                    key >= 2 && 'hidden md:flex',
                  )}
                >
                  <p className="text-foreground mb-2 font-semibold">
                    {demo.header}
                  </p>
                  <span className="text-muted-foreground line-clamp-2">
                    {demo.query}
                  </span>
                </Button>
              ),
          )}
          {offerConnect && (
            <Button
              type="button"
              variant="outline"
              size="lg"
              shape="pill"
              onClick={() => navigate('/settings/connectors')}
              data-testid="hero-connect-card"
              className={cn(
                /* eslint-disable-next-line shadcn/no-restyle --
                   Same two-line pill as the demo cards above. */
                'hidden h-auto w-full flex-col items-start gap-0 py-3.5 text-left text-xs font-normal whitespace-normal md:flex',
              )}
            >
              <p className="text-foreground mb-2 font-semibold">
                {t('connectHero.title')}
              </p>
              <span className="text-muted-foreground line-clamp-2">
                {t('connectHero.body', {
                  names: connectNames,
                  interpolation: { escapeValue: false },
                })}
              </span>
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
