import { Database } from 'lucide-react';
import { type MouseEvent, type ReactNode, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import {
  MultiSelectPopover,
  type MultiSelectPopoverItem,
} from '../../components/MultiSelectPopover';
import type { HolderFolder } from '../../components/pickerScope';
import {
  toSourcePickerItem,
  withHolderFolderFirst,
} from '../../components/sourcePickerItems';
import SourcesPopoverFooter from '../../components/SourcesPopoverFooter';
import {
  folderIdOfRow,
  type KnowledgePick,
} from '../../components/folders/folderPick';
import type { UnlistedFolderRow } from '../../components/folders/knowledgeFolderRows';
import { useKnowledgeFolderPicker } from '../../components/folders/useKnowledgeFolderPicker';
import type { Connection } from '../../connectors/types';
import type { LeaveTo } from '../../hooks/useLeaveGuard';
import type { Doc } from '../../models/misc';
import Upload from '../../upload/Upload';
import { sourceItemId } from '../../utils/sourceUtils';

export type KnowledgePickerProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The sources the reader can list. */
  docs: Doc[];
  /** The sources and whole folders picked on the agent or node. */
  pick: KnowledgePick;
  onPickChange: (next: KnowledgePick) => void;
  /** The reader's own connections, for the rows' lines and Reconnect badges. */
  connections: Connection[];
  /**
   * The name of a picked source the list doesn't hold (an owner's private
   * source on a shared agent), which still gets a row so it can be taken off.
   */
  unlistedLabel: (id: string) => string;
  /** That row's line. */
  unlistedLine?: (id: string) => string | null | undefined;
  /**
   * A picked folder the reader's folders don't hold (a teammate's, or
   * deleted): its row, so it can be taken off.
   */
  unlistedFolder?: (id: string) => Omit<UnlistedFolderRow, 'id'>;
  /** Who added a listed source ("Added by Lena"), joined to its row's line. */
  addedBy?: (id: string) => string | null;
  /**
   * The folder the agent or workflow is filed in: at the root its sources
   * come first, under the folder's heading.
   */
  holderFolder?: HolderFolder | null;
  /**
   * Off while the agent or workflow lives in another workspace than the
   * folder tree (before the page follows it there): only the folders
   * picked on it are listed, so they can be taken off.
   */
  foldersOffered?: boolean;
  /** The picker's trigger. */
  trigger: ReactNode;
  /**
   * The Go to Knowledge link's click, after the picker closed: a builder
   * prevents it and asks first while it has unsaved changes.
   */
  onNavigate: (event: MouseEvent<HTMLAnchorElement>) => void;
  /** A source the footer's Upload created, to put on. */
  onUploaded: (sourceId?: string) => void;
  /**
   * Upload's Browse connectors, through the builder's leave guard; left out,
   * Upload offers none.
   */
  onBrowseConnectors?: () => void;
  /** Upload's connect runs leave through the builder's leave guard. */
  onLeaveTo?: LeaveTo;
};

/**
 * The knowledge picker of the agent builder and a workflow agent node: the
 * reader's folders and sources (`useKnowledgeFolderPicker`: a folder picks
 * whole, its chevron opens it) with a kind track, a remove-only row for each
 * picked source or folder they can't list, who added a source, and a footer
 * to Knowledge and to Upload (with Browse connectors). Opened from an agent
 * or workflow filed in a folder, that folder's sources lead the root.
 */
export default function KnowledgePicker({
  open,
  onOpenChange,
  docs,
  pick,
  onPickChange,
  connections,
  unlistedLabel,
  unlistedLine,
  unlistedFolder,
  addedBy,
  holderFolder,
  foldersOffered = true,
  trigger,
  onNavigate,
  onUploaded,
  onBrowseConnectors,
  onLeaveTo,
}: KnowledgePickerProps) {
  const { t } = useTranslation();
  const [uploadOpen, setUploadOpen] = useState(false);
  // A picked source the reader can't list: its kind is unknown, so a kind
  // filter leaves it out (the hook drops these under one).
  const extraSources = useMemo<MultiSelectPopoverItem[]>(() => {
    const listedIds = new Set(docs.map((doc) => sourceItemId(doc)));
    return pick.sources
      .filter(
        (id, index) => !listedIds.has(id) && pick.sources.indexOf(id) === index,
      )
      .map((id) => ({
        id,
        label: unlistedLabel(id),
        icon: <Database />,
        description: unlistedLine?.(id) ?? undefined,
      }));
  }, [docs, pick.sources, unlistedLabel, unlistedLine]);

  // Who added a source joins its line, so the row keeps one line.
  const lineSuffix = useMemo(
    () => (addedBy ? (doc: Doc) => addedBy(sourceItemId(doc)) : undefined),
    [addedBy],
  );
  const { popoverProps, tree } = useKnowledgeFolderPicker({
    open,
    docs,
    pick,
    onPickChange,
    connections,
    lineSuffix,
    extraSources,
    unlistedFolder,
  });
  // The root before a search or a kind narrows it (`selectedFirst` says so
  // when there are folders): the holder's folder leads.
  const atRoot = Boolean(popoverProps.selectedFirst) && !popoverProps.header;
  const items = useMemo(() => {
    if (!foldersOffered)
      return popoverProps.items.filter((row) => {
        const folderId = folderIdOfRow(row.id);
        return folderId === null || pick.folders.includes(folderId);
      });
    return atRoot
      ? withHolderFolderFirst(popoverProps.items, {
          t,
          holderFolder,
          tree,
          docs,
          pick,
          sourceRow: (doc, linePrefix) =>
            toSourcePickerItem(doc, {
              t,
              labels: {
                own: t('conversation.sources.groupOwn'),
                team: t('conversation.sources.groupTeam'),
              },
              connections,
              lineSuffix,
              linePrefix,
            }),
        })
      : popoverProps.items;
  }, [
    foldersOffered,
    atRoot,
    popoverProps.items,
    t,
    holderFolder,
    tree,
    docs,
    pick,
    connections,
    lineSuffix,
  ]);

  return (
    <>
      <MultiSelectPopover
        open={open}
        onOpenChange={onOpenChange}
        title={t('conversation.sources.knowledge')}
        // What is picked when it opens comes first (at the root), folders
        // open in place, and a search lists every level.
        {...popoverProps}
        items={items}
        // Knowledge is always grouped (Folders · Sources or Yours, then
        // Shared with team).
        loneGroupHeading={false}
        searchPlaceholder={t('agents.form.sourcePopup.searchPlaceholder')}
        emptyMessage={t('settings.sources.noKnowledgeFound')}
        footer={
          <SourcesPopoverFooter
            onNavigate={(event) => {
              onOpenChange(false);
              onNavigate(event);
            }}
            onUploadClick={() => {
              onOpenChange(false);
              setUploadOpen(true);
            }}
          />
        }
        trigger={trigger}
      />
      {uploadOpen && (
        <Upload
          receivedFile={[]}
          setModalState={(state) => setUploadOpen(state === 'ACTIVE')}
          isOnboarding={false}
          renderTab={null}
          close={() => setUploadOpen(false)}
          onSuccessfulUpload={onUploaded}
          selectUploadedDoc={false}
          onBrowseConnectors={onBrowseConnectors}
          onNavigate={onLeaveTo}
        />
      )}
    </>
  );
}
