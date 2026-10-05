import { useTranslation } from 'react-i18next';

import { Card } from '../components/ui/card';
import { PanelBody, PanelHeader } from '../components/ui/side-panel';
import ConnectorIcon from '../connectors/ConnectorIcon';
import { connectorIconKey } from '../connectors/i18n';
import type { AnswerSource } from './chatCompanion';
import CitationReader from './CitationReader';

/**
 * An answer's sources, as side panel content: docked in the chat's slot, or
 * in a modal SidePanel where there is none. The first level lists every
 * source as a `filled` tile; opening one shows its passage as the second
 * level (`CitationReader`), with a Back arrow to the list. The open source is
 * the caller's state, so a citation in the answer can open it directly.
 */
export default function SourcesPanel({
  sources,
  openIndex = null,
  onOpenIndexChange,
}: {
  sources: AnswerSource[];
  /** The source whose reader is showing, or null for the list. */
  openIndex?: number | null;
  onOpenIndexChange: (index: number | null) => void;
}) {
  const { t } = useTranslation();
  const open = openIndex !== null ? sources[openIndex] : undefined;

  if (open && openIndex !== null) {
    return (
      <CitationReader
        key={openIndex}
        source={open}
        number={openIndex + 1}
        onBack={() => onOpenIndexChange(null)}
      />
    );
  }

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
              <SourceTile
                source={source}
                position={index + 1}
                onOpen={() => onOpenIndexChange(index)}
              />
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
  onOpen,
}: {
  source: AnswerSource;
  position: number;
  onOpen: () => void;
}) {
  const { t } = useTranslation();

  return (
    <Card
      variant="filled"
      interactive
      asChild
      className="w-full gap-2 text-left"
    >
      <button type="button" onClick={onOpen} title={source.title}>
        <span className="text-foreground line-clamp-3 text-sm font-semibold wrap-break-word">
          {`${position}. ${source.title}`}
        </span>
        {source.connector_name ? (
          <span className="text-muted-foreground flex items-center gap-1.5 text-xs">
            <ConnectorIcon
              icon={connectorIconKey(source.connector_key)}
              className="size-3.5 shrink-0"
            />
            <span className="truncate" title={source.connector_name}>
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
      </button>
    </Card>
  );
}
