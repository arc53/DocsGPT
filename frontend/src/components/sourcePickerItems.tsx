import type { TFunction } from 'i18next';
import { BookOpen, Cloud, FileText, Globe, Network } from 'lucide-react';

import ConnectorIcon from '../connectors/ConnectorIcon';
import { connectionNeedsSignIn } from '../connectors/connectorsSlice';
import type { Connection } from '../connectors/types';
import type { Doc } from '../models/misc';
import {
  connectionOf,
  IngestBadge,
  ingestState,
  sourceDetailLine,
} from '../settings/sourceDetails';
import { sourceKindOf } from '../settings/sourceKinds';
import { sourceItemId } from '../utils/sourceUtils';
import type { MultiSelectPopoverItem } from './MultiSelectPopover';
import { Badge } from './ui/badge';

export type SourceGroupLabels = { own: string; team: string };

// The logo of a connector source whose connection the caller can't see (a
// team's), by the provider its sync names, else its loader type.
const PROVIDER_ICONS: Record<string, string> = {
  google_drive: 'drive',
  share_point: 'sharepoint',
  sharepoint: 'sharepoint',
  confluence: 'confluence',
  s3: 's3',
  github: 'github',
  reddit: 'reddit',
};

/**
 * A knowledge row's icon, by kind: a wiki's book; the logo of the
 * connection or provider it syncs from; a website's globe; a graph's
 * network; another synced source's cloud; else a file.
 */
function sourceIcon(doc: Doc, connection: Connection | undefined) {
  const kind = sourceKindOf(doc);
  if (kind === 'wikis') return <BookOpen />;
  const logo =
    connection?.icon ??
    PROVIDER_ICONS[(doc.provider ?? doc.type ?? '').toLowerCase()];
  if (logo) return <ConnectorIcon icon={logo} className="size-4" />;
  if (kind === 'websites') return <Globe />;
  if (doc.config?.kind === 'graphrag') return <Network />;
  if (kind === 'synced') return <Cloud />;
  return <FileText />;
}

type SourcePickerOptions = {
  t: TFunction;
  labels: SourceGroupLabels;
  /** The caller's own connections. */
  connections: Connection[];
};

/**
 * The rows of a knowledge picker (the chat's and the agent builder's). Each
 * row has an icon for its kind and one line from its Knowledge card's
 * details (`sourceDetailLine`), with the card's badges above that line: a
 * failed or running ingest, and Reconnect when the caller's connection
 * needs a sign-in. When any source is shared through a team, the rows are
 * grouped into the caller's own, then the team's; otherwise the list stays
 * flat.
 *
 * Args:
 *   docs: The sources.
 *   options: The translator, the group labels and the caller's connections.
 *
 * Returns:
 *   The picker rows.
 */
export function toSourcePickerItems(
  docs: Doc[] | null | undefined,
  { t, labels, connections }: SourcePickerOptions,
): MultiSelectPopoverItem[] {
  const list = docs ?? [];
  const isTeam = (doc: Doc) => doc.ownership === 'team';
  const hasTeam = list.some(isTeam);
  const toItem = (doc: Doc): MultiSelectPopoverItem => {
    const connection = connectionOf(doc, connections);
    const line = sourceDetailLine(t, doc, connection) || undefined;
    const item: MultiSelectPopoverItem = {
      id: sourceItemId(doc),
      label: doc.name,
      icon: sourceIcon(doc, connection),
      ...(hasTeam ? { group: isTeam(doc) ? labels.team : labels.own } : {}),
    };
    const ingest = ingestState(doc);
    const badges = [];
    if (connectionNeedsSignIn(connection))
      badges.push(
        <Badge key="reconnect" variant="warning">
          {t('settings.connectors.status.reconnect')}
        </Badge>,
      );
    if (ingest) badges.push(<IngestBadge key="ingest" status={ingest} />);
    if (badges.length === 0) return { ...item, description: line };
    return {
      ...item,
      descriptionNode: (
        <div className="flex flex-col items-start gap-0.5">
          <span className="mt-0.5 flex flex-wrap gap-1">{badges}</span>
          {line ? (
            <p
              className="text-muted-foreground w-full truncate text-xs"
              title={line}
            >
              {line}
            </p>
          ) : null}
        </div>
      ),
    };
  };
  if (!hasTeam) return list.map(toItem);
  return [
    ...list.filter((doc) => !isTeam(doc)).map(toItem),
    ...list.filter(isTeam).map(toItem),
  ];
}
