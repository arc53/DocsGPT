import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useMemo,
} from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch } from 'react-redux';

import ArtifactPanel from '@/components/ArtifactPanel';
import { Badge } from '@/components/ui/badge';
import { PanelHeader, SidePanel } from '@/components/ui/side-panel';
import { cn } from '@/lib/utils';

import type {
  ArtifactCardItem,
  OpenArtifactRequest,
} from '../../conversation/artifactCards';
import ArtifactsPanel from '../../conversation/ArtifactsPanel';
import { useArtifactDetail } from '../../conversation/useArtifactDetail';
import { setPreviewOpen } from '../workflow/workflowPreviewSlice';

/**
 * Opens a preview answer's artifacts inside the drawer: there is no room
 * beside an 800px drawer for the chat's docked panel, so the artifact takes
 * the drawer over, with Back to the run (or to the answer's list).
 */
export const PreviewArtifactsContext = createContext<{
  openArtifact: (request: OpenArtifactRequest) => void;
  openArtifactList: (items: ArtifactCardItem[], key: string) => void;
  /** Keeps the list showing current with its answer's files. */
  syncArtifactList: (key: string, items: ArtifactCardItem[]) => void;
  /** The artifact showing, so its card is marked open. */
  shown: { id: string; version?: number } | null;
  /** The key of the answer whose list is showing. */
  listKey: string | null;
} | null>(null);

export const usePreviewArtifacts = () => useContext(PreviewArtifactsContext);

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
  const {
    detail,
    setDetail,
    back,
    reset,
    openArtifact,
    openArtifactList,
    syncArtifactList,
    shown,
    listKey,
  } = useArtifactDetail();

  // A closed drawer opens on the preview again.
  useEffect(() => {
    if (!open) reset();
  }, [open, reset]);

  const artifacts = useMemo(
    () => ({
      openArtifact,
      openArtifactList,
      syncArtifactList,
      shown,
      listKey,
    }),
    [openArtifact, openArtifactList, syncArtifactList, shown, listKey],
  );

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
      {detail?.kind === 'artifact' ? (
        <ArtifactPanel
          key={`${detail.open.id}:${detail.open.version ?? ''}`}
          artifactId={detail.open.id}
          toolName={detail.open.toolName}
          version={detail.open.version}
          conversationId={null}
          onBack={back}
          backLabel={t('agents.workflow.preview.backToRun')}
        />
      ) : detail?.kind === 'artifacts' ? (
        <ArtifactsPanel
          items={detail.items}
          open={detail.open}
          onOpenChange={(next) =>
            setDetail((current) =>
              current?.kind === 'artifacts'
                ? { ...current, open: next }
                : current,
            )
          }
          onBack={back}
          conversationId={null}
        />
      ) : (
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
      )}
      {/* The preview owns its scroller and padding, so no PanelBody. It stays
        mounted under an open artifact, so a running answer keeps streaming. */}
      <PreviewArtifactsContext.Provider value={artifacts}>
        <div className={cn('flex min-h-0 flex-1 flex-col', detail && 'hidden')}>
          {children}
        </div>
      </PreviewArtifactsContext.Provider>
    </SidePanel>
  );
}
