import { forceCollide, type SimulationNodeDatum } from 'd3-force';
import { ArrowLeft, Network, X } from 'lucide-react';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import ForceGraph2D, { type ForceGraphMethods } from 'react-force-graph-2d';

import userService from '../api/services/userService';
import { selectToken } from '../preferences/preferenceSlice';
import { useThemeVersion } from '../utils/chartUtils';
import { Badge } from './ui/badge';
import { IconButton } from './ui/icon-button';
import { SectionHeader } from './ui/section-header';
import SkeletonLoader from './SkeletonLoader';
import {
  ForceGraphData,
  GraphNode,
  GraphNodeDetail,
  GraphOverview,
  collideRadius,
  maxDegree,
  nodeAtPoint,
  nodeRadius,
  readGraphPalette,
  toForceGraphData,
} from './graphViewUtils';

interface GraphViewProps {
  docId: string;
  sourceName: string;
  onBackToDocuments: () => void;
  /** Extra header control, right-aligned in the title row. */
  headerAction?: React.ReactNode;
}

const GRAPH_LIMIT = 100;
const HIT_SLOP = 4;

const GraphView: React.FC<GraphViewProps> = ({
  docId,
  sourceName,
  onBackToDocuments,
  headerAction,
}) => {
  const { t } = useTranslation();
  const token = useSelector(selectToken);

  const [data, setData] = useState<ForceGraphData>({ nodes: [], links: [] });
  const [loading, setLoading] = useState(true);
  const [selectedNode, setSelectedNode] = useState<GraphNodeDetail | null>(
    null,
  );
  const [loadingNode, setLoadingNode] = useState(false);

  const containerRef = useRef<HTMLDivElement>(null);
  const hoveredNodeIdRef = useRef<string | null>(null);
  const fgRef = useRef<ForceGraphMethods | undefined>(undefined);
  const [size, setSize] = useState({ width: 0, height: 480 });
  // The canvas can't read CSS variables: resolve the tokens, and re-read them
  // whenever the theme changes.
  const themeVersion = useThemeVersion();
  // themeVersion is not used inside the factory: it only signals a change.
  const palette = useMemo(() => readGraphPalette(), [themeVersion]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    userService
      .getSourceGraph(docId, token, GRAPH_LIMIT)
      .then((response) => response.json())
      .then((body) => {
        if (cancelled) return;
        const overview: GraphOverview = {
          nodes: body?.nodes ?? [],
          edges: body?.edges ?? [],
        };
        setData(toForceGraphData(overview));
      })
      .catch((error) => console.error('Error loading graph:', error))
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [docId, token]);

  useEffect(() => {
    if (!containerRef.current) return;
    const element = containerRef.current;
    const observer = new ResizeObserver(() => {
      setSize({ width: element.clientWidth, height: 480 });
    });
    observer.observe(element);
    setSize({ width: element.clientWidth, height: 480 });
    return () => observer.disconnect();
  }, [loading, data.nodes.length]);

  const maxNodeDegree = useMemo(() => maxDegree(data.nodes), [data.nodes]);

  useEffect(() => {
    if (!fgRef.current || data.nodes.length === 0) return;
    fgRef.current.d3Force(
      'collide',
      forceCollide<SimulationNodeDatum>((node) =>
        collideRadius(nodeRadius((node as GraphNode).degree, maxNodeDegree)),
      ),
    );
    fgRef.current.d3ReheatSimulation();
  }, [data, maxNodeDegree, size.width]);

  const handleNodeClick = (node: GraphNode) => {
    setLoadingNode(true);
    setSelectedNode(null);
    userService
      .getSourceGraphNode(docId, node.id, token)
      .then((response) => response.json())
      .then((body) => {
        if (body?.node) setSelectedNode(body.node as GraphNodeDetail);
      })
      .catch((error) => console.error('Error loading graph node:', error))
      .finally(() => setLoadingNode(false));
  };

  // Geometric hit test, immune to canvas read-back farbling (e.g. Brave): map
  // the pointer into graph coordinates and pick the nearest node directly.
  const pickNodeAt = (clientX: number, clientY: number): GraphNode | null => {
    const fg = fgRef.current;
    if (!fg || !containerRef.current) return null;
    const rect = containerRef.current.getBoundingClientRect();
    const g = fg.screen2GraphCoords(clientX - rect.left, clientY - rect.top);
    return nodeAtPoint(data.nodes, g.x, g.y, maxNodeDegree, HIT_SLOP);
  };

  const repaint = () => {
    const fg = fgRef.current;
    if (fg) fg.zoom(fg.zoom());
  };

  // A settled simulation stops drawing, so paint the new colours once.
  useEffect(() => {
    repaint();
  }, [palette]);

  const handlePointerMove = (event: React.MouseEvent<HTMLDivElement>) => {
    const node = pickNodeAt(event.clientX, event.clientY);
    if (containerRef.current) {
      containerRef.current.style.cursor = node ? 'pointer' : 'default';
    }
    const nextId = node?.id ?? null;
    if (nextId !== hoveredNodeIdRef.current) {
      hoveredNodeIdRef.current = nextId;
      repaint();
    }
  };

  const handlePointerLeave = () => {
    if (containerRef.current) containerRef.current.style.cursor = 'default';
    if (hoveredNodeIdRef.current !== null) {
      hoveredNodeIdRef.current = null;
      repaint();
    }
  };

  const handleContainerClick = (event: React.MouseEvent<HTMLDivElement>) => {
    const node = pickNodeAt(event.clientX, event.clientY);
    if (node) handleNodeClick(node);
  };

  const isEmpty = !loading && data.nodes.length === 0;

  return (
    <div className="flex flex-col">
      <div className="mb-4 flex items-center">
        <IconButton
          variant="outline"
          size="icon-xs"
          shape="pill"
          className="mr-3"
          onClick={onBackToDocuments}
          label={t('settings.sources.backToAll')}
          icon={ArrowLeft}
          side="bottom"
        />
        <span className="text-primary font-semibold wrap-break-word">
          {sourceName}
        </span>
        {headerAction ? <div className="ml-auto">{headerAction}</div> : null}
      </div>

      <div className="bg-muted text-muted-foreground mb-4 flex items-start gap-2 rounded-xl px-4 py-3 text-xs">
        <Network className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <p>
          <span className="text-foreground font-medium">
            {t('settings.sources.graphrag.view.title')}
          </span>{' '}
          {t('settings.sources.graphrag.view.explainer')}
        </p>
      </div>

      {loading ? (
        <SkeletonLoader count={4} />
      ) : isEmpty ? (
        <div className="border-border text-muted-foreground flex flex-col items-center gap-2 rounded-xl border border-dashed px-6 py-12 text-center text-sm">
          <Network className="size-7" aria-hidden="true" />
          <p>{t('settings.sources.graphrag.view.empty')}</p>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <p className="text-muted-foreground text-xs">
            {t('settings.sources.graphrag.view.stats', {
              nodes: data.nodes.length,
              edges: data.links.length,
            })}
          </p>
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
            <div
              ref={containerRef}
              onMouseMove={handlePointerMove}
              onMouseLeave={handlePointerLeave}
              onClick={handleContainerClick}
              className="border-border bg-card relative min-h-[480px] flex-1 overflow-hidden rounded-xl border"
            >
              {size.width > 0 && (
                <ForceGraph2D
                  ref={fgRef}
                  graphData={data}
                  width={size.width}
                  height={size.height}
                  nodeRelSize={1}
                  enablePointerInteraction={false}
                  enableNodeDrag={false}
                  nodeVal={(node) =>
                    nodeRadius((node as GraphNode).degree, maxNodeDegree)
                  }
                  linkColor={() => palette.link}
                  cooldownTicks={80}
                  nodeCanvasObject={(node, ctx, globalScale) => {
                    const graphNode = node as GraphNode & {
                      x?: number;
                      y?: number;
                    };
                    if (graphNode.x == null) return;
                    const r = nodeRadius(graphNode.degree, maxNodeDegree);
                    const hovered = hoveredNodeIdRef.current === graphNode.id;
                    ctx.beginPath();
                    ctx.arc(graphNode.x, graphNode.y ?? 0, r, 0, 2 * Math.PI);
                    ctx.fillStyle = palette.node;
                    ctx.fill();
                    if (hovered) {
                      ctx.lineWidth = 2 / globalScale;
                      ctx.strokeStyle = palette.hoverStroke;
                      ctx.stroke();
                    }
                    if (globalScale >= 1.2) {
                      const label = graphNode.name ?? '';
                      const x = graphNode.x;
                      const y = (graphNode.y ?? 0) + r + 1;
                      ctx.font = `${10 / globalScale}px sans-serif`;
                      ctx.textAlign = 'center';
                      ctx.textBaseline = 'top';
                      ctx.lineWidth = 3 / globalScale;
                      ctx.lineJoin = 'round';
                      ctx.strokeStyle = palette.halo;
                      ctx.strokeText(label, x, y);
                      ctx.fillStyle = palette.label;
                      ctx.fillText(label, x, y);
                    }
                  }}
                />
              )}
            </div>

            <aside className="border-border bg-card flex max-h-[480px] w-full shrink-0 flex-col overflow-y-auto rounded-xl border p-4 lg:w-80">
              {loadingNode ? (
                <SkeletonLoader count={3} />
              ) : selectedNode ? (
                <div className="flex flex-col">
                  <div className="mb-2 flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <SectionHeader
                        as="h3"
                        size="xs"
                        className="wrap-break-word"
                        title={selectedNode.name}
                      />
                      {selectedNode.type && (
                        <Badge variant="neutral" className="mt-1">
                          {selectedNode.type}
                        </Badge>
                      )}
                    </div>
                    <IconButton
                      variant="ghost-muted"
                      size="icon-xs"
                      className="shrink-0"
                      onClick={() => setSelectedNode(null)}
                      label={t('settings.sources.graphrag.view.close')}
                      icon={X}
                      side="bottom"
                    />
                  </div>

                  {selectedNode.description && (
                    <p className="text-muted-foreground mb-3 text-sm leading-relaxed wrap-break-word">
                      {selectedNode.description}
                    </p>
                  )}

                  <div className="flex flex-col gap-2">
                    <SectionHeader
                      as="h4"
                      size="xs"
                      title={t('settings.sources.graphrag.view.linkedChunks')}
                    />
                    {selectedNode.chunks.length === 0 ? (
                      <p className="text-muted-foreground text-xs">
                        {t('settings.sources.graphrag.view.noChunks')}
                      </p>
                    ) : (
                      <ul className="flex flex-col gap-2">
                        {selectedNode.chunks.map((chunk) => (
                          <li
                            key={chunk.chunk_id}
                            className="border-border text-muted-foreground rounded-md border px-3 py-2 text-xs leading-relaxed wrap-break-word"
                          >
                            {chunk.text}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              ) : (
                <p className="text-muted-foreground py-2 text-sm">
                  {t('settings.sources.graphrag.view.selectNode')}
                </p>
              )}
            </aside>
          </div>
        </div>
      )}
    </div>
  );
};

export default GraphView;
