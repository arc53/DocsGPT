import { Database } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { Doc } from '../../models/misc';
import { formatCount } from '../../utils/dateTimeUtils';
import {
  MultiSelectPopover,
  type MultiSelectPopoverItem,
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
};

export default function SourcesTrigger({
  open,
  onOpenChange,
  items,
  selectedIds,
  onToggle,
  selectedDocs,
  onUploadClick,
}: SourcesTriggerProps) {
  const { t } = useTranslation();
  const docs = selectedDocs ?? [];
  const count = docs.length;

  return (
    <MultiSelectPopover
      open={open}
      onOpenChange={onOpenChange}
      title={t('conversation.sources.text')}
      items={items}
      selectedIds={selectedIds}
      onToggle={onToggle}
      searchPlaceholder={t('settings.sources.searchPlaceholder')}
      emptyMessage={t('conversation.sources.noSourcesAvailable')}
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
          <Database className="size-3.5 sm:size-4" />
          <span
            className="text-foreground truncate overflow-hidden text-xs sm:text-sm"
            title={
              count > 0 ? docs.map((doc) => doc.name).join(', ') : undefined
            }
          >
            {count === 1 ? docs[0].name : t('conversation.sources.knowledge')}
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
