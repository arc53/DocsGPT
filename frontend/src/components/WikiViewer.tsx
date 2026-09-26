import { ArrowLeft, BookOpen } from 'lucide-react';
import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { markdownHeadings } from '@/lib/markdown';
import { cn } from '@/lib/utils';

import userService from '../api/services/userService';
import { selectToken } from '../preferences/preferenceSlice';
import { formatRelative } from '../utils/dateTimeUtils';
import { decodeJwtPayload } from '../utils/jwtUtils';
import { Button } from './ui/button';
import { IconButton } from './ui/icon-button';
import { Textarea } from './ui/textarea';
import SkeletonLoader from './SkeletonLoader';
import { WikiPageNode, provenanceKey, saveWikiPage } from './wikiViewerUtils';

interface WikiViewerProps {
  docId: string;
  sourceName: string;
  canEdit?: boolean;
  onBackToDocuments: () => void;
  /** Extra header control, right-aligned in the title row. */
  headerAction?: React.ReactNode;
}

const markdownComponents = {
  ...markdownHeadings,
  p: ({ children }: { children?: React.ReactNode }) => (
    <p className="mb-3">{children}</p>
  ),
  ul: ({ children }: { children?: React.ReactNode }) => (
    <ul className="mb-3 list-inside list-disc pl-4">{children}</ul>
  ),
  ol: ({ children }: { children?: React.ReactNode }) => (
    <ol className="mb-3 list-inside list-decimal pl-4">{children}</ol>
  ),
  a: ({ children, href }: { children?: React.ReactNode; href?: string }) => (
    <Button variant="link" size="inline" asChild>
      <a href={href} target="_blank" rel="noreferrer">
        {children}
      </a>
    </Button>
  ),
  code: ({ children }: { children?: React.ReactNode }) => (
    <code className="bg-accent rounded-md px-1.5 py-0.5 text-xs">
      {children}
    </code>
  ),
};

const WikiViewer: React.FC<WikiViewerProps> = ({
  docId,
  sourceName,
  canEdit = false,
  onBackToDocuments,
  headerAction,
}) => {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const currentUserSub = token
    ? ((decodeJwtPayload(token)?.sub as string | undefined) ?? null)
    : null;

  const [pages, setPages] = useState<WikiPageNode[]>([]);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [page, setPage] = useState<WikiPageNode | null>(null);
  const [content, setContent] = useState<string>('');
  const [loadingPages, setLoadingPages] = useState(true);
  const [loadingContent, setLoadingContent] = useState(false);

  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState<string>('');
  const [saving, setSaving] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoadingPages(true);
    userService
      .getWikiPages(docId, token)
      .then((response) => response.json())
      .then((data) => {
        if (cancelled) return;
        const list: WikiPageNode[] = data?.pages ?? [];
        setPages(list);
        if (list.length > 0) setSelectedPath(list[0].path);
      })
      .catch((error) => console.error('Error loading wiki pages:', error))
      .finally(() => {
        if (!cancelled) setLoadingPages(false);
      });
    return () => {
      cancelled = true;
    };
  }, [docId, token]);

  useEffect(() => {
    setIsEditing(false);
    setEditError(null);
    if (!selectedPath) {
      setPage(null);
      setContent('');
      return;
    }
    let cancelled = false;
    setLoadingContent(true);
    userService
      .getWikiPage(docId, selectedPath, token)
      .then((response) => response.json())
      .then((data) => {
        if (cancelled) return;
        const node: WikiPageNode | null = data?.page ?? null;
        setPage(node);
        setContent((data?.page?.content as string) ?? '');
      })
      .catch((error) => console.error('Error loading wiki page:', error))
      .finally(() => {
        if (!cancelled) setLoadingContent(false);
      });
    return () => {
      cancelled = true;
    };
  }, [docId, selectedPath, token]);

  const startEditing = () => {
    setDraft(content);
    setEditError(null);
    setIsEditing(true);
  };

  const cancelEditing = () => {
    setIsEditing(false);
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
          if (outcome.page) setPage(outcome.page);
          setContent(draft);
          setIsEditing(false);
          break;
        case 'conflict':
          if (outcome.page) {
            setPage(outcome.page);
            setContent(outcome.page.content ?? '');
          }
          setEditError(t('settings.sources.wiki.conflict'));
          break;
        case 'forbidden':
          setEditError(t('settings.sources.wiki.forbidden'));
          break;
        default:
          setEditError(t('settings.sources.wiki.saveFailed'));
      }
    } catch (error) {
      console.error('Error saving wiki page:', error);
      setEditError(t('settings.sources.wiki.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  const provenanceLabel = (via?: string | null, by?: string | null): string =>
    t(`settings.sources.wiki.stamp.${provenanceKey(via, by, currentUserSub)}`);

  const renderStamp = () => {
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
    return (
      <p className="text-muted-foreground mb-3 text-xs">{parts.join(' · ')}</p>
    );
  };

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
        <BookOpen className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <p>
          <span className="text-foreground font-medium">
            {t('settings.sources.wiki.livingTitle')}
          </span>{' '}
          {t('settings.sources.wiki.livingExplainer')}
          {canEdit && (
            <> {t('settings.sources.wiki.livingExplainerEditable')}</>
          )}
        </p>
      </div>

      <div className="flex flex-col gap-4 md:flex-row">
        <div className="border-border md:w-64 md:shrink-0 md:border-r md:pr-4">
          {loadingPages ? (
            <SkeletonLoader count={3} />
          ) : pages.length === 0 ? (
            <p className="text-muted-foreground py-2 text-sm">
              {t('settings.sources.wiki.empty')}
            </p>
          ) : (
            <ul className="flex flex-col gap-1">
              {pages.map((p) => (
                <li key={p.path}>
                  <button
                    type="button"
                    onClick={() => setSelectedPath(p.path)}
                    className={cn(
                      'w-full truncate rounded-lg px-3 py-2 text-left text-sm transition-colors',
                      selectedPath === p.path
                        ? 'bg-accent text-foreground'
                        : 'text-muted-foreground hover:bg-accent',
                    )}
                    title={p.path}
                  >
                    {p.title || p.path}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="min-w-0 flex-1">
          {loadingContent ? (
            <SkeletonLoader count={4} />
          ) : selectedPath ? (
            <div className="flex flex-col">
              <div className="mb-2 flex items-center justify-between gap-2">
                {renderStamp()}
                {canEdit && !isEditing && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={startEditing}
                  >
                    {t('settings.sources.wiki.edit')}
                  </Button>
                )}
              </div>

              {editError && (
                <p
                  role="alert"
                  className="border-border text-muted-foreground mb-3 rounded-md border px-3 py-2 text-xs"
                >
                  {editError}
                </p>
              )}

              {isEditing ? (
                <div className="flex flex-col gap-3">
                  <Textarea
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    placeholder={t('settings.sources.wiki.editPlaceholder')}
                    variant="filled"
                    className="min-h-[320px] font-mono"
                    aria-label={selectedPath}
                  />
                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      size="sm"
                      onClick={handleSave}
                      loading={saving}
                    >
                      {t('settings.sources.wiki.save')}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={cancelEditing}
                      disabled={saving}
                    >
                      {t('settings.sources.wiki.cancel')}
                    </Button>
                  </div>
                </div>
              ) : (
                <article className="text-foreground max-w-none text-sm leading-relaxed wrap-break-word">
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={markdownComponents}
                  >
                    {content}
                  </ReactMarkdown>
                </article>
              )}
            </div>
          ) : (
            <p className="text-muted-foreground py-2 text-sm">
              {t('settings.sources.wiki.selectPage')}
            </p>
          )}
        </div>
      </div>
    </div>
  );
};

export default WikiViewer;
