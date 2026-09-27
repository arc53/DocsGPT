import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from '@/components/ui/sheet';

type AgentPreviewSheetProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The drawer's title, e.g. "Preview". */
  title: string;
  /** One muted line under the title: the agent's name. */
  description?: string;
  /** Shows an info "Running" badge while the preview is answering. */
  running?: boolean;
  /** Actions at the header's right end (New chat). */
  actions?: ReactNode;
  /** The preview itself; fills the rest of the drawer. */
  children: ReactNode;
};

/**
 * The drawer an agent is previewed in, for workflow and classic agents alike:
 * a right Sheet with a title row, a rule, then the preview filling the rest.
 *
 * Args:
 *   open: Whether the drawer is open.
 *   onOpenChange: Called with the next open state (the X, Escape, the scrim).
 *   title: The drawer's title.
 *   description: A muted line under the title.
 *   running: Whether the preview is answering; shows a Running badge.
 *   actions: Nodes at the right end of the header, clear of the close button.
 *   children: The preview body.
 */
export default function AgentPreviewSheet({
  open,
  onOpenChange,
  title,
  description,
  running = false,
  actions,
  children,
}: AgentPreviewSheetProps) {
  const { t } = useTranslation();
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-full max-w-none p-0 sm:max-w-[600px] md:max-w-[700px] lg:max-w-[800px]"
      >
        <div className="flex min-h-0 flex-1 flex-col">
          {/* pr-12 keeps the header clear of the close X at top-2 right-2. */}
          <div className="flex items-center gap-3 px-6 pt-6 pr-12 pb-4">
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <SheetTitle>{title}</SheetTitle>
              {description && (
                <SheetDescription className="truncate" title={description}>
                  {description}
                </SheetDescription>
              )}
            </div>
            {running && (
              <Badge variant="info">
                {t('agents.schedules.status.running')}
              </Badge>
            )}
            {actions}
          </div>
          <Separator />
          <div className="flex min-h-0 flex-1 flex-col">{children}</div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
