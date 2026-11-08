import { Database } from 'lucide-react';
import { type MouseEvent, type ReactNode, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import {
  MultiSelectPopover,
  type MultiSelectPopoverItem,
} from '../../components/MultiSelectPopover';
import SourcesPopoverFooter from '../../components/SourcesPopoverFooter';
import type { KnowledgePick } from '../../components/folders/folderPick';
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
 * to Knowledge and to Upload (with Browse connectors).
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

  const { popoverProps } = useKnowledgeFolderPicker({
    open,
    docs,
    pick,
    onPickChange,
    connections,
    // Who added a source joins its line, so the row keeps one line.
    lineSuffix: addedBy ? (doc) => addedBy(sourceItemId(doc)) : undefined,
    extraSources,
    unlistedFolder,
  });

  return (
    <>
      <MultiSelectPopover
        open={open}
        onOpenChange={onOpenChange}
        title={t('conversation.sources.knowledge')}
        // What is picked when it opens comes first (at the root), folders
        // open in place, and a search lists every level.
        {...popoverProps}
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
