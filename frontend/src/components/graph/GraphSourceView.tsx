import { Waypoints } from 'lucide-react';
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../../api/services/userService';
import { selectToken } from '../../preferences/preferenceSlice';
import { formatCount } from '../../utils/dateTimeUtils';
import Chunks, {
  type ChunksController,
  type OpenChunkPosition,
} from '../Chunks';
import ConnectorTree from '../ConnectorTree';
import FileTree from '../FileTree';
import GraphView, { type GraphLoadStatus } from '../GraphView';
import PathHeader, { type Crumb } from '../tree/PathHeader';
import { Badge } from '../ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../ui/tabs';
import {
  foldGraphTypes,
  toForceGraphData,
  type ForceGraphData,
  type GraphStats,
} from '../graphViewUtils';
import GraphEntities from './GraphEntities';
import type { GraphNodeRef } from './GraphNodePanel';

const DEFAULT_LIMIT = 100;

type GraphTab = 'graph' | 'entities' | 'files';

interface GraphSourceViewProps {
  docId: string;
  sourceName: string;
  /** The source's `type`; `connector:file` sources browse as a connector tree. */
  sourceType?: string;
  /**
   * Whether the source has a folder structure (`bool(directory_structure)`).
   * Without one the Files tab shows the chunk list, as the plain source view
   * does. Defaults to true.
   */
  isNested?: boolean;
  onBackToDocuments: () => void;
  /** Extra header control (Test retrieval), right-aligned in the title row. */
  headerAction?: ReactNode;
}

/**
 * A knowledge-graph source: the header (source name, the Knowledge graph
 * badge, the whole graph's totals) over three tabs, Graph (the canvas),
 * Entities (a searchable table) and Files (the ordinary file view). The
 * overview is fetched here so the header, the canvas and the entity list
 * share one fold of the types, and so one type has one colour everywhere.
 */
export default function GraphSourceView({
  docId,
  sourceName,
  sourceType,
  isNested = true,
  onBackToDocuments,
  headerAction,
}: GraphSourceViewProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);

  const [tab, setTab] = useState<GraphTab>('graph');
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [data, setData] = useState<ForceGraphData>({ nodes: [], links: [] });
  const [stats, setStats] = useState<GraphStats | null>(null);
  const [status, setStatus] = useState<GraphLoadStatus>('loading');
  const [attempt, setAttempt] = useState(0);
  const [selected, setSelected] = useState<GraphNodeRef | null>(null);
  // The file a chunk drawer's "Open in Files" asked the Files tab to open.
  const [filesPath, setFilesPath] = useState<string | undefined>(undefined);
  // Where the Files tab's tree is (the source, folders, file, chunk); the
  // header shows it while that tab is open.
  const [filesCrumbs, setFilesCrumbs] = useState<Crumb[]>([]);
  // A flat source's open chunk (its crumb), reported by the chunk list.
  const [openChunkPosition, setOpenChunkPosition] =
    useState<OpenChunkPosition>(null);
  const chunksControllerRef = useRef<ChunksController | null>(null);

  useEffect(() => {
    let cancelled = false;
    setStatus('loading');
    userService
      .getSourceGraph(docId, token, limit)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((body) => {
        if (cancelled) return;
        const nodes = body?.nodes ?? [];
        const edges = body?.edges ?? [];
        setData(toForceGraphData({ nodes, edges }));
        setStats(body?.stats ?? { nodes: nodes.length, edges: edges.length });
        setStatus('ready');
      })
      .catch((error) => {
        if (cancelled) return;
        console.error('Error loading graph:', error);
        setStatus('error');
      });
    return () => {
      cancelled = true;
    };
  }, [docId, token, limit, attempt]);

  const fold = useMemo(() => foldGraphTypes(data.nodes), [data.nodes]);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  // "Open in Files" is a one-off request: leaving the Files tab drops it, so
  // a later visit opens the tree at its root rather than on that file again.
  const changeTab = useCallback(
    (next: GraphTab) => {
      if (tab === 'files' && next !== 'files') setFilesPath(undefined);
      setTab(next);
    },
    [tab],
  );

  const showInGraph = useCallback(
    (node: GraphNodeRef) => {
      setSelected(node);
      changeTab('graph');
    },
    [changeTab],
  );

  const [filesActions, setFilesActions] = useState<HTMLDivElement | null>(null);

  // A flat source has no file to open: "Open in Files" just shows the tab.
  const openInFiles = useCallback(
    (path: string) => {
      if (isNested) setFilesPath(path);
      setTab('files');
    },
    [isNested],
  );

  // The flat source's crumbs: the source, then the open chunk; the source
  // crumb closes the chunk.
  const chunkCrumbs: Crumb[] = [
    {
      label: sourceName,
      onSelect:
        openChunkPosition !== null
          ? () => chunksControllerRef.current?.closeChunk()
          : undefined,
    },
    ...(openChunkPosition !== null
      ? [
          {
            label:
              openChunkPosition === 'unplaced'
                ? t('settings.sources.chunkCrumbUnplaced')
                : t('settings.sources.chunkCrumb', { n: openChunkPosition }),
          },
        ]
      : []),
  ];
  const filesSegments = isNested ? filesCrumbs : chunkCrumbs;

  const files = !isNested ? (
    <Chunks
      embedded
      documentId={docId}
      documentName={sourceName}
      handleGoBack={onBackToDocuments}
      controllerRef={chunksControllerRef}
      onOpenChunkChange={setOpenChunkPosition}
    />
  ) : sourceType === 'connector:file' ? (
    <ConnectorTree
      embedded
      docId={docId}
      sourceName={sourceName}
      onBackToDocuments={onBackToDocuments}
      initialPath={filesPath}
      actionsTarget={filesActions}
      onCrumbsChange={setFilesCrumbs}
    />
  ) : (
    <FileTree
      embedded
      docId={docId}
      sourceName={sourceName}
      onBackToDocuments={onBackToDocuments}
      initialPath={filesPath}
      actionsTarget={filesActions}
      onCrumbsChange={setFilesCrumbs}
    />
  );

  return (
    <div className="flex flex-col gap-4">
      <PathHeader
        root={{
          label: t('settings.sources.label'),
          onSelect: onBackToDocuments,
        }}
        segments={
          tab === 'files' && filesSegments.length
            ? filesSegments
            : [{ label: sourceName }]
        }
        badge={
          <Badge variant="neutral">
            <Waypoints />
            {t('settings.sources.graphrag.view.title')}
          </Badge>
        }
        byline={
          stats
            ? t('settings.sources.graphrag.view.stats', {
                entities: t('settings.sources.graphrag.view.entityCount', {
                  count: stats.nodes,
                  formatted: formatCount(stats.nodes),
                }),
                relationships: t(
                  'settings.sources.graphrag.view.relationshipCount',
                  {
                    count: stats.edges,
                    formatted: formatCount(stats.edges),
                  },
                ),
                interpolation: { escapeValue: false },
              })
            : undefined
        }
        actions={
          <>
            {headerAction}
            {/* The Files tab's own action (Add file, Sync) portals in here,
                beside Test retrieval, like on a plain source. */}
            {tab === 'files' && isNested ? (
              <div ref={setFilesActions} className="flex items-center gap-2" />
            ) : null}
          </>
        }
      />
      <Tabs value={tab} onValueChange={(value) => changeTab(value as GraphTab)}>
        <TabsList variant="underline">
          <TabsTrigger value="graph" variant="underline">
            {t('settings.sources.graphrag.view.tabs.graph')}
          </TabsTrigger>
          <TabsTrigger value="entities" variant="underline">
            {t('settings.sources.graphrag.view.tabs.entities')}
          </TabsTrigger>
          <TabsTrigger value="files" variant="underline">
            {t('settings.sources.graphrag.view.tabs.files')}
          </TabsTrigger>
        </TabsList>
        {/* Kept mounted so the layout and zoom survive a trip to another tab. */}
        <TabsContent
          value="graph"
          forceMount
          className="mt-4 data-[state=inactive]:hidden"
        >
          <GraphView
            docId={docId}
            data={data}
            fold={fold}
            status={status}
            onRetry={retry}
            limit={limit}
            onLimitChange={setLimit}
            selected={selected}
            onSelect={setSelected}
            active={tab === 'graph'}
            onOpenInFiles={openInFiles}
          />
        </TabsContent>
        <TabsContent value="entities" className="mt-4">
          <GraphEntities
            docId={docId}
            fold={fold}
            onShowInGraph={showInGraph}
            overview={data}
            onOpenInFiles={openInFiles}
          />
        </TabsContent>
        <TabsContent value="files" className="mt-4">
          {/* Remounted per requested file so the tree opens on it. */}
          <div key={filesPath ?? ''}>{files}</div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
