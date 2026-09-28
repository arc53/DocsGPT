import { ArrowRight, Wrench } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

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
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Button variant="link" size="inline" asChild>
            <Link to="/settings/tools">
              {t('settings.tools.manageTools')}
              <ArrowRight aria-hidden="true" className="size-3" />
            </Link>
          </Button>
          <Button variant="link" size="inline" asChild>
            <Link to="/settings/connectors?capability=tools">
              {t('conversation.sources.connectMore')}
              <ArrowRight aria-hidden="true" className="size-3" />
            </Link>
          </Button>
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
