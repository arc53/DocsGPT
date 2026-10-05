import { forceCollide, type SimulationNodeDatum } from 'd3-force';
import React, {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useTranslation } from 'react-i18next';
import ForceGraph2D, {
  type ForceGraphMethods,
  type LinkObject,
  type NodeObject,
} from 'react-force-graph-2d';

import { useThemeVersion } from '../utils/chartUtils';
import { formatCount } from '../utils/dateTimeUtils';
import GraphCanvasControls from './graph/GraphCanvasControls';
import GraphEntitySearch from './graph/GraphEntitySearch';
import GraphNodePanel, { type GraphNodeRef } from './graph/GraphNodePanel';
import { GraphSeriesDot } from './graph/GraphTypeDot';
import {
  DIM_ALPHA,
  OTHER_GROUP_KEY,
  buildAdjacency,
  endpointId,
  focusSet,
  legendGroupOf,
  linkTouches,
  nodeHasLabel,
  pickLabels,
  topHubIds,
  type LabelBox,
} from './graph/graphCanvasUtils';
import { useGraphNodeDetail } from './graph/useGraphNodeDetail';
import { Card } from './ui/card';
import { EmptyState } from './ui/empty-state';
import { LoadingState } from './ui/loading-state';
import { SidePanel } from './ui/side-panel';
import { ToggleGroup, ToggleGroupItem } from './ui/toggle-group';
import {
  type FoldedGraphTypes,
  type ForceGraphData,
  type GraphEdge,
  type GraphNode,
  collideRadius,
  escapeDeselects,
  maxDegree,
  nodeAtPoint,
  nodeRadius,
  otherTypesList,
  readGraphPalette,
} from './graphViewUtils';

/** The overview sizes the "Show top" control offers. */
const GRAPH_LIMITS = [50, 100, 250] as const;

export type GraphLoadStatus = 'loading' | 'error' | 'ready';

interface GraphViewProps {
  docId: string;
  /** The loaded overview (top nodes by degree and the edges among them). */
  data: ForceGraphData;
  /** The one type fold shared with the header, the entity list and the panel. */
  fold: FoldedGraphTypes;
  status: GraphLoadStatus;
  onRetry: () => void;
  limit: number;
  onLimitChange: (limit: number) => void;
  selected: GraphNodeRef | null;
  onSelect: (node: GraphNodeRef | null) => void;
  /** False while another tab is showing; Escape then leaves the selection alone. */
  active?: boolean;
  /** Show a chunk's file on the Files tab (the chunk drawer's "Open in Files"). */
  onOpenInFiles?: (path: string) => void;
  /** Whether the chunk drawer offers Edit (`can(source, 'edit')`). */
  canEdit?: boolean;
}

type PositionedNode = NodeObject<GraphNode> & { x?: number; y?: number };

const HIT_SLOP = 4;
const ZOOM_STEP = 1.3;
const ZOOM_MS = 200;
const FOCUS_MS = 400;
const FOCUS_ZOOM = 2;
const FIT_PADDING = 40;
const LABEL_PX = 11;
/** Screen-pixel clearance kept between two labels. */
const LABEL_GAP_PX = 2;

/**
 * The Graph tab of a knowledge-graph source: entity search, the "Show top"
 * size, the type legend (a filter), and the canvas with its controls and the
 * node's docked side panel (a full-width sheet on a phone).
 */
const GraphView: React.FC<GraphViewProps> = ({
  docId,
  data,
  fold,
  status,
  onRetry,
  limit,
  onLimitChange,
  selected,
  onSelect,
  active = true,
  onOpenInFiles,
  canEdit = true,
}) => {
  const { t } = useTranslation();
  const showTopId = useId();

  const containerRef = useRef<HTMLDivElement>(null);
  const fgRef = useRef<ForceGraphMethods<GraphNode, GraphEdge> | undefined>(
    undefined,
  );
  const hoveredIdRef = useRef<string | null>(null);
  const fittedRef = useRef(false);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [zoom, setZoom] = useState(1);
  const [hidden, setHidden] = useState<Set<string>>(() => new Set());

  // The canvas can't read CSS variables: resolve the tokens, and re-read them
  // whenever the theme changes.
  const themeVersion = useThemeVersion();
  // themeVersion is not used inside the factory: it only signals a change.
  const palette = useMemo(() => readGraphPalette(), [themeVersion]);
  const fadedLink = `color-mix(in srgb, ${palette.link} 15%, transparent)`;

  const selectedId = selected?.id ?? null;
  const nodeDetail = useGraphNodeDetail(docId, selectedId);

  const maxNodeDegree = useMemo(() => maxDegree(data.nodes), [data.nodes]);
  const nodeById = useMemo(
    () => new Map(data.nodes.map((node) => [node.id, node])),
    [data.nodes],
  );
  const loadedIds = useMemo(() => new Set(nodeById.keys()), [nodeById]);
  const adjacency = useMemo(() => buildAdjacency(data.links), [data.links]);
  const focus = useMemo(
    () => focusSet(selectedId, adjacency, loadedIds),
    [selectedId, adjacency, loadedIds],
  );

  const legendKeys = useMemo(
    () => [
      ...fold.groups.map((group) => group.key),
      ...(fold.other.count > 0 ? [OTHER_GROUP_KEY] : []),
    ],
    [fold],
  );

  const isVisible = useCallback(
    (node: GraphNode | undefined) =>
      !!node && !hidden.has(legendGroupOf(fold, node.type)),
    [fold, hidden],
  );
  const visibleNodes = useMemo(
    () => data.nodes.filter((node) => isVisible(node)),
    [data.nodes, isVisible],
  );

  // The busiest of what's shown keep their labels.
  const hubs = useMemo(() => topHubIds(visibleNodes), [visibleNodes]);

  // A new overview (another "Show top") starts with a fresh fit.
  useEffect(() => {
    fittedRef.current = false;
  }, [data]);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const measure = () => {
      // A hidden tab measures 0: keep the last size so the canvas survives.
      if (element.clientWidth === 0) return;
      setSize({ width: element.clientWidth, height: element.clientHeight });
    };
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    measure();
    return () => observer.disconnect();
  }, [status, data.nodes.length]);

  const hasCanvas = size.width > 0;
  useEffect(() => {
    if (!fgRef.current || data.nodes.length === 0) return;
    fgRef.current.d3Force(
      'collide',
      forceCollide<SimulationNodeDatum>((node) =>
        collideRadius(nodeRadius((node as GraphNode).degree, maxNodeDegree)),
      ),
    );
    fgRef.current.d3ReheatSimulation();
  }, [data, maxNodeDegree, hasCanvas]);

  // A settled simulation stops drawing, so paint changes once.
  const repaint = useCallback(() => {
    const fg = fgRef.current;
    if (fg) fg.zoom(fg.zoom());
  }, []);

  useEffect(() => {
    repaint();
  }, [palette, focus, hidden, fold, repaint]);

  const fitView = useCallback(
    (durationMs = FOCUS_MS) => {
      fgRef.current?.zoomToFit(durationMs, FIT_PADDING, (node) =>
        isVisible(node as GraphNode),
      );
    },
    [isVisible],
  );

  // Centre the selection; zoom in once per new selection. Re-centre when the
  // docked panel changes the canvas width.
  const zoomedForRef = useRef<string | null>(null);
  const hadSelectionRef = useRef(false);
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    if (!selectedId) {
      zoomedForRef.current = null;
      if (!hadSelectionRef.current) return;
      hadSelectionRef.current = false;
      // Deselecting hands the width back to the canvas: refit.
      const frame = requestAnimationFrame(() => fitView());
      return () => cancelAnimationFrame(frame);
    }
    hadSelectionRef.current = true;
    const node = nodeById.get(selectedId) as PositionedNode | undefined;
    if (!node || node.x == null || node.y == null) return;
    const { x, y } = node;
    const frame = requestAnimationFrame(() => {
      fg.centerAt(x, y, FOCUS_MS);
      if (zoomedForRef.current !== selectedId) {
        zoomedForRef.current = selectedId;
        fg.zoom(Math.max(fg.zoom(), FOCUS_ZOOM), FOCUS_MS);
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [selectedId, nodeById, size.width, fitView]);

  useEffect(() => {
    if (!active || !selectedId) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (escapeDeselects(event)) onSelect(null);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [active, selectedId, onSelect]);

  // Geometric hit test, immune to canvas read-back farbling (e.g. Brave): map
  // the pointer into graph coordinates and pick the nearest visible node.
  const pickNodeAt = (clientX: number, clientY: number): GraphNode | null => {
    const fg = fgRef.current;
    if (!fg || !containerRef.current) return null;
    const rect = containerRef.current.getBoundingClientRect();
    const g = fg.screen2GraphCoords(clientX - rect.left, clientY - rect.top);
    return nodeAtPoint(visibleNodes, g.x, g.y, maxNodeDegree, HIT_SLOP);
  };

  const onCanvas = (event: React.MouseEvent) =>
    event.target instanceof HTMLCanvasElement;

  const handlePointerMove = (event: React.MouseEvent<HTMLDivElement>) => {
    const node = onCanvas(event)
      ? pickNodeAt(event.clientX, event.clientY)
      : null;
    if (containerRef.current) {
      containerRef.current.style.cursor = node ? 'pointer' : 'default';
    }
    const nextId = node?.id ?? null;
    if (nextId !== hoveredIdRef.current) {
      hoveredIdRef.current = nextId;
      repaint();
    }
  };

  const handlePointerLeave = () => {
    if (containerRef.current) containerRef.current.style.cursor = 'default';
    if (hoveredIdRef.current !== null) {
      hoveredIdRef.current = null;
      repaint();
    }
  };

  const handleContainerClick = (event: React.MouseEvent<HTMLDivElement>) => {
    // Clicks on the controls strip are not canvas clicks.
    if (!onCanvas(event)) return;
    const node = pickNodeAt(event.clientX, event.clientY);
    if (node) onSelect({ id: node.id, name: node.name, type: node.type });
    else if (selectedId) onSelect(null);
  };

  const nodeVisibility = useCallback(
    (node: NodeObject<GraphNode>) => isVisible(node as GraphNode),
    [isVisible],
  );
  const linkVisibility = useCallback(
    (link: LinkObject<GraphNode, GraphEdge>) =>
      isVisible(nodeById.get(endpointId(link.source as never))) &&
      isVisible(nodeById.get(endpointId(link.target as never))),
    [isVisible, nodeById],
  );
  const linkColor = useCallback(
    (link: LinkObject<GraphNode, GraphEdge>) => {
      if (!focus) return palette.link;
      return linkTouches(link as GraphEdge, selectedId)
        ? palette.primary
        : fadedLink;
    },
    [focus, selectedId, palette, fadedLink],
  );
  const linkWidth = useCallback(
    (link: LinkObject<GraphNode, GraphEdge>) =>
      focus && linkTouches(link as GraphEdge, selectedId) ? 1.5 : 1,
    [focus, selectedId],
  );
  const nodeVal = useCallback(
    (node: NodeObject<GraphNode>) =>
      nodeRadius((node as GraphNode).degree, maxNodeDegree),
    [maxNodeDegree],
  );

  const nodeCanvasObject = useCallback(
    (
      node: NodeObject<GraphNode>,
      ctx: CanvasRenderingContext2D,
      globalScale: number,
    ) => {
      const graphNode = node as PositionedNode;
      if (graphNode.x == null || graphNode.y == null) return;
      const { x, y } = graphNode;
      const r = nodeRadius(graphNode.degree, maxNodeDegree);
      const hoveredId = hoveredIdRef.current;
      const isSelected = graphNode.id === selectedId;
      const series = fold.seriesOf(graphNode.type);

      ctx.save();
      ctx.globalAlpha = focus && !focus.has(graphNode.id) ? DIM_ALPHA : 1;
      ctx.beginPath();
      ctx.arc(x, y, r, 0, 2 * Math.PI);
      ctx.fillStyle =
        series == null
          ? palette.other
          : (palette.series[series] ?? palette.other);
      ctx.fill();
      if (isSelected || graphNode.id === hoveredId) {
        ctx.lineWidth = (isSelected ? 2.5 : 1.5) / globalScale;
        ctx.strokeStyle = palette.hoverStroke;
        ctx.stroke();
      }
      ctx.restore();
    },
    [maxNodeDegree, selectedId, fold, focus, palette],
  );

  // Labels go on top of every node (a per-node label would sit under the
  // nodes drawn after it): one pass after the frame. In priority order (the
  // selection, the hovered node, then by degree) a label that would sit on
  // one already placed is skipped; the first two always draw.
  const drawLabels = useCallback(
    (ctx: CanvasRenderingContext2D, globalScale: number) => {
      const hoveredId = hoveredIdRef.current;
      const rank = (node: GraphNode) =>
        node.id === selectedId ? 0 : node.id === hoveredId ? 1 : 2;
      const labelled = (visibleNodes as PositionedNode[])
        .filter(
          (node) =>
            node.x != null &&
            node.y != null &&
            nodeHasLabel(node.id, { hubs, focus, hoveredId }),
        )
        .sort(
          (a, b) =>
            rank(a) - rank(b) ||
            (b.degree || 0) - (a.degree || 0) ||
            a.id.localeCompare(b.id),
        );
      ctx.save();
      ctx.font = `${LABEL_PX / globalScale}px ${palette.font}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.lineWidth = 3 / globalScale;
      ctx.lineJoin = 'round';
      const boxes: (LabelBox & { label: string })[] = labelled.map((node) => {
        const label = node.name ?? '';
        return {
          id: node.id,
          label,
          x: node.x as number,
          y:
            (node.y as number) +
            nodeRadius(node.degree, maxNodeDegree) +
            2 / globalScale,
          width: ctx.measureText(label).width,
          height: LABEL_PX / globalScale,
          always: rank(node) < 2,
        };
      });
      const shown = pickLabels(boxes, LABEL_GAP_PX / globalScale);
      for (const box of boxes) {
        if (!shown.has(box.id)) continue;
        ctx.strokeStyle = palette.halo;
        ctx.strokeText(box.label, box.x, box.y);
        ctx.fillStyle = palette.label;
        ctx.fillText(box.label, box.x, box.y);
      }
      ctx.restore();
    },
    [visibleNodes, hubs, focus, maxNodeDegree, palette, selectedId],
  );

  // Once a new layout settles: fit it, or, with a node selected, centre on
  // that node (its position only exists now; the focus effect ran before).
  const handleEngineStop = useCallback(() => {
    if (fittedRef.current) return;
    fittedRef.current = true;
    const node = selectedId
      ? (nodeById.get(selectedId) as PositionedNode | undefined)
      : undefined;
    if (node && node.x != null && node.y != null) {
      fgRef.current?.centerAt(node.x, node.y, FOCUS_MS);
    } else {
      fitView();
    }
  }, [fitView, selectedId, nodeById]);

  // The graph reports zoom while it renders (a prop update can move the
  // view), so the readout follows on the next frame, at most once a frame.
  const zoomFrameRef = useRef<number | null>(null);
  const handleZoom = useCallback(({ k }: { k: number }) => {
    if (zoomFrameRef.current !== null)
      cancelAnimationFrame(zoomFrameRef.current);
    zoomFrameRef.current = requestAnimationFrame(() => {
      zoomFrameRef.current = null;
      setZoom(k);
    });
  }, []);
  useEffect(
    () => () => {
      if (zoomFrameRef.current !== null)
        cancelAnimationFrame(zoomFrameRef.current);
    },
    [],
  );

  const zoomBy = (factor: number) => {
    const fg = fgRef.current;
    if (fg) fg.zoom(fg.zoom() * factor, ZOOM_MS);
  };

  const legendValue = legendKeys.filter((key) => !hidden.has(key));
  const otherLabels = fold.other.labels;

  const toolbar = (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <GraphEntitySearch docId={docId} fold={fold} onPick={onSelect} />
        {/* One phrase at one size: "Show top [50 | 100 | 250] by
            connections"; the group's track holds only the numbers. */}
        <div className="flex flex-wrap items-center gap-2">
          <span id={showTopId} className="text-muted-foreground text-sm">
            {t('settings.sources.graphrag.view.showTop')}
          </span>
          <ToggleGroup
            className="shrink-0"
            type="single"
            size="xs"
            value={String(limit)}
            onValueChange={(value) => value && onLimitChange(Number(value))}
            aria-labelledby={showTopId}
          >
            {GRAPH_LIMITS.map((option) => (
              <ToggleGroupItem key={option} value={String(option)}>
                {option}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <span className="text-muted-foreground text-sm">
            {t('settings.sources.graphrag.view.byConnections')}
          </span>
        </div>
      </div>
      {legendKeys.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2">
          <ToggleGroup
            type="multiple"
            size="xs"
            value={legendValue}
            onValueChange={(values) =>
              setHidden(
                new Set(legendKeys.filter((key) => !values.includes(key))),
              )
            }
            aria-label={t('settings.sources.graphrag.view.typeFilter')}
          >
            {fold.groups.map((group) => (
              <ToggleGroupItem key={group.key} value={group.key}>
                <GraphSeriesDot series={group.series} />
                {group.label}
                <span className="text-muted-foreground tabular-nums">
                  {formatCount(group.count)}
                </span>
              </ToggleGroupItem>
            ))}
            {fold.other.count > 0 ? (
              <ToggleGroupItem value={OTHER_GROUP_KEY}>
                <GraphSeriesDot series={null} />
                {t('settings.analytics.otherSeries')}
                <span className="text-muted-foreground tabular-nums">
                  {formatCount(fold.other.count)}
                </span>
              </ToggleGroupItem>
            ) : null}
          </ToggleGroup>
          {otherLabels.length > 0 ? (
            <span className="text-muted-foreground text-xs">
              {t('settings.sources.graphrag.view.otherTypes', {
                types: otherTypesList(otherLabels, (count) =>
                  t('settings.sources.graphrag.view.otherTypesMore', {
                    count,
                    formatted: formatCount(count),
                  }),
                ),
                interpolation: { escapeValue: false },
              })}
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );

  if (status === 'error') {
    return (
      <EmptyState
        size="sm"
        tone="destructive"
        illustration="none"
        title={t('settings.sources.graphrag.view.loadFailed')}
        onRetry={onRetry}
      />
    );
  }

  if (status === 'ready' && data.nodes.length === 0) {
    return (
      <EmptyState
        size="sm"
        illustration="none"
        title={t('settings.sources.graphrag.view.empty')}
      />
    );
  }

  const panel = selected ? (
    <GraphNodePanel
      key={selected.id}
      docId={docId}
      node={selected}
      detail={nodeDetail.detail}
      status={nodeDetail.status}
      onRetry={nodeDetail.retry}
      fold={fold}
      onSelectNode={onSelect}
      overview={data}
      onOpenInFiles={onOpenInFiles}
      onChunkSaved={nodeDetail.reload}
      canEdit={canEdit}
    />
  ) : null;

  return (
    <div className="flex flex-col gap-4">
      {toolbar}
      <Card
        variant="subtle"
        padding="none"
        className="relative h-[70svh] flex-row gap-0 overflow-hidden"
      >
        <div
          ref={containerRef}
          onMouseMove={handlePointerMove}
          onMouseLeave={handlePointerLeave}
          onClick={handleContainerClick}
          className="relative min-w-0 flex-1"
        >
          {status === 'loading' ? (
            <LoadingState fill="parent" />
          ) : (
            <>
              {hasCanvas && (
                <ForceGraph2D<GraphNode, GraphEdge>
                  ref={fgRef}
                  graphData={data}
                  width={size.width}
                  height={size.height}
                  nodeRelSize={1}
                  minZoom={0.2}
                  maxZoom={8}
                  enablePointerInteraction={false}
                  enableNodeDrag={false}
                  nodeVal={nodeVal}
                  nodeVisibility={nodeVisibility}
                  linkVisibility={linkVisibility}
                  linkColor={linkColor}
                  linkWidth={linkWidth}
                  cooldownTicks={80}
                  onEngineStop={handleEngineStop}
                  onZoom={handleZoom}
                  nodeCanvasObject={nodeCanvasObject}
                  onRenderFramePost={drawLabels}
                />
              )}
              {!selected ? (
                <p className="text-muted-foreground pointer-events-none absolute top-3 left-3 text-xs">
                  {t('settings.sources.graphrag.view.selectNode')}
                </p>
              ) : null}
              <GraphCanvasControls
                zoom={zoom}
                onZoomIn={() => zoomBy(ZOOM_STEP)}
                onZoomOut={() => zoomBy(1 / ZOOM_STEP)}
                onFit={() => fitView()}
              />
            </>
          )}
        </div>
        <SidePanel
          variant="docked"
          expandable="graph-node"
          open={!!panel && active}
          onOpenChange={(open) => {
            if (!open) onSelect(null);
          }}
        >
          {panel}
        </SidePanel>
      </Card>
    </div>
  );
};

export default GraphView;
