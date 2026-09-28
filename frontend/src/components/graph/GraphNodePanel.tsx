import { File, X } from 'lucide-react';
import { useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';

import { Button } from '../ui/button';
import { Card, CardFooter } from '../ui/card';
import { DescriptionItem, DescriptionList } from '../ui/description-list';
import { EmptyState } from '../ui/empty-state';
import { IconButton } from '../ui/icon-button';
import { ListRow } from '../ui/list-row';
import { SectionHeader } from '../ui/section-header';
import { Separator } from '../ui/separator';
import { Skeleton } from '../ui/skeleton';
import { formatCount } from '../../utils/dateTimeUtils';
import { chunkPreviewText } from '../chunkUtils';
import {
  groupRelationships,
  type ForceGraphData,
  type GraphNodeChunk,
  type GraphNodeDetail,
  type FoldedGraphTypes,
} from '../graphViewUtils';
import GraphChunkSheet from './GraphChunkSheet';
import {
  chunkFileName,
  overviewRelationships,
  relationshipLabelText,
} from './graphCanvasUtils';
import { GraphTypeBadge, GraphTypeDot } from './GraphTypeDot';
import type { GraphNodeDetailStatus } from './useGraphNodeDetail';

/** What the views know about a node before its detail loads. */
export interface GraphNodeRef {
  id: string;
  name: string;
  type?: string | null;
}

/** Relationship rows shown before "Show all". */
export const RELATIONSHIP_PREVIEW = 12;
/** A description longer than this gets a Show more toggle. */
const LONG_DESCRIPTION = 240;

interface GraphNodePanelProps {
  /** The source id (a chunk edit saves against it). */
  docId: string;
  node: GraphNodeRef;
  detail: GraphNodeDetail | null;
  status: GraphNodeDetailStatus;
  onRetry: () => void;
  fold: FoldedGraphTypes;
  onClose: () => void;
  /**
   * Draw the panel's own close X. Off in the phone bottom sheet, whose
   * handle means no X (the scrim closes it).
   */
  showClose?: boolean;
  /** Select another node (a relationship row). */
  onSelectNode: (node: GraphNodeRef) => void;
  /** An extra control under the type badge ("Show in graph"). */
  action?: ReactNode;
  /**
   * The loaded overview: its links around the node stand in for the
   * relationships when the detail has none (an API that predates them).
   */
  overview?: ForceGraphData;
  /** Show a chunk's file on the Files tab (the chunk drawer's "Open in Files"). */
  onOpenInFiles?: (path: string) => void;
  /** Refetch the detail after a chunk edit, keeping it on screen. */
  onChunkSaved?: () => void;
}

/**
 * The node panel docked in a graph frame, the Graph tab's canvas and the
 * Entities table alike: a `border-l` column at 320px, 40% of the frame from
 * `xl` (capped at the 576px detail-drawer width), so the relationship list has
 * room once the screen does.
 */
export function GraphNodePanelDock({ children }: { children: ReactNode }) {
  return (
    <aside className="border-border flex w-80 shrink-0 flex-col border-l xl:w-2/5 xl:max-w-xl">
      {children}
    </aside>
  );
}

/**
 * One entity's panel: its facts, the relationships you can follow, then the
 * chunks it was extracted from. Docked beside the canvas or the entity table
 * on desktop, in a bottom sheet on a phone. Key it on the node id so the
 * disclosures reset per node.
 */
export default function GraphNodePanel({
  docId,
  node,
  detail,
  status,
  onRetry,
  fold,
  onClose,
  showClose = true,
  onSelectNode,
  action,
  overview,
  onOpenInFiles,
  onChunkSaved,
}: GraphNodePanelProps) {
  const { t } = useTranslation();
  const name = detail?.name ?? node.name;
  const type = detail ? detail.type : node.type;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-start gap-3 px-4 py-3">
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <SectionHeader
              as="h3"
              size="xs"
              className="wrap-break-word"
              title={name}
            />
            <GraphTypeBadge fold={fold} type={type} />
          </div>
          {action ? <div>{action}</div> : null}
        </div>
        {showClose ? (
          <IconButton
            variant="ghost-muted"
            size="icon-sm"
            className="shrink-0"
            onClick={onClose}
            label={t('settings.sources.graphrag.view.close')}
            icon={X}
            side="bottom"
          />
        ) : null}
      </div>
      <Separator />
      <div className="scrollbar-overlay flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto p-4">
        {status === 'error' ? (
          <EmptyState
            size="sm"
            tone="destructive"
            illustration="none"
            title={t('settings.sources.graphrag.view.nodeLoadFailed')}
            action={
              <Button
                type="button"
                variant="outline"
                size="sm"
                shape="pill"
                onClick={onRetry}
              >
                {t('retry')}
              </Button>
            }
          />
        ) : detail && status === 'ready' ? (
          <NodeDetailBody
            docId={docId}
            detail={detail}
            fold={fold}
            onSelectNode={onSelectNode}
            overview={overview}
            onOpenInFiles={onOpenInFiles}
            onChunkSaved={onChunkSaved}
          />
        ) : (
          <div
            className="flex flex-col gap-3"
            aria-busy="true"
            aria-label={t('settings.sources.graphrag.view.loadingNode')}
          >
            <Skeleton className="h-3 w-1/2" />
            <Skeleton className="h-3 w-2/5" />
            <Skeleton className="mt-3 h-3 w-full" />
            <Skeleton className="h-3 w-5/6" />
            <Skeleton className="h-3 w-3/4" />
          </div>
        )}
      </div>
    </div>
  );
}

function NodeDetailBody({
  docId,
  detail,
  fold,
  onSelectNode,
  overview,
  onOpenInFiles,
  onChunkSaved,
}: {
  docId: string;
  detail: GraphNodeDetail;
  fold: FoldedGraphTypes;
  onSelectNode: (node: GraphNodeRef) => void;
  overview?: ForceGraphData;
  onOpenInFiles?: (path: string) => void;
  onChunkSaved?: () => void;
}) {
  const { t } = useTranslation();
  const [descriptionOpen, setDescriptionOpen] = useState(false);
  const [allRelationships, setAllRelationships] = useState(false);
  const [openChunk, setOpenChunk] = useState<GraphNodeChunk | null>(null);
  const rows = useMemo(
    () =>
      groupRelationships(
        detail.relationships ??
          (overview
            ? overviewRelationships(detail.id, overview.links, overview.nodes)
            : []),
      ),
    [detail.relationships, detail.id, overview],
  );
  const mentions = detail.doc_freq ?? detail.chunks.length;
  // The list is capped server-side; the total counts every edge.
  const returned = detail.relationships?.length ?? 0;
  const relationshipsTotal = detail.relationships_total ?? rows.length;
  const capped =
    detail.relationships_total !== undefined &&
    detail.relationships_total > returned;
  const shownRows = allRelationships
    ? rows
    : rows.slice(0, RELATIONSHIP_PREVIEW);
  const description = (detail.description ?? '').trim();
  const relatedTo = t('settings.sources.graphrag.view.relatedTo');

  return (
    <>
      <DescriptionList size="xs">
        <DescriptionItem
          label={t('settings.sources.graphrag.view.connections')}
        >
          <span className="tabular-nums">{formatCount(detail.degree)}</span>
        </DescriptionItem>
        <DescriptionItem
          label={t('settings.sources.graphrag.view.mentionedIn')}
        >
          <span className="tabular-nums">
            {t('settings.sources.graphrag.view.chunkCount', {
              count: mentions,
              formatted: formatCount(mentions),
            })}
          </span>
        </DescriptionItem>
      </DescriptionList>

      {description ? (
        <div className="flex flex-col gap-1">
          <p
            className={cn(
              'text-muted-foreground text-sm leading-relaxed wrap-break-word',
              !descriptionOpen && 'line-clamp-4',
            )}
          >
            {description}
          </p>
          {description.length > LONG_DESCRIPTION ? (
            <Button
              type="button"
              variant="link"
              size="sm"
              className="-ml-3 w-fit justify-start"
              aria-expanded={descriptionOpen}
              onClick={() => setDescriptionOpen((open) => !open)}
            >
              {descriptionOpen
                ? t('settings.sources.graphrag.view.showLess')
                : t('settings.sources.graphrag.view.showMore')}
            </Button>
          ) : null}
        </div>
      ) : null}

      <section className="flex flex-col gap-2">
        <SectionHeader
          as="h4"
          size="xs"
          title={
            <>
              {t('settings.sources.graphrag.view.relationships')}{' '}
              <span className="text-muted-foreground font-normal tabular-nums">
                {formatCount(relationshipsTotal)}
              </span>
            </>
          }
        />
        {rows.length === 0 ? (
          <p className="text-muted-foreground text-xs">
            {t('settings.sources.graphrag.view.noRelationships')}
          </p>
        ) : (
          <ul className="-mx-2 flex flex-col">
            {shownRows.map((row) => {
              const labels = relationshipLabelText(row.labels, relatedTo);
              return (
                <ListRow
                  key={row.id}
                  interactive
                  asChild
                  size="sm"
                  leading={
                    <GraphTypeDot
                      fold={fold}
                      type={row.type}
                      className="mt-1.5"
                    />
                  }
                  title={<span title={row.name}>{row.name}</span>}
                  description={<span title={labels}>{labels}</span>}
                >
                  <button
                    type="button"
                    onClick={() =>
                      onSelectNode({
                        id: row.id,
                        name: row.name,
                        type: row.type,
                      })
                    }
                  />
                </ListRow>
              );
            })}
          </ul>
        )}
        {rows.length > RELATIONSHIP_PREVIEW ? (
          <Button
            type="button"
            variant="link"
            size="sm"
            className="-ml-3 w-fit justify-start"
            aria-expanded={allRelationships}
            onClick={() => setAllRelationships((open) => !open)}
          >
            {allRelationships
              ? t('settings.sources.graphrag.view.showFewer')
              : t('settings.sources.graphrag.view.showAll', {
                  count: rows.length,
                  formatted: formatCount(rows.length),
                })}
          </Button>
        ) : null}
        {capped ? (
          <p className="text-muted-foreground text-xs">
            {t('settings.sources.graphrag.view.relationshipsCapped', {
              count: relationshipsTotal,
              shown: formatCount(returned),
              total: formatCount(relationshipsTotal),
            })}
          </p>
        ) : null}
      </section>

      <section className="flex flex-col gap-2">
        <SectionHeader
          as="h4"
          size="xs"
          title={
            <>
              {t('settings.sources.graphrag.view.sourceChunks')}{' '}
              <span className="text-muted-foreground font-normal tabular-nums">
                {formatCount(detail.chunks.length)}
              </span>
            </>
          }
        />
        {detail.chunks.length === 0 ? (
          <p className="text-muted-foreground text-xs">
            {t('settings.sources.graphrag.view.noChunks')}
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {detail.chunks.map((chunk) => {
              const file = chunkFileName(chunk.metadata);
              return (
                <Card
                  key={chunk.chunk_id}
                  variant="filled"
                  padding="sm"
                  interactive
                  className="gap-2 text-left"
                  asChild
                >
                  <button type="button" onClick={() => setOpenChunk(chunk)}>
                    <p className="text-foreground line-clamp-3 text-xs leading-relaxed wrap-break-word">
                      {chunkPreviewText(chunk.text)}
                    </p>
                    {file ? (
                      <CardFooter className="min-w-0 gap-1.5">
                        <File className="size-3 shrink-0" aria-hidden="true" />
                        <span className="truncate" title={file}>
                          {file}
                        </span>
                      </CardFooter>
                    ) : null}
                  </button>
                </Card>
              );
            })}
          </div>
        )}
      </section>

      <GraphChunkSheet
        docId={docId}
        chunk={openChunk}
        highlight={detail.name}
        onClose={() => setOpenChunk(null)}
        onOpenInFiles={onOpenInFiles}
        onSaved={onChunkSaved}
      />
    </>
  );
}
