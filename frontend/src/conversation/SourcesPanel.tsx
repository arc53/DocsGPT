import { ExternalLink } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Card } from '../components/ui/card';
import { PanelBody, PanelHeader } from '../components/ui/side-panel';
import ConnectorIcon from '../connectors/ConnectorIcon';
import { connectorIconKey } from '../connectors/i18n';
import type { AnswerSource } from './chatCompanion';

/**
 * An answer's full source list, as side panel content: docked in the chat's
 * slot, or in a modal SidePanel where there is none. Each source is a
 * `filled` tile; one with a web link opens it in a new tab.
 */
export default function SourcesPanel({ sources }: { sources: AnswerSource[] }) {
  const { t } = useTranslation();

  return (
    <>
      <PanelHeader
        title={t('conversation.sources.title')}
        description={t('conversation.sources.forAnswer', {
          count: sources.length,
        })}
      />
      <PanelBody>
        <ul className="flex flex-col gap-2">
          {sources.map((source, index) => (
            <li key={index}>
              <SourceTile source={source} position={index + 1} />
            </li>
          ))}
        </ul>
      </PanelBody>
    </>
  );
}

function SourceTile({
  source,
  position,
}: {
  source: AnswerSource;
  position: number;
}) {
  const { t } = useTranslation();
  const external = !!source.link && source.link !== 'local';

  const body = (
    <>
      <span className="text-foreground line-clamp-3 text-sm font-semibold wrap-break-word">
        {`${position}. ${source.title}`}
        {external ? (
          <ExternalLink
            className="text-muted-foreground ml-1 inline size-3"
            aria-hidden="true"
          />
        ) : null}
      </span>
      {source.connector_name ? (
        <span className="text-muted-foreground flex items-center gap-1.5 text-xs">
          <ConnectorIcon
            icon={connectorIconKey(source.connector_key)}
            className="size-3.5 shrink-0"
          />
          <span className="truncate">
            {t('conversation.sources.fromConnector', {
              name: source.connector_name,
              interpolation: { escapeValue: false },
            })}
          </span>
        </span>
      ) : null}
      <span className="text-foreground line-clamp-4 text-xs wrap-break-word">
        {source.text}
      </span>
    </>
  );

  if (external) {
    return (
      <Card variant="filled" interactive asChild className="gap-2">
        <a
          href={source.link}
          target="_blank"
          rel="noopener noreferrer"
          title={source.title}
        >
          {body}
        </a>
      </Card>
    );
  }
  return (
    <Card variant="filled" className="gap-2" title={source.title}>
      {body}
    </Card>
  );
}
