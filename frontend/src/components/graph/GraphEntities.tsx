import { Waypoints } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../../api/services/userService';
import { useDebouncedValue, useMediaQuery } from '../../hooks';
import { selectToken } from '../../preferences/preferenceSlice';
import { formatCount } from '../../utils/dateTimeUtils';
import SearchInput from '../SearchInput';
import { Button } from '../ui/button';
import { Card } from '../ui/card';
import { EmptyState } from '../ui/empty-state';
import { Pagination } from '../ui/pagination';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../ui/select';
import { Sheet, SheetContent } from '../ui/sheet';
import { Skeleton } from '../ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../ui/table';
import type {
  FoldedGraphTypes,
  ForceGraphData,
  GraphNodeSummary,
  GraphTypeFacet,
} from '../graphViewUtils';
import GraphNodePanel, {
  GraphNodePanelDock,
  type GraphNodeRef,
} from './GraphNodePanel';
import { GraphTypeBadge } from './GraphTypeDot';
import { useGraphNodeDetail } from './useGraphNodeDetail';

const ENTITIES_PER_PAGE = 25;
// Radix Select can't hold "" as a value, and "" is the untyped key.
const ALL_TYPES = '__all';
const UNTYPED = '__untyped';

type ListStatus = 'loading' | 'error' | 'ready';

/**
 * The Entities tab: every node of the source, searchable and filterable by
 * type, busiest first, paged. The frame is the Graph tab's: one `subtle`
 * Card at `h-[70svh]` with the table scrolling inside and a row's node panel
 * docked at its right edge (a bottom sheet on a phone), whose "Show in graph"
 * jumps to the canvas.
 */
export default function GraphEntities({
  docId,
  fold,
  onShowInGraph,
  overview,
  onOpenInFiles,
}: {
  docId: string;
  fold: FoldedGraphTypes;
  onShowInGraph: (node: GraphNodeRef) => void;
  /** The loaded overview, for the node panel's relationships fallback. */
  overview?: ForceGraphData;
  /** Show a chunk's file on the Files tab. */
  onOpenInFiles?: (path: string) => void;
}) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const { isDesktop } = useMediaQuery();

  const [query, setQuery] = useState('');
  const debouncedQuery = useDebouncedValue(query.trim(), 300);
  const [typeFilter, setTypeFilter] = useState(ALL_TYPES);
  const [page, setPage] = useState(1);
  const [nodes, setNodes] = useState<GraphNodeSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [types, setTypes] = useState<GraphTypeFacet[]>([]);
  const [status, setStatus] = useState<ListStatus>('loading');
  const [attempt, setAttempt] = useState(0);
  const [selected, setSelected] = useState<GraphNodeRef | null>(null);
  const nodeDetail = useGraphNodeDetail(docId, selected?.id ?? null);

  // A new search or type filter starts on page 1; that page change then
  // fetches, so the old page is never requested with the new filter.
  const filterKey = `${debouncedQuery}\u0000${typeFilter}`;
  const fetchedFilterRef = useRef(filterKey);
  useEffect(() => {
    if (fetchedFilterRef.current !== filterKey) {
      fetchedFilterRef.current = filterKey;
      if (page !== 1) {
        setPage(1);
        return;
      }
    }
    let cancelled = false;
    setStatus('loading');
    userService
      .getSourceGraphNodes(
        docId,
        {
          q: debouncedQuery || undefined,
          type:
            typeFilter === ALL_TYPES
              ? undefined
              : typeFilter === UNTYPED
                ? ''
                : typeFilter,
          page,
          perPage: ENTITIES_PER_PAGE,
        },
        token,
      )
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((body) => {
        if (cancelled) return;
        setNodes(body?.nodes ?? []);
        setTotal(body?.total ?? 0);
        setTypes(body?.types ?? []);
        setStatus('ready');
      })
      .catch((error) => {
        if (cancelled) return;
        console.error('Error loading graph entities:', error);
        setStatus('error');
      });
    return () => {
      cancelled = true;
    };
  }, [docId, filterKey, page, token, attempt]);

  const pageCount = Math.max(1, Math.ceil(total / ENTITIES_PER_PAGE));
  const untypedLabel = t('settings.sources.graphrag.view.untyped');
  const filtered = debouncedQuery !== '' || typeFilter !== ALL_TYPES;

  const panel = selected ? (
    <GraphNodePanel
      key={selected.id}
      docId={docId}
      node={selected}
      detail={nodeDetail.detail}
      status={nodeDetail.status}
      onRetry={nodeDetail.retry}
      fold={fold}
      onClose={() => setSelected(null)}
      showClose={isDesktop}
      onSelectNode={setSelected}
      overview={overview}
      onOpenInFiles={onOpenInFiles}
      onChunkSaved={nodeDetail.reload}
      action={
        <Button
          type="button"
          variant="outline"
          size="sm"
          shape="pill"
          onClick={() => onShowInGraph(selected)}
        >
          <Waypoints />
          {t('settings.sources.graphrag.view.showInGraph')}
        </Button>
      }
    />
  ) : null;

  const body =
    status === 'error' ? (
      <EmptyState
        size="sm"
        tone="destructive"
        illustration="none"
        title={t('settings.sources.graphrag.view.entitiesLoadFailed')}
        action={
          <Button
            type="button"
            variant="outline"
            size="sm"
            shape="pill"
            onClick={() => setAttempt((n) => n + 1)}
          >
            {t('retry')}
          </Button>
        }
      />
    ) : status === 'ready' && nodes.length === 0 ? (
      <EmptyState
        size="xs"
        illustration="none"
        title={
          filtered
            ? t('settings.sources.graphrag.view.noEntities')
            : t('settings.sources.graphrag.view.empty')
        }
      />
    ) : (
      <div className="scrollbar-overlay min-h-0 flex-1 overflow-auto">
        <Table minWidth="min-w-0">
          <TableHead>
            <TableRow>
              <TableHeader>
                {t('settings.sources.graphrag.view.entityName')}
              </TableHeader>
              <TableHeader>{t('settings.sources.type')}</TableHeader>
              <TableHeader align="right">
                {t('settings.sources.graphrag.view.connections')}
              </TableHeader>
              <TableHeader align="right">
                {t('settings.sources.chunks')}
              </TableHeader>
            </TableRow>
          </TableHead>
          <TableBody>
            {status === 'loading'
              ? Array.from({ length: 6 }, (_, index) => (
                  <TableRow key={index}>
                    <TableCell>
                      <Skeleton className="h-3 w-40" />
                    </TableCell>
                    <TableCell>
                      <Skeleton className="h-3 w-20" />
                    </TableCell>
                    <TableCell align="right">
                      <Skeleton className="ml-auto h-3 w-8" />
                    </TableCell>
                    <TableCell align="right">
                      <Skeleton className="ml-auto h-3 w-8" />
                    </TableCell>
                  </TableRow>
                ))
              : nodes.map((node) => (
                  <TableRow
                    key={node.id}
                    selected={selected?.id === node.id}
                    onClick={() =>
                      setSelected({
                        id: node.id,
                        name: node.name,
                        type: node.type,
                      })
                    }
                  >
                    <TableCell className="font-medium wrap-break-word">
                      {node.name}
                    </TableCell>
                    <TableCell>
                      <GraphTypeBadge fold={fold} type={node.type} />
                    </TableCell>
                    <TableCell align="right" className="tabular-nums">
                      {formatCount(node.degree)}
                    </TableCell>
                    <TableCell align="right" className="tabular-nums">
                      {formatCount(node.doc_freq ?? 0)}
                    </TableCell>
                  </TableRow>
                ))}
          </TableBody>
        </Table>
      </div>
    );
  // Kept through a page load (the previous page's rows stay until the next
  // arrive), so Prev / Next do not shift the layout.
  const showPager = status !== 'error' && nodes.length > 0;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="w-full sm:w-72">
          <SearchInput
            label={t('settings.sources.graphrag.view.findEntity')}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <Select value={typeFilter} onValueChange={setTypeFilter}>
          <SelectTrigger
            size="field"
            shape="pill"
            className="w-full sm:w-56"
            aria-label={t('settings.sources.type')}
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_TYPES}>
              {t('settings.sources.graphrag.view.allTypes')}
            </SelectItem>
            {types.map((facet) => (
              <SelectItem
                key={facet.key || UNTYPED}
                value={facet.key || UNTYPED}
              >
                {facet.key ? (facet.label ?? facet.key) : untypedLabel}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <Card
        variant="subtle"
        padding="none"
        className="h-[70svh] flex-row gap-0 overflow-hidden"
      >
        <div className="flex min-w-0 flex-1 flex-col justify-center">
          {body}
        </div>
        {isDesktop && panel ? (
          <GraphNodePanelDock>{panel}</GraphNodePanelDock>
        ) : null}
      </Card>
      {showPager ? (
        <Pagination
          page={page}
          pageCount={pageCount}
          onPageChange={setPage}
          summary={t('settings.sources.graphrag.view.entityCount', {
            count: total,
            formatted: formatCount(total),
          })}
        />
      ) : null}
      {!isDesktop ? (
        <Sheet
          open={!!selected}
          onOpenChange={(open) => {
            if (!open) setSelected(null);
          }}
        >
          <SheetContent
            side="bottom"
            handle
            title={selected?.name}
            // Open on the panel, not with a ring on its first control.
            onOpenAutoFocus={(event) => event.preventDefault()}
          >
            {panel}
          </SheetContent>
        </Sheet>
      ) : null}
    </div>
  );
}
