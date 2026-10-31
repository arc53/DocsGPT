import {
  ArrowUp,
  Bot,
  ChevronRight,
  FileText,
  Files,
  History,
  Plug,
  Upload as UploadIcon,
} from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import AgentTypeModal from '../agents/components/AgentTypeModal';
import { ListRow } from '../components/ui/list-row';
import { cn } from '../lib/utils';
import { catalogCards } from '../connectors/catalogCards';
import ConnectorIcon from '../connectors/ConnectorIcon';
import {
  selectConnections,
  selectConnectorCatalog,
  selectConnectorsEnabled,
  selectConnectorsFailed,
  selectConnectorsLoaded,
} from '../connectors/connectorsSlice';
import { connectorName } from '../connectors/i18n';
import {
  selectChatTools,
  selectChatToolsLoaded,
} from '../conversation/chatToolsSlice';
import {
  selectAgents,
  selectConversations,
  selectSelectedDocs,
  selectSourceDocs,
} from '../preferences/preferenceSlice';
import type { ActiveState } from '../models/misc';
import Upload from '../upload/Upload';
import { intlLocale } from '../utils/dateTimeUtils';
import {
  answerableServices,
  buildHeroSuggestions,
  holdsData,
  type HeroSuggestion,
} from './suggestions';

const SERVICE_TEMPLATES = new Set([
  'files',
  'knowledge',
  'projects',
  'dev',
  'business',
  'messaging',
  'database',
]);
/** How many services the Connect row names before "and more". */
const NAMED_SERVICES = 2;

const iconClass = 'text-muted-foreground size-4 shrink-0';

/**
 * The empty chat's suggestions: questions about what the user has (the
 * selected sources, connected services), their latest chat, and setup steps
 * not done yet. Nothing shows until every list it reads has loaded, so a
 * returning user never sees a fresh install's rows first.
 */
export default function HeroSuggestions({
  onAsk,
}: {
  /** Sends a suggested question. */
  onAsk: (question: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [uploadState, setUploadState] = useState<ActiveState>('INACTIVE');
  const [agentTypeOpen, setAgentTypeOpen] = useState(false);

  const selectedDocs = useSelector(selectSelectedDocs);
  const sourceDocs = useSelector(selectSourceDocs);
  const conversations = useSelector(selectConversations);
  const agents = useSelector(selectAgents);
  const tools = useSelector(selectChatTools);
  const toolsLoaded = useSelector(selectChatToolsLoaded);
  const connectorsEnabled = useSelector(selectConnectorsEnabled);
  const connectorsLoaded = useSelector(selectConnectorsLoaded);
  const connectorsFailed = useSelector(selectConnectorsFailed);
  const connections = useSelector(selectConnections);
  const catalog = useSelector(selectConnectorCatalog);

  const connectorsSettled =
    !connectorsEnabled || connectorsLoaded || connectorsFailed;
  const ready =
    sourceDocs !== null &&
    conversations.data !== null &&
    toolsLoaded &&
    connectorsSettled;

  // Offer connecting a service only while nothing is connected, named
  // after services whose data you chat with (files, docs, issues).
  const connectable = connectorsEnabled
    ? catalog.filter((c) => c.available && c.publisher !== 'custom')
    : [];
  const offerConnect =
    connectorsLoaded && connections.length === 0 && connectable.length > 0;
  const dataServices = catalogCards(connectable).filter(holdsData);
  const named = (dataServices.length > 0 ? dataServices : connectable).map(
    (connector) => connectorName(t, connector),
  );
  const connectNames = new Intl.ListFormat(intlLocale(i18n.language), {
    type: 'conjunction',
  }).format(
    named.length > NAMED_SERVICES
      ? [...named.slice(0, NAMED_SERVICES), t('hero.suggestions.more')]
      : named,
  );

  const rows = ready
    ? buildHeroSuggestions({
        selectedSources: selectedDocs,
        hasSources: (sourceDocs?.length ?? 0) > 0,
        services: connectorsEnabled
          ? answerableServices({
              catalog,
              connections,
              tools,
              nameOf: (connector) => connectorName(t, connector),
            })
          : [],
        conversations: conversations.data ?? [],
        // The agent list loads with the sidebar; until it has, don't offer
        // creating one.
        hasAgents: agents === null || agents.length > 0,
        offerConnect,
        now: Date.now(),
      })
    : [];

  const names = { interpolation: { escapeValue: false } };
  const row = (
    suggestion: HeroSuggestion,
  ): {
    key: string;
    icon: ReactNode;
    text: string;
    /** Sends `text`; otherwise the row opens something. */
    asks: boolean;
    open?: () => void;
  } => {
    switch (suggestion.kind) {
      case 'summarize':
        return {
          key: `summarize-${suggestion.source.id}`,
          icon: <FileText className={iconClass} />,
          text: t('hero.suggestions.summarize', {
            name: suggestion.source.name,
            ...names,
          }),
          asks: true,
        };
      case 'compare':
        return {
          key: 'compare',
          icon: <Files className={iconClass} />,
          text: t('hero.suggestions.compare', {
            first: suggestion.first.name,
            second: suggestion.second.name,
            ...names,
          }),
          asks: true,
        };
      case 'service': {
        const { service } = suggestion;
        const template = SERVICE_TEMPLATES.has(service.category)
          ? service.category
          : 'other';
        return {
          key: `service-${service.key}`,
          icon: <ConnectorIcon icon={service.icon} className={iconClass} />,
          text: t(`hero.suggestions.service.${template}`, {
            name: service.name,
            ...names,
          }),
          asks: true,
        };
      }
      case 'continue':
        return {
          key: `continue-${suggestion.chat.id}`,
          icon: <History className={iconClass} />,
          text: t('hero.suggestions.continue', {
            name: suggestion.chat.name,
            ...names,
          }),
          asks: false,
          open: () => navigate(`/c/${suggestion.chat.id}`),
        };
      case 'addKnowledge':
        return {
          key: 'add-knowledge',
          icon: <UploadIcon className={iconClass} />,
          text: t('hero.suggestions.addKnowledge'),
          asks: false,
          open: () => setUploadState('ACTIVE'),
        };
      case 'connect':
        return {
          key: 'connect',
          icon: <Plug className={iconClass} />,
          text: t('hero.suggestions.connect', {
            names: connectNames,
            ...names,
          }),
          asks: false,
          open: () => navigate('/settings/connectors'),
        };
      case 'createAgent':
        return {
          key: 'create-agent',
          icon: <Bot className={iconClass} />,
          text: t('hero.suggestions.createAgent'),
          asks: false,
          open: () => setAgentTypeOpen(true),
        };
    }
  };

  return (
    <>
      {rows.length > 0 && (
        <ul
          aria-label={t('hero.suggestions.label')}
          className="flex flex-col"
          data-testid="hero-suggestions"
        >
          {rows.map(row).map(({ key, icon, text, asks, open }) => (
            <ListRow
              key={key}
              size="md"
              interactive
              asChild
              className="group/row"
              leading={icon}
              title={text}
              trailing={
                asks ? (
                  <ArrowUp
                    className={cn(
                      iconClass,
                      'opacity-0 transition-opacity group-focus-within/row:opacity-100 group-hover/row:opacity-100',
                    )}
                  />
                ) : (
                  <ChevronRight className={iconClass} />
                )
              }
            >
              <button
                type="button"
                data-suggestion={key}
                onClick={asks ? () => onAsk(text) : open}
              />
            </ListRow>
          ))}
        </ul>
      )}
      {uploadState === 'ACTIVE' && (
        <Upload
          receivedFile={[]}
          setModalState={setUploadState}
          isOnboarding={false}
          renderTab={null}
          close={() => setUploadState('INACTIVE')}
          onBrowseConnectors={() =>
            navigate('/settings/connectors?capability=sync')
          }
        />
      )}
      <AgentTypeModal
        isOpen={agentTypeOpen}
        onClose={() => setAgentTypeOpen(false)}
      />
    </>
  );
}
