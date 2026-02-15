import React, { useEffect, useState } from 'react';
import { useSelector } from 'react-redux';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import {
  oneLight,
  vscDarkPlus,
} from 'react-syntax-highlighter/dist/cjs/styles/prism';

import Exit from '../assets/exit.svg';
import { selectToken } from '../preferences/preferenceSlice';
import userService from '../api/services/userService';
import Spinner from './Spinner';
import CopyButton from './CopyButton';
import { useDarkTheme } from '../hooks';

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

const ARTIFACT_TITLE_BY_TYPE: Record<ArtifactData['artifact_type'], string> = {
  todo_list: 'Todo List',
  note: 'Note',
  memory: 'Memory',
};

function getArtifactTitle(artifact: ArtifactData | null, toolName?: string) {
  if (artifact) return ARTIFACT_TITLE_BY_TYPE[artifact.artifact_type] ?? 'Artifact';

  const formattedToolName = (toolName ?? '')
    .replace(/_/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());

  return formattedToolName || 'Artifact';
}

function TodoListView({ data }: { data: TodoArtifactData }) {
  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <div className="mb-4 flex items-center justify-end">
        <div className="flex gap-2 text-xs">
          <span className="rounded-full bg-green-100 px-2 py-1 text-green-700 dark:bg-green-900/30 dark:text-green-400">
            {data.completed_count} done
          </span>
          <span className="rounded-full bg-blue-100 px-2 py-1 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
            {data.open_count} open
          </span>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {data.items.length === 0 ? (
          <p className="text-center text-sm text-gray-500 dark:text-gray-400">
            No todos yet
          </p>
        ) : (
          <ul className="space-y-2">
            {data.items.map((item, index) => (
              <li
                key={`${item.todo_id}-${index}`}
                className={`flex items-start gap-3 rounded-lg border p-3 ${
                  item.status === 'completed'
                    ? 'border-green-300 dark:border-green-800'
                    : 'border-gray-200 dark:border-gray-700'
                }`}
              >
                <span
                  className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 ${
                    item.status === 'completed'
                      ? 'border-green-500 bg-green-500 text-white'
                      : 'border-gray-300 dark:border-gray-600'
                  }`}
                >
                  {item.status === 'completed' && (
                    <svg
                      className="h-3 w-3"
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
                    className={`text-sm ${
                      item.status === 'completed'
                        ? 'text-gray-500 line-through dark:text-gray-400'
                        : 'text-gray-900 dark:text-white'
                    }`}
                  >
                    {item.title}
                  </p>
                  <p className="mt-1 text-xs text-gray-400">#{item.todo_id}</p>
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
  const [isDarkTheme] = useDarkTheme();

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <div className="mb-4 flex items-center justify-end">
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500 dark:text-gray-400">
            {data.line_count} lines
          </span>
          <CopyButton textToCopy={data.content || ''} />
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        {data.content ? (
          <ReactMarkdown
            className="flex flex-col gap-3 text-sm leading-normal break-words whitespace-pre-wrap text-gray-800 dark:text-gray-200"
            remarkPlugins={[remarkGfm]}
            components={{
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
                  <div className="group border-light-silver dark:border-raisin-black relative my-2 overflow-hidden rounded-[14px] border">
                    <div className="bg-platinum dark:bg-eerie-black-2 flex items-center justify-between px-2 py-1">
                      <span className="text-just-black dark:text-chinese-white text-xs font-medium">
                        {language}
                      </span>
                      <CopyButton
                        textToCopy={String(children).replace(/\n$/, '')}
                      />
                    </div>
                    <SyntaxHighlighter
                      {...rest}
                      PreTag="div"
                      language={language}
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
                    className="dark:bg-independence dark:text-bright-gray rounded-[6px] bg-gray-200 px-[8px] py-[4px] text-xs font-normal"
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
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-600 hover:underline dark:text-blue-400"
                  >
                    {children}
                  </a>
                );
              },
              p({ children }) {
                return <p className="whitespace-pre-wrap">{children}</p>;
              },
              h1({ children }) {
                return <h1 className="text-xl font-bold">{children}</h1>;
              },
              h2({ children }) {
                return <h2 className="text-lg font-bold">{children}</h2>;
              },
              h3({ children }) {
                return <h3 className="text-base font-bold">{children}</h3>;
              },
              blockquote({ children }) {
                return (
                  <blockquote className="border-l-4 border-gray-300 pl-4 italic dark:border-gray-600">
                    {children}
                  </blockquote>
                );
              },
            }}
          >
            {data.content}
          </ReactMarkdown>
        ) : (
          <p className="text-sm text-gray-500 dark:text-gray-400">Empty note</p>
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
  const sidebarRef = React.useRef<HTMLDivElement>(null);
  const lastSuccessfulTodoArtifactIdRef = React.useRef<string | null>(null);
  const currentFetchIdRef = React.useRef<string | null>(null);
  const token = useSelector(selectToken);
  const [artifact, setArtifact] = useState<ArtifactData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [effectiveArtifactId, setEffectiveArtifactId] = useState<string | null>(
    artifactId,
  );

  const title = getArtifactTitle(artifact, toolName);

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
      setError(null);
      setLoading(false);
      currentFetchIdRef.current = null;
      return;
    }

    // Generate a unique ID for this fetch
    const fetchId = `${effectiveArtifactId}-${Date.now()}`;
    currentFetchIdRef.current = fetchId;
    
    setLoading(true);
    setError(null);
    
    // Note: For todo artifacts, the endpoint always returns all todos for the tool; will be coversation scoped later
    userService
      .getArtifact(effectiveArtifactId, token)
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
          (status === 404 ? 'Artifact not found' : null) ||
          'Failed to load artifact';
        setError(message);
        setLoading(false);
      })
      .catch((err) => {
        // Ignore if this is not the current fetch
        if (currentFetchIdRef.current !== fetchId) return;
        setError('Failed to fetch artifact');
        setLoading(false);
      });
  }, [isOpen, effectiveArtifactId, token, toolName, conversationId]);

  const handleClickOutside = (event: MouseEvent) => {
    if (
      sidebarRef.current &&
      !sidebarRef.current.contains(event.target as Node)
    ) {
      onClose();
    }
  };

  useEffect(() => {
    if (variant === 'overlay' && isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen, variant]);

  const renderContent = () => {
    if (loading) {
      return (
        <div className="flex h-full items-center justify-center">
          <Spinner />
        </div>
      );
    }
    if (error) {
      return (
        <div className="flex h-full items-center justify-center">
          <p className="text-sm text-red-500">{error}</p>
        </div>
      );
    }
    // Avoid rendering an empty panel if the artifact couldn't be loaded for any reason.
    if (!artifact) {
      return (
        <div className="flex h-full items-center justify-center">
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Artifact not found
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
          <pre className="text-xs text-gray-600 dark:text-gray-400">
            {JSON.stringify(artifact, null, 2)}
          </pre>
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
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-gray-200 bg-transparent dark:border-gray-700">
          <div className="flex w-full items-center justify-between px-4 py-2">
            <span className="text-sm font-medium text-gray-600 dark:text-gray-300">
              {title}
            </span>
            <button
              className="rounded-full p-1 hover:bg-gray-100 dark:hover:bg-gray-800"
              onClick={onClose}
            >
              <img
                className="h-3 w-3 filter dark:invert"
                src={Exit}
                alt="Close"
              />
            </button>
          </div>
          <div className="flex-1 overflow-hidden p-4">{renderContent()}</div>
        </div>
      </div>
    );
  }

  return (
    <div ref={sidebarRef} className="h-vh relative">
      <div
        className={`dark:bg-chinese-black fixed top-0 right-0 z-50 flex h-full w-80 transform flex-col bg-white shadow-xl transition-all duration-300 sm:w-96 ${
          isOpen ? 'translate-x-0' : 'translate-x-full'
        } border-l border-[#9ca3af]/10`}
      >
        <div className="flex w-full items-center justify-between border-b border-gray-200 px-4 py-3 dark:border-gray-700">
          <span className="text-sm font-medium text-gray-600 dark:text-gray-300">
            {title}
          </span>
          <button
            className="hover:bg-gray-1000 dark:hover:bg-gun-metal rounded-full p-2"
            onClick={onClose}
          >
            <img
              className="h-4 w-4 filter dark:invert"
              src={Exit}
              alt="Close"
            />
          </button>
        </div>
        <div className="flex-1 overflow-hidden p-4">{renderContent()}</div>
      </div>
    </div>
  );
}
