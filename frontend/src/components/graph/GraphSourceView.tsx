import { Network, Waypoints } from 'lucide-react';
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
import type { Doc } from '../../models/misc';
import { selectToken } from '../../preferences/preferenceSlice';
import { formatCount } from '../../utils/dateTimeUtils';
import type { LinkedChunk } from '../chunkUtils';
import Chunks, {
  type ChunksController,
  type OpenChunkPosition,
} from '../Chunks';
import ConnectorTree from '../ConnectorTree';
import FileTree from '../FileTree';
import GraphView, { type GraphLoadStatus } from '../GraphView';
import PathHeader, { type Crumb } from '../tree/PathHeader';
import WebsiteTree from '../WebsiteTree';
import { type WebsiteSync, useWebsiteChanges } from '../tree/useWebsiteChanges';
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
import useGraphBuild from './useGraphBuild';

const DEFAULT_LIMIT = 100;

type GraphTab = 'graph' | 'entities' | 'files';

interface GraphSourceViewProps {
  docId: string;
  sourceName: string;
  /** The source's `type`; `connector:file` sources browse as a connector tree. */
  sourceType?: string;
  /**
   * Synced from a connection or on a schedule, whatever its type (an S3 or
   * GitHub source): the Files tab browses as a connector tree too (Sync
   * now, no Add file).
   */
  synced?: boolean;
  /**
   * Whether the source can sync at all (`canSyncSource`): false hides the
   * Files tab's Sync now (a connector source whose connection was removed).
   * Defaults to true.
   */
  canSync?: boolean;
  /**
   * Whether the source has a folder structure (`bool(directory_structure)`).
   * Without one the Files tab shows the chunk list, as the plain source view
   * does. Defaults to true.
   */
  isNested?: boolean;
  /**
   * A Website source's hosts and page count (the sources list's `website`):
   * the Files tab lists its pages, with Add pages, Refresh and Remove.
   */
  website?: Doc['website'];
  /** `sources.sync_frequency`, for a Website source's byline. */
  syncFrequency?: string;
  /** When the source was last ingested or synced (a Website source's byline). */
  syncedAt?: string;
  /** A Website source: bumped when its settings are saved (see WebsiteTree). */
  settingsVersion?: number;
  /**
   * A Website source: a sync the host started. The view waits for it on
   * every tab, as for its page list's own changes (see `useWebsiteChanges`).
   */
  sync?: WebsiteSync | null;
  /** A Website source: the view's wait for `sync` ended. */
  onSyncSettled?: (sync: WebsiteSync) => void;
  /**
   * A Website source: called once a page change (add, refresh, remove, a
   * sync) has finished, after the graph is read again, so the host can read
   * the source again too.
   */
  onPagesChanged?: () => void;
  /**
   * A Website source: whether a page change or a sync is in flight, each
   * time that turns, so the host holds its Sync now meanwhile.
   */
  onBusyChange?: (busy: boolean) => void;
  onBackToDocuments: () => void;
  /** Extra header control (Test retrieval), right-aligned in the title row. */
  headerAction?: ReactNode;
  /** The source's ⋯, last in the title row. */
  headerMenu?: ReactNode;
  /**
   * Whether the caller may change the source (`can(source, 'edit')`). False
   * hides the Files tab's writes and the graph chunk drawer's Edit.
   */
  canEdit?: boolean;
  /**
   * A cited chunk to show (a citation opened in Knowledge): the view opens
   * on the Files tab at its file, with the chunk open.
   */
  linkedChunk?: LinkedChunk;
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
  synced = false,
  canSync = true,
  isNested = true,
  website,
  syncFrequency,
  syncedAt,
  settingsVersion,
  sync,
  onSyncSettled,
  onPagesChanged,
  onBusyChange,
  onBackToDocuments,
  headerAction,
  headerMenu,
  canEdit = true,
  linkedChunk,
}: GraphSourceViewProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);

  const [tab, setTab] = useState<GraphTab>(linkedChunk ? 'files' : 'graph');
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [data, setData] = useState<ForceGraphData>({ nodes: [], links: [] });
  const [stats, setStats] = useState<GraphStats | null>(null);
  const [status, setStatus] = useState<GraphLoadStatus>('loading');
  const [attempt, setAttempt] = useState(0);
  const [selected, setSelected] = useState<GraphNodeRef | null>(null);
  // The file a chunk drawer's "Open in Files" asked the Files tab to open.
  const [filesPath, setFilesPath] = useState<string | undefined>(
    linkedChunk?.path,
  );
  // The cited chunk, until the Files tab is left (as "Open in Files" is).
  const [linked, setLinked] = useState(linkedChunk);
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

  // A build running for this source (an Add pages or Refresh page extracting
  // its new chunks, a sync rebuilding): the badge shows it, and the graph and
  // its totals are read again once it ends.
  const build = useGraphBuild(docId);
  const wasBuilding = useRef(build.building);
  useEffect(() => {
    if (wasBuilding.current && !build.building) retry();
    wasBuilding.current = build.building;
  }, [build.building, retry]);

  // A Website source's page changes and the syncs the host starts: held
  // here, not by the Files tab's page list, which is mounted only while that
  // tab is open, so they finish (and say so) whichever tab shows.
  const changes = useWebsiteChanges({
    docId,
    sync: website ? sync : null,
    onSyncSettled,
    // A removal changes the graph without a build.
    onPagesChanged: () => {
      retry();
      onPagesChanged?.();
    },
    onBusyChange,
  });

  // "Open in Files" is a one-off request: leaving the Files tab drops it, so
  // a later visit opens the tree at its root rather than on that file again.
  const changeTab = useCallback(
    (next: GraphTab) => {
      if (tab === 'files' && next !== 'files') {
        setFilesPath(undefined);
        setLinked(undefined);
      }
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
      // Another file than the cited one: the citation no longer applies.
      setLinked(undefined);
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
      canEdit={canEdit}
      documentId={docId}
      documentName={sourceName}
      handleGoBack={onBackToDocuments}
      controllerRef={chunksControllerRef}
      onOpenChunkChange={setOpenChunkPosition}
      linkedChunk={linked}
    />
  ) : website ? (
    // Before the connector tree: a website on a schedule is synced too, but
    // its pages are added, refreshed and removed one by one.
    <WebsiteTree
      embedded
      graph
      canEdit={canEdit}
      docId={docId}
      sourceName={sourceName}
      hosts={website.hosts}
      syncFrequency={syncFrequency}
      syncedAt={syncedAt}
      settingsVersion={settingsVersion}
      onBackToDocuments={onBackToDocuments}
      initialPath={filesPath}
      linkedChunk={linked}
      actionsTarget={filesActions}
      onCrumbsChange={setFilesCrumbs}
      changes={changes}
    />
  ) : synced || sourceType === 'connector:file' ? (
    <ConnectorTree
      embedded
      canEdit={canEdit}
      canSync={canSync}
      docId={docId}
      sourceName={sourceName}
      sourceType={sourceType}
      onBackToDocuments={onBackToDocuments}
      initialPath={filesPath}
      linkedChunk={linked}
      actionsTarget={filesActions}
      onCrumbsChange={setFilesCrumbs}
    />
  ) : (
    <FileTree
      embedded
      canEdit={canEdit}
      docId={docId}
      sourceName={sourceName}
      onBackToDocuments={onBackToDocuments}
      initialPath={filesPath}
      linkedChunk={linked}
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
          build.building ? (
            <Badge variant="neutral">
              <Network aria-hidden="true" />
              {build.pct !== null
                ? t('settings.sources.graphrag.buildingPct', { pct: build.pct })
                : t('settings.sources.graphrag.building')}
            </Badge>
          ) : (
            <Badge variant="neutral">
              <Waypoints />
              {t('settings.sources.graphrag.view.title')}
            </Badge>
          )
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
            {/* A change still running, where the Files tab's page list
                would say so: on the other tabs, or a source without one. */}
            {changes.status && !(tab === 'files' && isNested && website) ? (
              <div className="text-muted-foreground text-sm">
                {changes.status}
              </div>
            ) : null}
            {/* The Files tab's own action (Add file, Add pages, Sync)
                portals in here, beside Test retrieval, like on a plain
                source. */}
            {tab === 'files' && isNested ? (
              <div ref={setFilesActions} className="flex items-center gap-2" />
            ) : null}
          </>
        }
        menu={headerMenu}
      />
      <Tabs value={tab} onValueChange={(value) => changeTab(value as GraphTab)}>
        <TabsList>
          <TabsTrigger value="graph">
            {t('settings.sources.graphrag.view.tabs.graph')}
          </TabsTrigger>
          <TabsTrigger value="entities">
            {t('settings.sources.graphrag.view.tabs.entities')}
          </TabsTrigger>
          <TabsTrigger value="files">
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
            canEdit={canEdit}
          />
        </TabsContent>
        <TabsContent value="entities" className="mt-4">
          <GraphEntities
            docId={docId}
            fold={fold}
            onShowInGraph={showInGraph}
            overview={data}
            onOpenInFiles={openInFiles}
            canEdit={canEdit}
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
