import copy from 'copy-to-clipboard';
import { BookOpen, Copy, FileText, Pencil } from 'lucide-react';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import userService from '../api/services/userService';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';
import { formatCount, formatRelative } from '../utils/dateTimeUtils';
import { decodeJwtPayload } from '../utils/jwtUtils';
import SourceMarkdown from './SourceMarkdown';
import PathHeader from './tree/PathHeader';
import ReaderPanel from './tree/ReaderPanel';
import SourceEditSheet from './tree/SourceEditSheet';
import SourceNavigator from './tree/SourceNavigator';
import { Alert, AlertDescription } from './ui/alert';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { ActionMenu } from './ui/dropdown-menu';
import { EmptyState } from './ui/empty-state';
import { Skeleton } from './ui/skeleton';
import {
  WikiPageNode,
  buildWikiNavigator,
  provenanceKey,
  saveWikiPage,
} from './wikiViewerUtils';

interface WikiViewerProps {
  docId: string;
  sourceName: string;
  canEdit?: boolean;
  onBackToDocuments: () => void;
  /** Extra header control, right-aligned in the title row. */
  headerAction?: React.ReactNode;
  /** The page to open first, when it exists (a citation opened in Knowledge). */
  initialPath?: string;
}

type EditError = { kind: 'conflict' | 'forbidden' | 'failed' } | null;

/** Bars in the reader body while a page loads. */
function ReaderBars() {
  return (
    <div className="flex flex-col gap-3" data-testid="wiki-reader-loading">
      <Skeleton className="h-6 w-1/3" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-11/12" />
      <Skeleton className="h-4 w-4/5" />
    </div>
  );
}

const WikiViewer: React.FC<WikiViewerProps> = ({
  docId,
  sourceName,
  canEdit = false,
  onBackToDocuments,
  headerAction,
  initialPath,
}) => {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const currentUserSub = token
    ? ((decodeJwtPayload(token)?.sub as string | undefined) ?? null)
    : null;

  const [pages, setPages] = useState<WikiPageNode[]>([]);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [page, setPage] = useState<WikiPageNode | null>(null);
  const [content, setContent] = useState<string>('');
  const [loadingPages, setLoadingPages] = useState(true);
  const [pagesFailed, setPagesFailed] = useState(false);
  const [pagesAttempt, setPagesAttempt] = useState(0);
  const [loadingContent, setLoadingContent] = useState(false);
  const [contentFailed, setContentFailed] = useState(false);
  const [contentAttempt, setContentAttempt] = useState(0);

  const [editorOpen, setEditorOpen] = useState(false);
  const [draft, setDraft] = useState<string>('');
  const [saving, setSaving] = useState(false);
  const [editError, setEditError] = useState<EditError>(null);

  // The loads read the token through a ref: a refresh (setToken during SSE
  // 401 recovery) is the same user, so it must not refetch, and above all not
  // reset the page and close an open editor with its draft.
  const tokenRef = useRef(token);
  tokenRef.current = token;

  useEffect(() => {
    let cancelled = false;
    setLoadingPages(true);
    setPagesFailed(false);
    userService
      .getWikiPages(docId, tokenRef.current)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((data) => {
        if (cancelled) return;
        const list: WikiPageNode[] = data?.pages ?? [];
        setPages(list);
        // The cited page opens first; a chunk's page path may carry a
        // leading slash the page list does not.
        const wanted = initialPath?.replace(/^\/+/, '');
        setSelectedPath((prev) =>
          prev && list.some((p) => p.path === prev)
            ? prev
            : (list.find((p) => p.path === wanted)?.path ??
              list[0]?.path ??
              null),
        );
      })
      .catch((error) => {
        console.error('Error loading wiki pages:', error);
        if (!cancelled) setPagesFailed(true);
      })
      .finally(() => {
        if (!cancelled) setLoadingPages(false);
      });
    return () => {
      cancelled = true;
    };
  }, [docId, pagesAttempt]);

  useEffect(() => {
    setEditorOpen(false);
    setEditError(null);
    setContentFailed(false);
    // Drop the last page before the next loads, so a failed load never shows
    // its stamp (editor, version) or its text under the new path.
    setPage(null);
    setContent('');
    if (!selectedPath) return;
    let cancelled = false;
    setLoadingContent(true);
    userService
      .getWikiPage(docId, selectedPath, tokenRef.current)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((data) => {
        if (cancelled) return;
        const node: WikiPageNode | null = data?.page ?? null;
        setPage(node);
        setContent((data?.page?.content as string) ?? '');
      })
      .catch((error) => {
        console.error('Error loading wiki page:', error);
        if (!cancelled) setContentFailed(true);
      })
      .finally(() => {
        if (!cancelled) setLoadingContent(false);
      });
    return () => {
      cancelled = true;
    };
  }, [docId, selectedPath, contentAttempt]);

  const homeLabel = t('settings.sources.wiki.home');
  const navigatorNodes = useMemo(
    () => buildWikiNavigator(pages, homeLabel),
    [pages, homeLabel],
  );
  const totalTokens = useMemo(
    () => pages.reduce((sum, p) => sum + (p.token_count ?? 0), 0),
    [pages],
  );

  const startEditing = () => {
    setDraft(content);
    setEditError(null);
    setEditorOpen(true);
  };

  const closeEditor = () => {
    setEditorOpen(false);
    setEditError(null);
  };

  const handleSave = async () => {
    if (!selectedPath) return;
    setSaving(true);
    setEditError(null);
    try {
      const outcome = await saveWikiPage(
        userService,
        docId,
        selectedPath,
        draft,
        page?.version,
        token,
      );
      switch (outcome.status) {
        case 'saved':
          if (outcome.page) {
            const saved = outcome.page;
            setPage(saved);
            // The list feeds the byline's token total and the navigator's
            // labels; keep its entry in step (the list carries no content).
            setPages((list) =>
              list.map((p) =>
                p.path === selectedPath
                  ? { ...p, ...saved, content: p.content }
                  : p,
              ),
            );
          }
          setContent(draft);
          setEditorOpen(false);
          break;
        case 'conflict':
          if (outcome.page) {
            setPage(outcome.page);
            setContent(outcome.page.content ?? '');
          }
          setEditError({ kind: 'conflict' });
          break;
        case 'forbidden':
          setEditError({ kind: 'forbidden' });
          break;
        default:
          setEditError({ kind: 'failed' });
      }
    } catch (error) {
      console.error('Error saving wiki page:', error);
      setEditError({ kind: 'failed' });
    } finally {
      setSaving(false);
    }
  };

  const provenanceLabel = (via?: string | null, by?: string | null): string =>
    t(`settings.sources.wiki.stamp.${provenanceKey(via, by, currentUserSub)}`);

  const stamp = (): string | null => {
    if (!page) return null;
    const who = provenanceLabel(page.updated_via, page.updated_by);
    const when = formatRelative(page.updated_at);
    const parts = [t('settings.sources.wiki.stamp.editedBy', { who })];
    if (when) parts.push(when);
    if (page.version != null) {
      parts.push(
        t('settings.sources.wiki.stamp.version', { version: page.version }),
      );
    }
    return parts.join(' · ');
  };

  const explainer = canEdit
    ? t('settings.sources.wiki.explainerEditable')
    : t('settings.sources.wiki.explainer');
  const byline = loadingPages
    ? explainer
    : `${t('settings.sources.wiki.byline', {
        count: pages.length,
        pages: formatCount(pages.length),
        tokens: formatCount(totalTokens),
      })} · ${explainer}`;

  const renderEditError = () => {
    if (!editError) return null;
    if (editError.kind === 'conflict') {
      return (
        <Alert variant="warning">
          <AlertDescription>
            {t('settings.sources.wiki.conflict')}
          </AlertDescription>
        </Alert>
      );
    }
    return (
      <Alert variant="destructive">
        <AlertDescription>
          {editError.kind === 'forbidden'
            ? t('settings.sources.wiki.forbidden')
            : t('settings.sources.wiki.saveFailed')}
        </AlertDescription>
      </Alert>
    );
  };

  // The chunk reader's actions: Edit (editors only), then the toolbar ⋯.
  const readerActions =
    loadingContent || contentFailed ? null : (
      <>
        {canEdit ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            shape="pill"
            onClick={startEditing}
          >
            <Pencil />
            {t('settings.sources.wiki.edit')}
          </Button>
        ) : null}
        <ActionMenu
          size="toolbar"
          triggerLabel={t('settings.sources.menuAlt')}
          options={[
            {
              icon: Copy,
              label: t('settings.sources.copyText'),
              onClick: () => {
                copy(content);
                dispatch(
                  showActionToast({
                    variant: 'success',
                    message: t('conversation.copied'),
                  }),
                );
              },
            },
          ]}
        />
      </>
    );

  const readerMeta = selectedPath ? (
    <>
      <span className="font-mono wrap-anywhere">{selectedPath}</span>
      {!loadingContent && !contentFailed && stamp() ? (
        <span>{stamp()}</span>
      ) : null}
    </>
  ) : null;

  const readerBody = () => {
    if (loadingContent) return <ReaderBars />;
    if (contentFailed) {
      return (
        <EmptyState
          size="xs"
          tone="destructive"
          illustration="none"
          title={t('settings.sources.wiki.pageLoadFailed')}
          onRetry={() => setContentAttempt((n) => n + 1)}
        />
      );
    }
    return <SourceMarkdown content={content} />;
  };

  const renderBody = () => {
    if (loadingPages) {
      return (
        <div
          className="flex flex-col gap-4 lg:flex-row lg:gap-6"
          data-testid="wiki-loading"
        >
          <div className="flex w-full shrink-0 flex-col gap-2 lg:w-64">
            <Skeleton className="h-9.5 w-full" />
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-5/6" />
            <Skeleton className="h-8 w-4/6" />
            <Skeleton className="h-8 w-5/6" />
          </div>
          <ReaderPanel
            className="min-w-0 flex-1"
            meta={<Skeleton className="h-3 w-40" />}
          >
            <ReaderBars />
          </ReaderPanel>
        </div>
      );
    }
    if (pagesFailed) {
      return (
        <EmptyState
          tone="destructive"
          illustration="none"
          title={t('settings.sources.wiki.loadFailed')}
          onRetry={() => setPagesAttempt((n) => n + 1)}
        />
      );
    }
    if (pages.length === 0) {
      return (
        <EmptyState
          size="xs"
          illustration="none"
          title={t('settings.sources.wiki.empty')}
        />
      );
    }
    const reader = selectedPath ? (
      <ReaderPanel meta={readerMeta} actions={readerActions}>
        {readerBody()}
      </ReaderPanel>
    ) : (
      <EmptyState
        size="xs"
        illustration="none"
        title={t('settings.sources.wiki.selectPage')}
      />
    );
    // One page: nothing to choose between, so no navigator; the reader takes
    // the full width, as TreeBrowser does for a one-file source.
    if (pages.length === 1) return reader;
    return (
      <div className="flex flex-col gap-4 lg:flex-row lg:gap-6">
        <SourceNavigator
          nodes={navigatorNodes}
          selectedId={selectedPath}
          onSelect={(node) => {
            if (node.kind === 'leaf') setSelectedPath(node.id);
          }}
          filterLabel={t('settings.sources.wiki.filterPages')}
          emptyLabel={t('settings.sources.noResults')}
          title={t('settings.sources.wiki.pagesTitle')}
          folderMode="groups"
          leafIcon={FileText}
        />
        <div className="min-w-0 flex-1">{reader}</div>
      </div>
    );
  };

  return (
    <div className="flex flex-col gap-4">
      <PathHeader
        root={{
          label: t('settings.sources.label'),
          onSelect: onBackToDocuments,
        }}
        segments={[{ label: sourceName }]}
        badge={
          <Badge variant="neutral">
            <BookOpen />
            {t('settings.sources.wiki.badge')}
          </Badge>
        }
        byline={byline}
        actions={headerAction}
      />
      {renderBody()}
      {canEdit && selectedPath ? (
        <SourceEditSheet
          open={editorOpen}
          onClose={closeEditor}
          title={t('settings.sources.wiki.editTitle')}
          description={
            page?.version != null
              ? `${selectedPath} · ${t('settings.sources.wiki.stamp.version', {
                  version: page.version,
                })}`
              : selectedPath
          }
          value={draft}
          onChange={setDraft}
          dirty={draft !== content}
          onSave={handleSave}
          saving={saving}
          saveLabel={t('settings.sources.wiki.save')}
          alert={renderEditError()}
          fieldLabel={t('modals.chunk.bodyText')}
          placeholder={t('settings.sources.wiki.editPlaceholder')}
        />
      ) : null}
    </div>
  );
};

export default WikiViewer;
