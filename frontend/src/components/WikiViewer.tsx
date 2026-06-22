import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import userService from '../api/services/userService';
import ArrowLeft from '../assets/arrow-left.svg';
import { selectToken } from '../preferences/preferenceSlice';
import { decodeJwtPayload } from '../utils/jwtUtils';
import { Button } from './ui/button';
import SkeletonLoader from './SkeletonLoader';
import {
  WikiPageNode,
  formatRelativeTime,
  provenanceKey,
  saveWikiPage,
} from './wikiViewerUtils';

interface WikiViewerProps {
  docId: string;
  sourceName: string;
  canEdit?: boolean;
  onBackToDocuments: () => void;
}

const markdownComponents = {
  h1: ({ children }: { children?: React.ReactNode }) => (
    <h1 className="mt-4 mb-2 text-xl font-semibold">{children}</h1>
  ),
  h2: ({ children }: { children?: React.ReactNode }) => (
    <h2 className="mt-4 mb-2 text-lg font-semibold">{children}</h2>
  ),
  h3: ({ children }: { children?: React.ReactNode }) => (
    <h3 className="mt-3 mb-2 text-base font-semibold">{children}</h3>
  ),
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
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="text-primary underline"
    >
      {children}
    </a>
  ),
  code: ({ children }: { children?: React.ReactNode }) => (
    <code className="dark:bg-accent rounded-md bg-gray-200 px-1.5 py-0.5 text-xs">
      {children}
    </code>
  ),
};

const WikiViewer: React.FC<WikiViewerProps> = ({
  docId,
  sourceName,
  canEdit = false,
  onBackToDocuments,
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
    const when = formatRelativeTime(page.updated_at);
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
                    className={`w-full truncate rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                      selectedPath === p.path
                        ? 'bg-muted text-foreground dark:bg-accent'
                        : 'text-muted-foreground hover:bg-muted dark:hover:bg-accent'
                    }`}
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
                  <textarea
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    placeholder={t('settings.sources.wiki.editPlaceholder')}
                    className="border-border bg-card text-foreground min-h-[320px] w-full resize-y rounded-md border p-3 font-mono text-sm leading-relaxed"
                    aria-label={selectedPath}
                  />
                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      size="sm"
                      onClick={handleSave}
                      disabled={saving}
                    >
                      {saving
                        ? t('settings.sources.wiki.saving')
                        : t('settings.sources.wiki.save')}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
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
