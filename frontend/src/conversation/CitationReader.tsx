import { ExternalLink } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { Link } from 'react-router-dom';

import userService from '../api/services/userService';
import {
  UNKNOWN_TOKEN_COUNT,
  formatChunkTokens,
} from '../components/chunkUtils';
import { chunkFilePath } from '../components/graph/graphCanvasUtils';
import SourceMarkdown, { type SourceLink } from '../components/SourceMarkdown';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import {
  DescriptionItem,
  DescriptionList,
} from '../components/ui/description-list';
import { EmptyState } from '../components/ui/empty-state';
import { LoadingState } from '../components/ui/loading-state';
import {
  PanelBody,
  PanelFooter,
  PanelHeader,
} from '../components/ui/side-panel';
import { wikiLinkTarget } from '../components/wikiViewerUtils';
import { selectSourceDocs, selectToken } from '../preferences/preferenceSlice';
import { knowledgeLink } from '../settings/knowledgeLink';
import { formatDateOnly } from '../utils/dateTimeUtils';
import { type AnswerSource, sourceExcerpt, sourceHref } from './chatCompanion';

type Chunk = {
  doc_id: string;
  text: string;
  metadata: Record<string, unknown>;
};

/** What `/api/sources/<id>/chunk` says about the chunk's source. */
type ChunkSource = {
  id: string;
  name?: string;
  kind?: string;
  date?: string;
};

// Why only the answer's excerpt is shown: the message predates chunk keys,
// the passage left the source, or the source is out of the viewer's reach.
type ExcerptReason = 'excerptOnly' | 'missing' | 'forbidden';

type ReaderState =
  | { status: 'loading' }
  | {
      status: 'ready';
      chunk: Chunk;
      source: ChunkSource | null;
      /** A wiki chunk's page, which Knowledge opens. */
      pagePath?: string | null;
    }
  | { status: 'excerpt'; reason: ExcerptReason }
  | { status: 'error' };

// The chunk browser's text search matches a substring; the excerpt's first
// characters are a verbatim prefix of the chunk, which is enough to find it.
const NEEDLE_LENGTH = 80;

/**
 * One cited source, the second level of an answer's sources panel: a Back
 * arrow to the list, the full passage rendered, and what is known about the
 * chunk and its knowledge. The passage is fetched by the chunk key retrieval
 * labelled it with; a re-chunked source is searched by the answer's excerpt,
 * and when neither finds it the excerpt is shown with a note saying why.
 * Render it inside the panel, keyed on the source.
 */
export default function CitationReader({
  source,
  number,
  onBack,
}: {
  source: AnswerSource;
  /** 1-based, the `[n]` the answer cites it by. */
  number: number;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const knowledge = useSelector(selectSourceDocs);
  const [state, setState] = useState<ReaderState>({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);

  const sourceId = source.source_id;
  const chunkKey = source.chunk_key;
  const excerpt = sourceExcerpt(source);

  useEffect(() => {
    if (!sourceId || !chunkKey) {
      setState({ status: 'excerpt', reason: 'excerptOnly' });
      return;
    }
    let cancelled = false;
    const settle = (next: ReaderState) => {
      if (!cancelled) setState(next);
    };

    const findByExcerpt = async () => {
      const needle = excerpt.slice(0, NEEDLE_LENGTH).trim();
      if (!needle) return settle({ status: 'excerpt', reason: 'missing' });
      const response = await userService.getDocumentChunks(
        sourceId,
        1,
        1,
        token,
        undefined,
        needle,
      );
      if (!response.ok) return settle({ status: 'excerpt', reason: 'missing' });
      const body = await response.json();
      const chunk: Chunk | undefined = body?.chunks?.[0];
      settle(
        chunk
          ? { status: 'ready', chunk, source: null }
          : { status: 'excerpt', reason: 'missing' },
      );
    };

    setState({ status: 'loading' });
    userService
      .getSourceChunk(sourceId, chunkKey, token)
      .then(async (response) => {
        if (response.ok) {
          const body = await response.json();
          return settle({
            status: 'ready',
            chunk: body.chunk,
            source: body.source,
            pagePath: body.page_path,
          });
        }
        if (response.status === 404) {
          const body = await response.json().catch(() => ({}));
          // The source is gone or out of reach; the chunk browser would
          // refuse the same way, so there is nothing more to search.
          if (body?.message !== 'Chunk not found') {
            return settle({ status: 'excerpt', reason: 'forbidden' });
          }
          return findByExcerpt();
        }
        if (response.status === 401 || response.status === 403) {
          return settle({ status: 'excerpt', reason: 'forbidden' });
        }
        settle({ status: 'error' });
      })
      .catch(() => settle({ status: 'error' }));

    return () => {
      cancelled = true;
    };
  }, [sourceId, chunkKey, excerpt, token, attempt]);

  const href = sourceHref(source);
  const ready = state.status === 'ready' ? state : null;
  const listed = knowledge?.find((doc) => doc.id && doc.id === sourceId);
  const knowledgeName = ready?.source?.name || listed?.name;
  const kind =
    ready?.source?.kind ??
    (listed?.type === 'wiki' ? 'wiki' : listed?.config?.kind);
  const metadata = ready?.chunk.metadata ?? {};
  const path =
    typeof metadata.source === 'string' ? metadata.source : source.source;
  const tokens = formatChunkTokens(
    metadata as Parameters<typeof formatChunkTokens>[0],
  );
  // The source is one the viewer can open in Knowledge: the API answered for
  // it, or the app's knowledge list has it.
  const reachable = Boolean(sourceId && (ready?.source || listed));
  // A wiki chunk's page: where its links to other pages are read from.
  const wikiPage =
    kind === 'wiki'
      ? (ready?.pagePath ??
        (typeof metadata.source === 'string' ? metadata.source : undefined) ??
        source.source)
      : undefined;
  // The passage in Knowledge: the cited chunk, or a wiki chunk's page.
  const inKnowledge =
    ready && sourceId && reachable
      ? knowledgeLink(
          kind === 'wiki'
            ? { sourceId, wikiPage }
            : {
                sourceId,
                chunk: {
                  id: ready.chunk.doc_id,
                  search: excerpt || ready.chunk.text,
                  path: chunkFilePath(metadata) || undefined,
                },
              },
        )
      : null;
  // A wiki passage links other pages by their wiki path; those open in
  // Knowledge at that page. Any other link that is not a web address (a page
  // of a source out of reach, a relative link in a document) leads nowhere
  // from the chat, so it reads as text rather than a dead route of this app.
  const resolveLink = useCallback(
    (href: string): SourceLink | null => {
      const target = wikiLinkTarget(href, wikiPage ?? '');
      if (target === null) return null;
      return sourceId && wikiPage && reachable
        ? { to: knowledgeLink({ sourceId, wikiPage: target }) }
        : 'text';
    },
    [sourceId, wikiPage, reachable],
  );

  const renderBody = () => {
    if (state.status === 'loading') return <LoadingState />;
    if (state.status === 'error') {
      return (
        <EmptyState
          tone="destructive"
          size="sm"
          illustration="none"
          title={t('conversation.sources.reader.loadFailed')}
          onRetry={() => setAttempt((n) => n + 1)}
        />
      );
    }
    return (
      <>
        {state.status === 'excerpt' ? (
          <Alert variant="info" role="note">
            <AlertDescription>
              {t(`conversation.sources.reader.${state.reason}`)}
            </AlertDescription>
          </Alert>
        ) : null}
        <DescriptionList size="xs">
          {knowledgeName ? (
            <DescriptionItem label={t('conversation.sources.reader.knowledge')}>
              {reachable && sourceId ? (
                <Button variant="link" size="text" asChild>
                  <Link to={knowledgeLink({ sourceId })}>{knowledgeName}</Link>
                </Button>
              ) : (
                knowledgeName
              )}
            </DescriptionItem>
          ) : null}
          {href ? (
            <DescriptionItem label={t('conversation.sources.reader.link')}>
              <span className="wrap-anywhere">{href}</span>
            </DescriptionItem>
          ) : path ? (
            <DescriptionItem
              label={t(
                kind === 'wiki'
                  ? 'conversation.sources.reader.page'
                  : 'conversation.sources.reader.file',
              )}
            >
              <span className="wrap-anywhere">{path}</span>
            </DescriptionItem>
          ) : null}
          {ready?.source?.date ? (
            <DescriptionItem label={t('conversation.sources.reader.added')}>
              {formatDateOnly(ready.source.date)}
            </DescriptionItem>
          ) : null}
          {ready && tokens !== UNKNOWN_TOKEN_COUNT ? (
            <DescriptionItem label={t('conversation.sources.reader.length')}>
              <span className="tabular-nums">
                {t('conversation.sources.reader.tokens', { tokens })}
              </span>
            </DescriptionItem>
          ) : null}
        </DescriptionList>
        <SourceMarkdown
          content={ready ? ready.chunk.text : excerpt}
          resolveLink={resolveLink}
        />
      </>
    );
  };

  return (
    <>
      <PanelHeader
        title={source.title}
        description={knowledgeName}
        actions={<Badge className="tabular-nums">{number}</Badge>}
        onBack={onBack}
        backLabel={t('conversation.sources.reader.back')}
      />
      <PanelBody>{renderBody()}</PanelBody>
      {href || inKnowledge ? (
        <PanelFooter>
          {href ? (
            <Button variant="outline" size="lg" shape="pill" asChild>
              <a href={href} target="_blank" rel="noopener noreferrer">
                <ExternalLink />
                {t('conversation.sources.reader.openLink')}
              </a>
            </Button>
          ) : null}
          {inKnowledge ? (
            <Button size="lg" shape="pill" asChild>
              <Link to={inKnowledge}>
                {t('conversation.sources.reader.openInKnowledge')}
              </Link>
            </Button>
          ) : null}
        </PanelFooter>
      ) : null}
    </>
  );
}
