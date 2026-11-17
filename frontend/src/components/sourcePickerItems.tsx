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
import {
  docFolderId,
  type KnowledgePick,
  sourceIncludedBy,
} from './folders/folderPick';
import type { FolderTree } from './folders/folderTree';
import type { MultiSelectPopoverItem } from './MultiSelectPopover';
import type { HolderFolder } from './pickerScope';
import { Badge } from './ui/badge';
import { cn } from '@/lib/utils';

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
export function sourceIcon(
  doc: Doc,
  connection: Connection | undefined,
  className = 'size-5',
) {
  const kind = sourceKindOf(doc);
  // In the foreground, like a tool's icon: the kind is part of the name.
  const lucide = cn('text-foreground shrink-0', className);
  if (kind === 'wikis') return <BookOpen className={lucide} />;
  const logo =
    connection?.icon ??
    PROVIDER_ICONS[(doc.provider ?? doc.type ?? '').toLowerCase()];
  if (logo)
    return <ConnectorIcon icon={logo} className={cn('shrink-0', className)} />;
  if (kind === 'websites') return <Globe className={lucide} />;
  if (doc.config?.kind === 'graphrag') return <Network className={lucide} />;
  if (kind === 'synced') return <Cloud className={lucide} />;
  return <FileText className={lucide} />;
}

/** Another team's source shared with this team (`origin: "team_shared"`). */
export const isReceivedSource = (doc: Doc): boolean =>
  doc.origin === 'team_shared';

/** The picker group of the sources other teams shared with this team. */
export const receivedSourcesLabel = (t: TFunction): string =>
  t('workspace.page.sharedFromTeams.title');

type SourcePickerOptions = {
  t: TFunction;
  labels: SourceGroupLabels;
  /** The caller's own connections. */
  connections: Connection[];
  /**
   * Text joined to the end of a row's line with " · " ("Added by Lena" in
   * the agent builder), so the row keeps one line.
   */
  lineSuffix?: (doc: Doc) => string | null | undefined;
};

/**
 * The rows of a knowledge picker (the chat's and the agent builder's). Each
 * row has an icon for its kind and one line from its Knowledge card's
 * details (`sourceDetailLine`), with the card's badges above that line: a
 * failed or running ingest, and Reconnect when the caller's connection
 * needs a sign-in. The rows are grouped into the caller's own, then the
 * team's, then those other teams shared with the team (each naming the team
 * it comes from); a picker passes `loneGroupHeading={false}`, so a lone
 * group shows its heading only beside Selected.
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
  options: SourcePickerOptions,
): MultiSelectPopoverItem[] {
  const list = docs ?? [];
  const isTeam = (doc: Doc) =>
    doc.ownership === 'team' && !isReceivedSource(doc);
  const toItem = (doc: Doc) => toSourcePickerItem(doc, options);
  return [
    ...list.filter((doc) => !isTeam(doc) && !isReceivedSource(doc)).map(toItem),
    ...list.filter(isTeam).map(toItem),
    ...list.filter(isReceivedSource).map(toItem),
  ];
}

/**
 * One knowledge picker row (see `toSourcePickerItems`). `linePrefix` leads
 * its line: the folder trail in a flat search, or "Included with Carriers".
 */
export function toSourcePickerItem(
  doc: Doc,
  {
    t,
    labels,
    connections,
    lineSuffix,
    linePrefix,
  }: SourcePickerOptions & { linePrefix?: string | null },
): MultiSelectPopoverItem {
  const connection = connectionOf(doc, connections);
  const received = isReceivedSource(doc);
  // Another team's source says which team it comes from.
  const from =
    received && doc.shared_from?.name
      ? t('workspace.page.sharedFromTeams.from', {
          team: doc.shared_from.name,
          interpolation: { escapeValue: false },
        })
      : null;
  const line =
    [linePrefix, from, sourceDetailLine(t, doc, connection), lineSuffix?.(doc)]
      .filter(Boolean)
      .join(' · ') || undefined;
  const item: MultiSelectPopoverItem = {
    id: sourceItemId(doc),
    label: doc.name,
    icon: sourceIcon(doc, connection),
    group: received
      ? receivedSourcesLabel(t)
      : doc.ownership === 'team'
        ? labels.team
        : labels.own,
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
    keywords: line ? [line] : undefined,
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
}

/** The key of the holder's folder group; no other group key starts so. */
const HOLDER_GROUP = 'folder:holder';

type HolderFolderFirstOptions = {
  t: TFunction;
  /** The folder of the agent or workflow being edited, or null for none. */
  holderFolder: HolderFolder | null | undefined;
  tree: FolderTree;
  /** Every source the picker lists. */
  docs: Doc[];
  pick: KnowledgePick;
  /** A source's row, as the picker draws it (`toSourcePickerItem`). */
  sourceRow: (doc: Doc, linePrefix: string | null) => MultiSelectPopoverItem;
};

/**
 * A knowledge picker's root rows with the holder's folder first: opened
 * from an agent or workflow filed in a folder, the sources filed in that
 * folder lead under "In Carriers, this agent's folder", then the folders
 * and the rest as they were. A source a picked folder brings in keeps its
 * muted, ticked box; a row it replaces (a picked source's Selected-only
 * row) goes, so each source is listed once.
 *
 * Args:
 *   items: The root rows (`buildKnowledgeRows` at the root).
 *   options: The holder's folder, the tree, the sources, the pick and how
 *     to draw a source row.
 *
 * Returns:
 *   The rows, the holder's folder's sources first; `items` itself when the
 *   holder is in no folder or the folder holds no source.
 */
export function withHolderFolderFirst(
  items: MultiSelectPopoverItem[],
  { t, holderFolder, tree, docs, pick, sourceRow }: HolderFolderFirstOptions,
): MultiSelectPopoverItem[] {
  if (!holderFolder) return items;
  const inFolder = docs.filter(
    (doc) => docFolderId(tree, doc) === holderFolder.id,
  );
  if (inFolder.length === 0) return items;
  const lead = inFolder.map((doc): MultiSelectPopoverItem => {
    const cover = sourceIncludedBy(tree, doc, pick);
    const row = sourceRow(
      doc,
      cover
        ? t('folders.picker.includedWith', {
            name: cover.name,
            interpolation: { escapeValue: false },
          })
        : null,
    );
    return {
      ...row,
      group: HOLDER_GROUP,
      groupHeading: holderFolder.heading,
      checked: cover ? true : undefined,
      muted: Boolean(cover),
      disabled: Boolean(cover) || row.disabled,
      pinnedOnly: false,
    };
  });
  const leadIds = new Set(lead.map((row) => row.id));
  return [...lead, ...items.filter((row) => !leadIds.has(row.id))];
}
