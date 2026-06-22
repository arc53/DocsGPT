import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import userService from '../api/services/userService';
import ArrowLeft from '../assets/arrow-left.svg';
import { selectToken } from '../preferences/preferenceSlice';
import { Button } from './ui/button';
import SkeletonLoader from './SkeletonLoader';

interface WikiPageNode {
  path: string;
  title?: string | null;
  token_count?: number;
  embed_status?: string;
}

interface WikiViewerProps {
  docId: string;
  sourceName: string;
  onBackToDocuments: () => void;
}

const WikiViewer: React.FC<WikiViewerProps> = ({
  docId,
  sourceName,
  onBackToDocuments,
}) => {
  const { t } = useTranslation();
  const token = useSelector(selectToken);

  const [pages, setPages] = useState<WikiPageNode[]>([]);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [content, setContent] = useState<string>('');
  const [loadingPages, setLoadingPages] = useState(true);
  const [loadingContent, setLoadingContent] = useState(false);

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
    if (!selectedPath) {
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
        setContent(data?.page?.content ?? '');
      })
      .catch((error) => console.error('Error loading wiki page:', error))
      .finally(() => {
        if (!cancelled) setLoadingContent(false);
      });
    return () => {
      cancelled = true;
    };
  }, [docId, selectedPath, token]);

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
              {pages.map((page) => (
                <li key={page.path}>
                  <button
                    type="button"
                    onClick={() => setSelectedPath(page.path)}
                    className={`w-full truncate rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                      selectedPath === page.path
                        ? 'bg-muted text-foreground dark:bg-accent'
                        : 'text-muted-foreground hover:bg-muted dark:hover:bg-accent'
                    }`}
                    title={page.path}
                  >
                    {page.title || page.path}
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
            <article className="text-foreground max-w-none text-sm leading-relaxed wrap-break-word">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  h1: ({ children }) => (
                    <h1 className="mt-4 mb-2 text-xl font-semibold">
                      {children}
                    </h1>
                  ),
                  h2: ({ children }) => (
                    <h2 className="mt-4 mb-2 text-lg font-semibold">
                      {children}
                    </h2>
                  ),
                  h3: ({ children }) => (
                    <h3 className="mt-3 mb-2 text-base font-semibold">
                      {children}
                    </h3>
                  ),
                  p: ({ children }) => <p className="mb-3">{children}</p>,
                  ul: ({ children }) => (
                    <ul className="mb-3 list-inside list-disc pl-4">
                      {children}
                    </ul>
                  ),
                  ol: ({ children }) => (
                    <ol className="mb-3 list-inside list-decimal pl-4">
                      {children}
                    </ol>
                  ),
                  a: ({ children, href }) => (
                    <a
                      href={href}
                      target="_blank"
                      rel="noreferrer"
                      className="text-primary underline"
                    >
                      {children}
                    </a>
                  ),
                  code: ({ children }) => (
                    <code className="dark:bg-accent rounded-md bg-gray-200 px-1.5 py-0.5 text-xs">
                      {children}
                    </code>
                  ),
                }}
              >
                {content}
              </ReactMarkdown>
            </article>
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
