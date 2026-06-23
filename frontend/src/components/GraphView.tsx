import { forceCollide, type SimulationNodeDatum } from 'd3-force';
import { Network, X } from 'lucide-react';
import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import ForceGraph2D, { type ForceGraphMethods } from 'react-force-graph-2d';

import userService from '../api/services/userService';
import ArrowLeft from '../assets/arrow-left.svg';
import { selectToken } from '../preferences/preferenceSlice';
import { Button } from './ui/button';
import SkeletonLoader from './SkeletonLoader';
import {
  ForceGraphData,
  GraphNode,
  GraphNodeDetail,
  GraphOverview,
  collideRadius,
  maxDegree,
  nodeLabelEl,
  nodeRadius,
  pointerAreaRadius,
  toForceGraphData,
} from './graphViewUtils';

interface GraphViewProps {
  docId: string;
  sourceName: string;
  onBackToDocuments: () => void;
}

const GRAPH_LIMIT = 100;

const GraphView: React.FC<GraphViewProps> = ({
  docId,
  sourceName,
  onBackToDocuments,
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
  // Bumped after zoom/pan settles to re-supply nodePointerAreaPaint, which makes
  // force-graph repaint the hit-test (pick) canvas immediately. The engine
  // otherwise throttles that repaint by 800ms, leaving the pick discs at their
  // pre-zoom positions — so just after a zoom the cursor reads stale/empty
  // pixels and hover/click silently fail. The miss scales with the screen
  // distance a node moved (largest for the biggest, highest-degree hubs) and is
  // doubled on Retina, where each pick reads a single device pixel.
  const [pickRefresh, setPickRefresh] = useState(0);

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

  // Paints the hit-test (pick) disc for a node. Its identity is keyed on
  // `pickRefresh` so re-supplying it after a zoom/pan settles forces force-graph
  // to repaint the pick canvas immediately rather than after its 800ms throttle.
  const nodePointerAreaPaint = useCallback(
    (node: object, color: string, ctx: CanvasRenderingContext2D) => {
      const graphNode = node as GraphNode & { x?: number; y?: number };
      if (graphNode.x == null || graphNode.y == null) return;
      const r = pointerAreaRadius(nodeRadius(graphNode.degree, maxNodeDegree));
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(graphNode.x, graphNode.y, r, 0, 2 * Math.PI);
      ctx.fill();
    },
    // pickRefresh is an intentional dependency: bumping it re-supplies this
    // callback, which makes force-graph flush the pick canvas after a zoom/pan.
    [maxNodeDegree, pickRefresh],
  );

  const isEmpty = !loading && data.nodes.length === 0;

  return (
    <div className="flex flex-col">
      <div className="mb-4 flex items-center">
        <Button
          type="button"
          variant="outline"
          size="icon-sm"
          className="text-muted-foreground mr-3 h-[29px] w-[29px] rounded-full p-2 dark:border-0"
          onClick={onBackToDocuments}
          aria-label={t('settings.sources.backToAll')}
        >
          <img src={ArrowLeft} alt="left-arrow" className="h-3 w-3" />
        </Button>
        <span className="text-primary font-semibold wrap-break-word">
          {sourceName}
        </span>
      </div>

      <div className="bg-muted/60 text-muted-foreground dark:bg-accent/40 mb-4 flex items-start gap-2 rounded-xl px-4 py-3 text-xs">
        <Network
          size={16}
          strokeWidth={1.75}
          className="mt-0.5 shrink-0"
          aria-hidden="true"
        />
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
          <Network size={28} strokeWidth={1.5} aria-hidden="true" />
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
          <div className="flex flex-col gap-4 lg:flex-row">
            <div
              ref={containerRef}
              className="border-border bg-card relative min-h-[480px] flex-1 overflow-hidden rounded-xl border"
            >
              {size.width > 0 && (
                <ForceGraph2D
                  ref={fgRef}
                  graphData={data}
                  width={size.width}
                  height={size.height}
                  nodeRelSize={1}
                  nodeVal={(node) =>
                    nodeRadius((node as GraphNode).degree, maxNodeDegree)
                  }
                  nodeLabel={(node) =>
                    nodeLabelEl(
                      (node as GraphNode).name,
                    ) as unknown as React.ReactHTMLElement<HTMLElement>
                  }
                  linkColor={() => 'rgba(150,150,150,0.35)'}
                  linkPointerAreaPaint={() => {}}
                  cooldownTicks={80}
                  onEngineStop={() => {
                    const fg = fgRef.current;
                    if (!fg) return;
                    fg.zoom(fg.zoom());
                    setPickRefresh((n) => n + 1);
                  }}
                  onZoomEnd={() => setPickRefresh((n) => n + 1)}
                  onNodeClick={(node) => handleNodeClick(node as GraphNode)}
                  onNodeHover={(node) => {
                    hoveredNodeIdRef.current = node
                      ? (node as GraphNode).id
                      : null;
                    if (containerRef.current) {
                      containerRef.current.style.cursor = node
                        ? 'pointer'
                        : 'default';
                    }
                  }}
                  nodePointerAreaPaint={nodePointerAreaPaint}
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
                    ctx.fillStyle = hovered ? '#7aa7d9' : '#4a7fb5';
                    ctx.fill();
                    if (globalScale >= 1.2) {
                      const label = graphNode.name ?? '';
                      const x = graphNode.x;
                      const y = (graphNode.y ?? 0) + r + 1;
                      ctx.font = `${10 / globalScale}px sans-serif`;
                      ctx.textAlign = 'center';
                      ctx.textBaseline = 'top';
                      ctx.lineWidth = 3 / globalScale;
                      ctx.lineJoin = 'round';
                      ctx.strokeStyle = 'rgba(10,10,10,0.85)';
                      ctx.strokeText(label, x, y);
                      ctx.fillStyle = hovered
                        ? 'rgba(255,255,255,0.98)'
                        : 'rgba(210,210,210,0.95)';
                      ctx.fillText(label, x, y);
                    }
                  }}
                />
              )}
            </div>

            <aside className="border-border bg-card flex w-full shrink-0 flex-col rounded-xl border p-4 lg:w-80">
              {loadingNode ? (
                <SkeletonLoader count={3} />
              ) : selectedNode ? (
                <div className="flex flex-col">
                  <div className="mb-2 flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <h3 className="text-foreground text-sm font-semibold wrap-break-word">
                        {selectedNode.name}
                      </h3>
                      {selectedNode.type && (
                        <span className="bg-muted-foreground/10 text-muted-foreground mt-1 inline-block rounded-full px-2 py-0.5 text-xs font-medium">
                          {selectedNode.type}
                        </span>
                      )}
                    </div>
                    <button
                      type="button"
                      onClick={() => setSelectedNode(null)}
                      aria-label={t('settings.sources.graphrag.view.close')}
                      className="text-muted-foreground hover:text-foreground shrink-0"
                    >
                      <X size={16} aria-hidden="true" />
                    </button>
                  </div>

                  {selectedNode.description && (
                    <p className="text-muted-foreground mb-3 text-sm leading-relaxed wrap-break-word">
                      {selectedNode.description}
                    </p>
                  )}

                  <h4 className="text-foreground mb-2 text-xs font-semibold">
                    {t('settings.sources.graphrag.view.linkedChunks')}
                  </h4>
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
