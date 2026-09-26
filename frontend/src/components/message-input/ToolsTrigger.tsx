import { ArrowRight, Wrench } from 'lucide-react';
import { useTranslation } from 'react-i18next';

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
        <Button variant="link" size="inline" asChild>
          <a href="/settings/tools">
            {t('settings.tools.manageTools')}
            <ArrowRight aria-hidden="true" className="size-3" />
          </a>
        </Button>
      }
      trigger={
        <Button
          type="button"
          variant="outline"
          size="sm"
          shape="pill"
          className="max-w-[130px] justify-start"
        >
          <Wrench />
          <span className="text-foreground truncate overflow-hidden text-xs sm:text-sm">
            {t('settings.tools.label')}
          </span>
        </Button>
      }
    />
  );
}
