import { Wrench } from 'lucide-react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import {
  MultiSelectPopover,
  type MultiSelectPopoverItem,
} from '../MultiSelectPopover';
import PickerFooter from '../PickerFooter';
import { Button } from '../ui/button';

type ToolsTriggerProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  items: MultiSelectPopoverItem[];
  selectedIds: string[];
  onToggle: (id: string) => void;
  loading: boolean;
  /** Shown above the link, e.g. connections that need signing in again. */
  notice?: ReactNode;
  /** Opens the add-tool modal; the picker closes first. */
  onAddTool: () => void;
};

export default function ToolsTrigger({
  open,
  onOpenChange,
  items,
  selectedIds,
  onToggle,
  loading,
  notice,
  onAddTool,
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
        <div className="flex flex-col gap-3">
          {notice}
          <PickerFooter
            to="/settings/tools"
            linkLabel={t('settings.tools.manageTools')}
            onNavigate={() => onOpenChange(false)}
            actionLabel={t('settings.tools.addTool')}
            onAction={() => {
              onOpenChange(false);
              onAddTool();
            }}
          />
        </div>
      }
      trigger={
        <Button
          type="button"
          variant="outline"
          size="sm"
          shape="pill"
          className="max-w-[130px] justify-start"
        >
          <Wrench className="size-3.5 sm:size-4" />
          <span className="text-foreground truncate overflow-hidden text-xs sm:text-sm">
            {t('settings.tools.label')}
          </span>
        </Button>
      }
    />
  );
}
