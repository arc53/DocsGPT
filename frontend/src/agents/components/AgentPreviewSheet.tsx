import { type ReactNode, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch } from 'react-redux';

import { Badge } from '@/components/ui/badge';
import { PanelHeader, SidePanel } from '@/components/ui/side-panel';

import { setPreviewOpen } from '../workflow/workflowPreviewSlice';

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
 * a right SidePanel with a fixed header, then the preview filling the rest.
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
  const dispatch = useDispatch();

  // App moves the toast stack bottom-left while a preview drawer is open, so
  // it doesn't sit over the chat. The flag lives in the workflow preview
  // slice for both agent types.
  useEffect(() => {
    dispatch(setPreviewOpen(open));
    return () => {
      dispatch(setPreviewOpen(false));
    };
  }, [dispatch, open]);

  return (
    <SidePanel
      open={open}
      onOpenChange={onOpenChange}
      size="wide"
      // Radix warns about a dialog without a description; only opt out when
      // there is none.
      {...(description ? {} : { 'aria-describedby': undefined })}
    >
      <PanelHeader
        title={title}
        description={
          description ? (
            <span className="block truncate" title={description}>
              {description}
            </span>
          ) : null
        }
        actions={
          running || actions ? (
            <>
              {running && (
                <Badge variant="info">
                  {t('agents.schedules.status.running')}
                </Badge>
              )}
              {actions}
            </>
          ) : null
        }
      />
      {/* The preview owns its scroller and padding, so no PanelBody. */}
      <div className="flex min-h-0 flex-1 flex-col">{children}</div>
    </SidePanel>
  );
}
