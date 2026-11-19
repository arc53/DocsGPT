import { Database, Folder as FolderIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import type { Doc } from '../../models/misc';
import type { SelectedFolder } from '../../preferences/preferenceApi';
import { formatCount } from '../../utils/dateTimeUtils';
import {
  MultiSelectPopover,
  type MultiSelectPopoverItem,
  type MultiSelectPopoverProps,
} from '../MultiSelectPopover';
import SourcesPopoverFooter from '../SourcesPopoverFooter';
import { Badge } from '../ui/badge';
import { Button } from '../ui/button';

type SourcesTriggerProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  items: MultiSelectPopoverItem[];
  selectedIds: string[];
  onToggle: (id: string) => void;
  selectedDocs: Doc[] | null | undefined;
  onUploadClick: () => void;
  /** The kind filter drawn under the search (`useSourceKindFilter`). */
  filters?: ReactNode;
  /** Whole folders picked, named on the pill when one is all there is. */
  selectedFolders?: SelectedFolder[];
} & Partial<
  Pick<
    MultiSelectPopoverProps,
    | 'header'
    | 'search'
    | 'onSearchChange'
    | 'shouldFilter'
    | 'selectedFirst'
    | 'onBack'
  >
>;

export default function SourcesTrigger({
  open,
  onOpenChange,
  items,
  selectedIds,
  onToggle,
  selectedDocs,
  onUploadClick,
  filters,
  selectedFolders = [],
  selectedFirst = true,
  ...folderProps
}: SourcesTriggerProps) {
  const { t } = useTranslation();
  const docs = selectedDocs ?? [];
  // A folder counts once, like a source.
  const count = docs.length + selectedFolders.length;
  const names = [
    ...selectedFolders.map((folder) => folder.name),
    ...docs.map((doc) => doc.name),
  ];
  const loneFolder = docs.length === 0 && selectedFolders.length === 1;

  return (
    <MultiSelectPopover
      open={open}
      onOpenChange={onOpenChange}
      title={t('conversation.sources.knowledge')}
      items={items}
      selectedIds={selectedIds}
      onToggle={onToggle}
      // What is chosen when it opens comes first, fixed while it is open.
      selectedFirst={selectedFirst}
      {...folderProps}
      // Rows are grouped Yours / Shared with team; a lone group needs no
      // heading unless Selected sits above it.
      loneGroupHeading={false}
      filters={filters}
      searchPlaceholder={t('agents.form.sourcePopup.searchPlaceholder')}
      emptyMessage={t('settings.sources.noKnowledgeFound')}
      footer={
        <SourcesPopoverFooter
          onNavigate={() => onOpenChange(false)}
          onUploadClick={onUploadClick}
        />
      }
      trigger={
        <Button
          type="button"
          variant="outline"
          size="sm"
          shape="pill"
          className="max-w-[130px] justify-start sm:max-w-[150px]"
          aria-label={
            count > 1
              ? t('conversation.sources.triggerLabel', {
                  count,
                  formatted: formatCount(count),
                })
              : undefined
          }
        >
          {/* One folder and nothing else reads as the folder. */}
          {loneFolder ? (
            <FolderIcon className="size-3.5 sm:size-4" />
          ) : (
            <Database className="size-3.5 sm:size-4" />
          )}
          <span
            className="text-foreground truncate overflow-hidden text-xs sm:text-sm"
            title={count > 0 ? names.join(', ') : undefined}
          >
            {count === 1 ? names[0] : t('conversation.sources.knowledge')}
          </span>
          {/* One source is named; several are counted, like the Tools pill.
              The aria-label says it for screen readers. */}
          {count > 1 && (
            <Badge className="tabular-nums" aria-hidden="true">
              {formatCount(count)}
            </Badge>
          )}
        </Button>
      }
    />
  );
}
