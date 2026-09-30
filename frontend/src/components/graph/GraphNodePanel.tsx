import { File } from 'lucide-react';
import { useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';

import { Button } from '../ui/button';
import { Card, CardFooter } from '../ui/card';
import { DescriptionItem, DescriptionList } from '../ui/description-list';
import { EmptyState } from '../ui/empty-state';
import { ListRow } from '../ui/list-row';
import { SectionHeader } from '../ui/section-header';
import { PanelBody, PanelHeader } from '../ui/side-panel';
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
import GraphChunkReader from './GraphChunkReader';
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
  /** Whether the chunk drawer offers Edit (`can(source, 'edit')`). */
  canEdit?: boolean;
}

/**
 * One entity's side panel content: its facts, the relationships you can
 * follow, then the chunks it was extracted from; a chunk opens as the
 * panel's second level. Render it in the frame's docked SidePanel (a
 * full-width right sheet on a phone), keyed on the node id so the
 * disclosures and the open chunk reset per node.
 */
export default function GraphNodePanel({
  docId,
  node,
  detail,
  status,
  onRetry,
  fold,
  onSelectNode,
  action,
  overview,
  onOpenInFiles,
  onChunkSaved,
  canEdit = true,
}: GraphNodePanelProps) {
  const { t } = useTranslation();
  const [openChunk, setOpenChunk] = useState<GraphNodeChunk | null>(null);
  const name = detail?.name ?? node.name;
  const type = detail ? detail.type : node.type;

  if (openChunk) {
    return (
      <GraphChunkReader
        key={openChunk.chunk_id}
        docId={docId}
        chunk={openChunk}
        highlight={name}
        onBack={() => setOpenChunk(null)}
        onOpenInFiles={onOpenInFiles}
        onSaved={onChunkSaved}
        canEdit={canEdit}
      />
    );
  }

  return (
    <>
      <PanelHeader
        title={name}
        description={<GraphTypeBadge fold={fold} type={type} />}
      >
        {action ? <div>{action}</div> : null}
      </PanelHeader>
      <PanelBody>
        {status === 'error' ? (
          <EmptyState
            size="sm"
            tone="destructive"
            illustration="none"
            title={t('settings.sources.graphrag.view.nodeLoadFailed')}
            onRetry={onRetry}
          />
        ) : detail && status === 'ready' ? (
          <NodeDetailBody
            detail={detail}
            fold={fold}
            onSelectNode={onSelectNode}
            onOpenChunk={setOpenChunk}
            overview={overview}
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
      </PanelBody>
    </>
  );
}

function NodeDetailBody({
  detail,
  fold,
  onSelectNode,
  onOpenChunk,
  overview,
}: {
  detail: GraphNodeDetail;
  fold: FoldedGraphTypes;
  onSelectNode: (node: GraphNodeRef) => void;
  onOpenChunk: (chunk: GraphNodeChunk) => void;
  overview?: ForceGraphData;
}) {
  const { t } = useTranslation();
  const [descriptionOpen, setDescriptionOpen] = useState(false);
  const [allRelationships, setAllRelationships] = useState(false);
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
                  <button type="button" onClick={() => onOpenChunk(chunk)}>
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
    </>
  );
}
