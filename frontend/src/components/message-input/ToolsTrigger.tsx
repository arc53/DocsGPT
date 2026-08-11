import { useTranslation } from 'react-i18next';

import RedirectIcon from '../../assets/redirect.svg';
import ToolIcon from '../../assets/tool.svg';
import {
  MultiSelectPopover,
  type MultiSelectPopoverItem,
} from '../MultiSelectPopover';
import { Button } from '../ui/button';

type ToolsTriggerProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  items: MultiSelectPopoverItem[];
  selectedIds: string[];
  onToggle: (id: string) => void;
  loading: boolean;
};

export default function ToolsTrigger({
  open,
  onOpenChange,
  items,
  selectedIds,
  onToggle,
  loading,
}: ToolsTriggerProps) {
  const { t } = useTranslation();

  return (
    <MultiSelectPopover
      open={open}
      onOpenChange={onOpenChange}
      title={t('settings.tools.label')}
      items={items}
      selectedIds={selectedIds}
      onToggle={onToggle}
      searchPlaceholder={t('settings.tools.searchPlaceholder')}
      emptyMessage={t('settings.tools.noToolsFound')}
      loading={loading}
      footer={
        <a
          href="/settings/tools"
          className="text-primary inline-flex items-center text-base font-medium"
        >
          {t('settings.tools.manageTools')}
          <img
            src={RedirectIcon}
            alt=""
            aria-hidden="true"
            className="ml-2 h-[11px] w-[11px]"
          />
        </a>
      }
      trigger={
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="xs:px-3 xs:py-1.5 xs:max-w-[150px] dark:border-border border-border hover:bg-muted dark:hover:bg-muted flex h-auto max-w-[130px] items-center justify-start rounded-full border bg-transparent px-2 py-1 shadow-none transition-colors"
        >
          <img
            src={ToolIcon}
            alt="Tools"
            className="mr-1 h-3.5 w-3.5 shrink-0 sm:mr-1.5 sm:h-4 sm:w-4"
          />
          <span className="xs:text-xs dark:text-foreground text-muted-foreground truncate overflow-hidden text-xs font-medium sm:text-sm">
            {t('settings.tools.label')}
          </span>
        </Button>
      }
    />
  );
}
