import React, { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import ReactMarkdown from 'react-markdown';
import { useSelector } from 'react-redux';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import {
  oneLight,
  vscDarkPlus,
} from 'react-syntax-highlighter/dist/cjs/styles/prism';
import remarkGfm from 'remark-gfm';

import { markdownHeadings } from '@/lib/markdown';
import { cn } from '@/lib/utils';

import userService from '../api/services/userService';
import { useDarkTheme } from '../hooks';
import { selectToken } from '../preferences/preferenceSlice';
import { isDocumentArtifact, type DocumentArtifact } from './artifactViewUtils';
import CopyButton from './CopyButton';
import DocumentArtifactView from './DocumentArtifactView';
import { EmptyState } from '@/components/ui/empty-state';
import { LoadingState } from '@/components/ui/loading-state';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Card } from './ui/card';
import { IconButton } from './ui/icon-button';
import { Sheet, SheetContent } from './ui/sheet';

type TodoItem = {
  todo_id: number;
  title: string;
  status: 'open' | 'completed';
  created_at: string | null;
  updated_at: string | null;
};

type TodoArtifactData = {
  items: TodoItem[];
  total_count: number;
  open_count: number;
  completed_count: number;
};

type NoteArtifactData = {
  content: string;
  line_count: number;
  updated_at: string | null;
};

type ArtifactData =
  | { artifact_type: 'todo_list'; data: TodoArtifactData }
  | { artifact_type: 'note'; data: NoteArtifactData }
  | { artifact_type: 'memory'; data: Record<string, unknown> };

type ArtifactSidebarProps = {
  isOpen: boolean;
  onClose: () => void;
  artifactId: string | null;
  toolName?: string;
  conversationId: string | null;
  /**
   * overlay: current fixed slide-in sidebar
   * split: renders as a normal panel (to be placed in a split layout)
   */
  variant?: 'overlay' | 'split';
};

const ARTIFACT_TITLE_KEY_BY_TYPE: Record<
  ArtifactData['artifact_type'],
  string
> = {
  todo_list: 'components.artifact.types.todoList',
  note: 'components.artifact.types.note',
  memory: 'components.artifact.types.memory',
};

function getArtifactTitle(
  t: TFunction,
  artifact: ArtifactData | null,
  toolName?: string,
) {
  if (artifact) {
    const key = ARTIFACT_TITLE_KEY_BY_TYPE[artifact.artifact_type];
    return key ? t(key) : t('components.artifact.fallbackTitle');
  }

  const formattedToolName = (toolName ?? '')
    .replace(/_/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());

  return formattedToolName || t('components.artifact.fallbackTitle');
}

function TodoListView({ data }: { data: TodoArtifactData }) {
  const { t } = useTranslation();
  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <div className="mb-4 flex items-center justify-end">
        <div className="flex gap-2 text-xs">
          <Badge variant="success">
            {t('components.artifact.todo.done', {
              count: data.completed_count,
            })}
          </Badge>
          <Badge variant="info">
            {t('components.artifact.todo.open', { count: data.open_count })}
          </Badge>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {data.items.length === 0 ? (
          <p className="text-muted-foreground text-center text-sm">
            {t('components.artifact.todo.empty')}
          </p>
        ) : (
          <ul className="space-y-2">
            {data.items.map((item, index) => (
              <li
                key={`${item.todo_id}-${index}`}
                className={cn(
                  'flex items-start gap-3 rounded-lg border p-3',
                  item.status === 'completed'
                    ? 'border-success/50'
                    : 'border-border',
                )}
              >
                <span
                  className={cn(
                    'mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border-2',
                    item.status === 'completed'
                      ? 'border-success bg-success text-success-foreground'
                      : 'border-input',
                  )}
                >
                  {item.status === 'completed' && (
                    <svg
                      className="size-3"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={3}
                        d="M5 13l4 4L19 7"
                      />
                    </svg>
                  )}
                </span>
                <div className="flex-1">
                  <p
                    className={cn(
                      'text-sm',
                      item.status === 'completed'
                        ? 'text-muted-foreground line-through'
                        : 'text-foreground',
                    )}
                  >
                    {item.title}
                  </p>
                  <p className="text-muted-foreground mt-1 text-xs">
                    #{item.todo_id}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function NoteView({ data }: { data: NoteArtifactData }) {
  const { t } = useTranslation();
  const [isDarkTheme] = useDarkTheme();

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <div className="mb-4 flex items-center justify-end">
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground text-xs">
            {t('components.artifact.note.lines', { count: data.line_count })}
          </span>
          <CopyButton textToCopy={data.content || ''} side="bottom" />
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        {data.content ? (
          <div className="text-foreground flex flex-col gap-3 text-sm leading-normal wrap-break-word whitespace-pre-wrap">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                ...markdownHeadings,
                code(props) {
                  const {
                    children,
                    className,
                    node: _node,
                    ref: _ref,
                    ...rest
                  } = props;
                  void _node;
                  void _ref;
                  const match = /language-(\w+)/.exec(className || '');
                  const language = match ? match[1] : '';

                  return match ? (
                    <div className="group border-border relative my-2 overflow-hidden rounded-xl border">
                      <div className="bg-muted flex items-center justify-between px-2 py-1">
                        <span className="text-foreground text-xs font-medium">
                          {language}
                        </span>
                        <CopyButton
                          textToCopy={String(children).replace(/\n$/, '')}
                          side="bottom"
                        />
                      </div>
                      <SyntaxHighlighter
                        {...rest}
                        PreTag="div"
                        language={language}
                        /* eslint-disable-next-line shadcn/no-inline-styles -- SyntaxHighlighter's style prop is its Prism theme object (oneLight / vscDarkPlus), picked by theme at runtime; it is not CSS. See DESIGN.md, Approved exceptions. */
                        style={isDarkTheme ? vscDarkPlus : oneLight}
                        customStyle={{
                          margin: 0,
                          borderRadius: 0,
                          scrollbarWidth: 'thin',
                        }}
                      >
                        {String(children).replace(/\n$/, '')}
                      </SyntaxHighlighter>
                    </div>
                  ) : (
                    <code
                      className="bg-accent rounded-md px-2 py-1 text-xs font-normal"
                      {...rest}
                    >
                      {children}
                    </code>
                  );
                },
                ul({ children }) {
                  return (
                    <ul className="list-inside list-disc pl-4 whitespace-normal">
                      {children}
                    </ul>
                  );
                },
                ol({ children }) {
                  return (
                    <ol className="list-inside list-decimal pl-4 whitespace-normal">
                      {children}
                    </ol>
                  );
                },
                a({ children, href }) {
                  return (
                    <Button variant="link" size="inline" asChild>
                      <a href={href} target="_blank" rel="noopener noreferrer">
                        {children}
                      </a>
                    </Button>
                  );
                },
                p({ children }) {
                  return <p className="whitespace-pre-wrap">{children}</p>;
                },
                blockquote({ children }) {
                  return (
                    <blockquote className="border-border border-l-4 pl-4 italic">
                      {children}
                    </blockquote>
                  );
                },
              }}
            >
              {data.content}
            </ReactMarkdown>
          </div>
        ) : (
          <p className="text-muted-foreground text-sm">
            {t('components.artifact.note.empty')}
          </p>
        )}
      </div>
    </div>
  );
}

export default function ArtifactSidebar({
  isOpen,
  onClose,
  artifactId,
  toolName,
  conversationId,
  variant = 'overlay',
}: ArtifactSidebarProps) {
  const lastSuccessfulTodoArtifactIdRef = React.useRef<string | null>(null);
  const currentFetchIdRef = React.useRef<string | null>(null);
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const [artifact, setArtifact] = useState<ArtifactData | null>(null);
  const [documentArtifact, setDocumentArtifact] =
    useState<DocumentArtifact | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [effectiveArtifactId, setEffectiveArtifactId] = useState<string | null>(
    artifactId,
  );

  const title =
    documentArtifact?.title || getArtifactTitle(t, artifact, toolName);

  // Reset last successful todo artifact ID when conversation changes
  useEffect(() => {
    lastSuccessfulTodoArtifactIdRef.current = null;
  }, [conversationId]);

  // Reset effectiveArtifactId when artifactId changes
  useEffect(() => {
    if (!isOpen) {
      setEffectiveArtifactId(null);
      return;
    }
    setEffectiveArtifactId(artifactId);
  }, [isOpen, artifactId]);

  // Fetch artifact when effectiveArtifactId changes
  useEffect(() => {
    if (!isOpen || !effectiveArtifactId) {
      setArtifact(null);
      setDocumentArtifact(null);
      setError(null);
      setLoading(false);
      currentFetchIdRef.current = null;
      return;
    }

    // Generate a unique ID for this fetch
    const artifactIdToFetch = effectiveArtifactId;
    const fetchId = `${artifactIdToFetch}-${Date.now()}`;
    currentFetchIdRef.current = fetchId;

    setLoading(true);
    setError(null);

    // Document/file artifacts live behind the generalized /api/artifacts/<id>
    // endpoint; notes/todos behind the legacy /api/artifact/<id>. Try the
    // document path first and fall back to the legacy flow on a non-document
    // shape so a single id resolves cleanly either way.
    userService
      .getDocumentArtifact(artifactIdToFetch, token)
      .then(async (res: Response) => {
        if (currentFetchIdRef.current !== fetchId) return true;
        if (!res.ok) return false;
        let data: any = null;
        try {
          data = await res.json();
        } catch {
          data = null;
        }
        if (currentFetchIdRef.current !== fetchId) return true;
        if (data?.success && isDocumentArtifact(data.artifact)) {
          setDocumentArtifact(data.artifact);
          setArtifact(null);
          setLoading(false);
          return true;
        }
        return false;
      })
      .catch(() => false)
      .then((handled) => {
        if (handled) return;
        if (currentFetchIdRef.current !== fetchId) return;
        setDocumentArtifact(null);
        fetchLegacyArtifact(fetchId);
      });

    // Legacy notes/todo fetch (unchanged behavior).
    function fetchLegacyArtifact(fetchId: string) {
      userService
        .getArtifact(artifactIdToFetch, token)
        .then(async (res: any) => {
          // Ignore if this is not the current fetch
          if (currentFetchIdRef.current !== fetchId) return;

          const isResponseLike = res && typeof res.json === 'function';
          const status = isResponseLike ? res.status : undefined;
          const ok = isResponseLike ? Boolean(res.ok) : true;

          let data: any = res;
          if (isResponseLike) {
            try {
              data = await res.json();
            } catch {
              data = null;
            }
          }

          // Check again after async operation
          if (currentFetchIdRef.current !== fetchId) return;

          if (ok && data?.success && data?.artifact) {
            setArtifact(data.artifact);
            // Remember the last successful todo artifact id so we can fallback if a newer id 404s.
            if (data.artifact?.artifact_type === 'todo_list') {
              lastSuccessfulTodoArtifactIdRef.current = effectiveArtifactId;
            }
            setLoading(false);
            return;
          }

          const isTodoTool = (toolName ?? '').toLowerCase().includes('todo');

          // If the latest todo artifact id is missing (404), fall back to the last known good one
          // so the backend can still resolve `tool_id` for the todo list.
          if (
            status === 404 &&
            isTodoTool &&
            lastSuccessfulTodoArtifactIdRef.current &&
            lastSuccessfulTodoArtifactIdRef.current !== effectiveArtifactId
          ) {
            // Update effectiveArtifactId to trigger a new fetch with the fallback id
            setEffectiveArtifactId(lastSuccessfulTodoArtifactIdRef.current);
            setLoading(false);
            return;
          }

          // Ensure we show a visible error state instead of rendering nothing.
          const message =
            data?.message ||
            (status === 404 ? t('components.artifact.notFound') : null) ||
            t('components.artifact.loadFailed');
          setError(message);
          setLoading(false);
        })
        .catch(() => {
          // Ignore if this is not the current fetch
          if (currentFetchIdRef.current !== fetchId) return;
          setError(t('components.artifact.fetchFailed'));
          setLoading(false);
        });
    }
  }, [
    isOpen,
    effectiveArtifactId,
    token,
    toolName,
    conversationId,
    refreshNonce,
  ]);

  const renderContent = () => {
    if (loading) {
      return <LoadingState fill="parent" />;
    }
    if (error) {
      return (
        <EmptyState
          tone="destructive"
          size="sm"
          illustration="none"
          title={error}
          className="h-full"
          action={
            <Button
              variant="outline"
              size="sm"
              onClick={() => setRefreshNonce((n) => n + 1)}
            >
              {t('retry')}
            </Button>
          }
        />
      );
    }
    if (documentArtifact) {
      return (
        <DocumentArtifactView
          artifact={documentArtifact}
          onRefresh={() => setRefreshNonce((n) => n + 1)}
        />
      );
    }
    // Avoid rendering an empty panel if the artifact couldn't be loaded for any reason.
    if (!artifact) {
      return (
        <div className="flex h-full items-center justify-center">
          <p className="text-muted-foreground text-sm">
            {t('components.artifact.notFound')}
          </p>
        </div>
      );
    }
    switch (artifact.artifact_type) {
      case 'todo_list':
        return <TodoListView data={artifact.data} />;
      case 'note':
        return <NoteView data={artifact.data} />;
      default:
        return (
          <Card
            variant="filled"
            padding="sm"
            className="max-h-full overflow-auto"
          >
            <pre className="text-muted-foreground font-mono text-xs wrap-break-word whitespace-pre-wrap">
              {JSON.stringify(artifact, null, 2)}
            </pre>
          </Card>
        );
    }
  };

  if (variant === 'split') {
    if (!isOpen) return null;

    return (
      <div className="flex h-full w-full flex-col p-3">
        {/* Space for top bar / actions */}
        <div className="h-14 shrink-0" />
        {/* Artifact panel */}
        <div className="border-border flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border bg-transparent">
          <div className="flex w-full items-center justify-between px-4 py-2">
            <span className="text-muted-foreground text-sm font-medium">
              {title}
            </span>
            <IconButton
              label={t('agents.close')}
              side="bottom"
              variant="ghost"
              size="icon-sm"
              shape="pill"
              onClick={onClose}
            >
              <X aria-hidden="true" className="size-4" />
            </IconButton>
          </div>
          <div className="flex-1 overflow-hidden p-4">{renderContent()}</div>
        </div>
      </div>
    );
  }

  return (
    <Sheet
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <SheetContent
        side="right"
        showCloseButton={false}
        title={title || t('components.artifact.preview')}
        className="h-full w-80 p-0 sm:w-96 sm:max-w-none"
      >
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="border-border flex w-full items-center justify-between border-b px-4 py-3">
            <span className="text-muted-foreground text-sm font-medium">
              {title}
            </span>
            <IconButton
              label={t('agents.close')}
              side="bottom"
              variant="ghost"
              size="icon"
              shape="pill"
              onClick={onClose}
            >
              <X aria-hidden="true" className="size-4" />
            </IconButton>
          </div>
          <div className="flex-1 overflow-hidden p-4">{renderContent()}</div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
