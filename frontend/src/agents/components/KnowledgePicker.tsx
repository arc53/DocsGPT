import { Database } from 'lucide-react';
import { type MouseEvent, type ReactNode, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import {
  MultiSelectPopover,
  type MultiSelectPopoverItem,
} from '../../components/MultiSelectPopover';
import SourcesPopoverFooter from '../../components/SourcesPopoverFooter';
import { toSourcePickerItems } from '../../components/sourcePickerItems';
import type { Connection } from '../../connectors/types';
import type { Doc } from '../../models/misc';
import { useSourceKindFilter } from '../../settings/SourceKindFilter';
import Upload from '../../upload/Upload';
import { sourceItemId } from '../../utils/sourceUtils';

export type KnowledgePickerProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The sources the reader can list. */
  docs: Doc[];
  /** The ids picked on the agent or node. */
  selectedIds: string[];
  onToggle: (id: string) => void;
  /** The reader's own connections, for the rows' lines and Reconnect badges. */
  connections: Connection[];
  /**
   * The name of a picked source the list doesn't hold (an owner's private
   * source on a shared agent), which still gets a row so it can be taken off.
   */
  unlistedLabel: (id: string) => string;
  /** That row's line. */
  unlistedLine?: (id: string) => string | null | undefined;
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
};

/**
 * The knowledge picker of the agent builder and a workflow agent node: the
 * reader's sources grouped Yours / Shared with team with a kind track, a
 * remove-only row for each picked source they can't list, who added a
 * source, and a footer to Knowledge and to Upload (with Browse connectors).
 */
export default function KnowledgePicker({
  open,
  onOpenChange,
  docs,
  selectedIds,
  onToggle,
  connections,
  unlistedLabel,
  unlistedLine,
  addedBy,
  trigger,
  onNavigate,
  onUploaded,
  onBrowseConnectors,
}: KnowledgePickerProps) {
  const { t } = useTranslation();
  const [uploadOpen, setUploadOpen] = useState(false);
  // The kind track, back on All each time the picker opens.
  const kinds = useSourceKindFilter(docs, open);

  const items = useMemo<MultiSelectPopoverItem[]>(() => {
    const listed = toSourcePickerItems(kinds.docs, {
      t,
      labels: {
        own: t('conversation.sources.groupOwn'),
        team: t('conversation.sources.groupTeam'),
      },
      connections,
      // Who added a source joins its line, so the row keeps one line.
      lineSuffix: addedBy ? (doc) => addedBy(sourceItemId(doc)) : undefined,
    });
    // A picked source the reader can't list: its kind is unknown, so a kind
    // filter leaves it out.
    const listedIds = new Set(docs.map((doc) => sourceItemId(doc)));
    const unlisted =
      kinds.kind === 'all'
        ? selectedIds
            .filter(
              (id, index) =>
                !listedIds.has(id) && selectedIds.indexOf(id) === index,
            )
            .map((id) => ({
              id,
              label: unlistedLabel(id),
              icon: <Database />,
              description: unlistedLine?.(id) ?? undefined,
            }))
        : [];
    return [...listed, ...unlisted];
  }, [
    addedBy,
    connections,
    docs,
    kinds.docs,
    kinds.kind,
    selectedIds,
    t,
    unlistedLabel,
    unlistedLine,
  ]);

  return (
    <>
      <MultiSelectPopover
        open={open}
        onOpenChange={onOpenChange}
        title={t('conversation.sources.knowledge')}
        items={items}
        // What is picked when it opens comes first.
        selectedFirst
        // Knowledge is always grouped Yours / Shared with team.
        loneGroupHeading={false}
        filters={kinds.filters}
        selectedIds={selectedIds}
        onToggle={onToggle}
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
        />
      )}
    </>
  );
}
