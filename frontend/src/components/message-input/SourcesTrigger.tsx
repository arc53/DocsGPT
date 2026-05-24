import { useTranslation } from 'react-i18next';

import RedirectIcon from '../../assets/redirect.svg';
import SourceIcon from '../../assets/source.svg';
import type { Doc } from '../../models/misc';
import {
  MultiSelectPopover,
  type MultiSelectPopoverItem,
} from '../MultiSelectPopover';
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
        <div className="flex flex-col gap-3">
          <a
            href="/settings/sources"
            className="text-primary inline-flex items-center gap-2 text-base font-medium"
            onClick={() => onOpenChange(false)}
          >
            {t('settings.sources.goToSources')}
            <img
              src={RedirectIcon}
              alt=""
              aria-hidden="true"
              className="h-3 w-3"
            />
          </a>
          <Button
            type="button"
            variant="outline"
            onClick={onUploadClick}
            className="border-primary text-primary hover:bg-primary/90 h-auto w-auto self-start rounded-full border bg-transparent px-4 py-2 text-sm font-medium shadow-none transition-colors duration-200 hover:text-white"
          >
            {t('settings.sources.uploadNew')}
          </Button>
        </div>
      }
      trigger={
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="xs:px-3 xs:py-1.5 dark:border-border border-border hover:bg-accent dark:hover:bg-muted flex h-auto max-w-[130px] items-center justify-start rounded-full border bg-transparent px-2 py-1 shadow-none transition-colors sm:max-w-[150px]"
          title={
            selectedDocs && selectedDocs.length > 0
              ? selectedDocs.map((doc) => doc.name).join(', ')
              : t('conversation.sources.title')
          }
        >
          <img
            src={SourceIcon}
            alt="Sources"
            className="mr-1 h-3.5 w-3.5 shrink-0 sm:mr-1.5 sm:h-4"
          />
          <span className="xs:text-xs dark:text-foreground text-muted-foreground truncate overflow-hidden text-xs font-medium sm:text-sm">
            {selectedDocs && selectedDocs.length > 0
              ? selectedDocs.length === 1
                ? selectedDocs[0].name
                : `${selectedDocs.length} sources selected`
              : t('conversation.sources.title')}
          </span>
        </Button>
      }
    />
  );
}
