import 'katex/dist/katex.min.css';

import { forwardRef, Fragment, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import ReactMarkdown from 'react-markdown';
import { useSelector } from 'react-redux';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import {
  oneLight,
  vscDarkPlus,
} from 'react-syntax-highlighter/dist/cjs/styles/prism';
import rehypeKatex from 'rehype-katex';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';

import ChevronDown from '../assets/chevron-down.svg';
import Cloud from '../assets/cloud.svg';
import DocsGPT3 from '../assets/cute_docsgpt3.svg';
import Dislike from '../assets/dislike.svg?react';
import Document from '../assets/document.svg';
import DocumentationDark from '../assets/documentation-dark.svg';
import Edit from '../assets/edit.svg';
import Like from '../assets/like.svg?react';
import Link from '../assets/link.svg';
import Sources from '../assets/sources.svg';
import UserIcon from '../assets/user.svg';
import Accordion from '../components/Accordion';
import Avatar from '../components/Avatar';
import CopyButton from '../components/CopyButton';
import MermaidRenderer from '../components/MermaidRenderer';
import Sidebar from '../components/Sidebar';
import Spinner from '../components/Spinner';
import SpeakButton from '../components/TextToSpeechButton';
import { useDarkTheme, useOutsideAlerter } from '../hooks';
import {
  selectChunks,
  selectSelectedDocs,
} from '../preferences/preferenceSlice';
import classes from './ConversationBubble.module.css';
import { FEEDBACK, MESSAGE_TYPE, ResearchState } from './conversationModels';
import ResearchProgress from './ResearchProgress';
import { ToolCallsType } from './types';

const DisableSourceFE = import.meta.env.VITE_DISABLE_SOURCE_FE || false;

const ConversationBubble = forwardRef<
  HTMLDivElement,
  {
    message?: string;
    type: MESSAGE_TYPE;
    className?: string;
    feedback?: FEEDBACK;
    handleFeedback?: (feedback: FEEDBACK) => void;
    thought?: string;
    sources?: { title: string; text: string; link: string }[];
    toolCalls?: ToolCallsType[];
    research?: ResearchState;
    retryBtn?: React.ReactElement;
    questionNumber?: number;
    isStreaming?: boolean;
    handleUpdatedQuestionSubmission?: (
      updatedquestion?: string,
      updated?: boolean,
      index?: number,
    ) => void;
    filesAttached?: { id: string; fileName: string }[];
    onOpenArtifact?: (artifact: { id: string; toolName: string }) => void;
    onToolAction?: (
      callId: string,
      decision: 'approved' | 'denied',
      comment?: string,
    ) => void;
  }
>(function ConversationBubble(
  {
    message,
    type,
    className,
    feedback,
    handleFeedback,
    thought,
    sources,
    toolCalls,
    research,
    retryBtn,
    questionNumber,
    isStreaming,
    handleUpdatedQuestionSubmission,
    filesAttached,
    onOpenArtifact,
    onToolAction,
  },
  ref,
) {
  const { t } = useTranslation();
  const [isDarkTheme] = useDarkTheme();
  // const bubbleRef = useRef<HTMLDivElement | null>(null);
  const chunks = useSelector(selectChunks);
  const selectedDocs = useSelector(selectSelectedDocs);
  const [isEditClicked, setIsEditClicked] = useState(false);
  const [editInputBox, setEditInputBox] = useState<string>('');
  const messageRef = useRef<HTMLDivElement>(null);
  const [shouldShowToggle, setShouldShowToggle] = useState(false);

  const [activeTooltip, setActiveTooltip] = useState<number | null>(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(false);
  const editableQueryRef = useRef<HTMLDivElement>(null);
  const [isQuestionCollapsed, setIsQuestionCollapsed] = useState(true);

  const completedArtifactCalls = (toolCalls ?? []).filter(
    (toolCall) => toolCall.artifact_id && toolCall.status === 'completed',
  );
  const primaryArtifactCall =
    completedArtifactCalls[completedArtifactCalls.length - 1] ?? null;
  const artifactCount = completedArtifactCalls.length;

  const formatToolName = (toolName: string | undefined): string => {
    if (!toolName) return '';
    return toolName
      .split('_')
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
      .join(' ');
  };

  useOutsideAlerter(editableQueryRef, () => setIsEditClicked(false), [], true);

  useEffect(() => {
    if (messageRef.current) {
      const height = messageRef.current.scrollHeight;
      setShouldShowToggle(height > 84);
    }
  }, [message]);

  const handleEditClick = () => {
    if (!editInputBox.trim() || editInputBox.trim() === (message ?? '').trim())
      return;
    setIsEditClicked(false);
    handleUpdatedQuestionSubmission?.(editInputBox, true, questionNumber);
  };
  let bubble;
  if (type === 'QUESTION') {
    bubble = (
      <div className={`group ${className}`}>
        <div className="flex flex-col items-end">
          {filesAttached && filesAttached.length > 0 && (
            <div className="mr-12 mb-4 flex flex-wrap justify-end gap-2">
              {filesAttached.map((file, index) => (
                <div
                  key={index}
                  title={file.fileName}
                  className="dark:text-foreground dark:bg-accent text-muted-foreground bg-muted flex items-center rounded-xl p-2 text-[14px]"
                >
                  <div className="bg-primary mr-2 items-center justify-center rounded-lg p-[5.5px]">
                    <img
                      src={DocumentationDark}
                      alt="Attachment"
                      className="h-[15px] w-[15px] object-fill"
                    />
                  </div>
                  <span className="max-w-[150px] truncate font-normal">
                    {file.fileName}
                  </span>
                </div>
              ))}
            </div>
          )}
          <div
            ref={ref}
            className={`flex flex-row-reverse justify-items-start`}
          >
            <Avatar
              size="SMALL"
              className="mt-2 shrink-0 text-2xl"
              avatar={
                <img className="mr-1 rounded-full" width={30} src={UserIcon} />
              }
            />
            {!isEditClicked && (
              <>
                <div className="relative mr-2 flex w-full flex-col">
                  <div className="from-medium-purple to-slate-blue mr-2 ml-2 flex max-w-full items-start gap-2 rounded-[28px] bg-linear-to-b px-5 py-4 text-sm leading-normal wrap-break-word whitespace-pre-wrap text-white sm:text-base">
                    <div
                      ref={messageRef}
                      className={`${isQuestionCollapsed ? 'line-clamp-4' : ''} w-full`}
                    >
                      {message}
                    </div>
                    {shouldShowToggle && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setIsQuestionCollapsed(!isQuestionCollapsed);
                        }}
                        className="ml-1 rounded-full p-2 hover:bg-[#D9D9D933]"
                      >
                        <img
                          src={ChevronDown}
                          alt="Toggle"
                          width={24}
                          height={24}
                          className={`transform invert transition-transform duration-200 ${isQuestionCollapsed ? '' : 'rotate-180'}`}
                        />
                      </button>
                    )}
                  </div>
                </div>
                <button
                  onClick={() => {
                    setIsEditClicked(true);
                    setEditInputBox(message ?? '');
                  }}
                  className={`hover:bg-accent dark:hover:bg-accent mt-3 flex h-fit shrink-0 cursor-pointer items-center rounded-full p-2 pt-1.5 pl-1.5 ${isEditClicked ? 'visible' : 'invisible group-hover:visible'}`}
                >
                  <img src={Edit} alt="Edit" className="cursor-pointer" />
                </button>
              </>
            )}
          </div>
          {isEditClicked && (
            <div
              ref={editableQueryRef}
              className="mx-auto flex w-full flex-col gap-4 rounded-lg bg-transparent p-4"
            >
              <textarea
                placeholder={t('conversation.edit.placeholder')}
                onChange={(e) => {
                  setEditInputBox(e.target.value);
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleEditClick();
                  }
                }}
                rows={5}
                value={editInputBox}
                className="border-border text-carbon dark:border-philippine-grey dark:text-foreground w-full resize-none rounded-3xl border px-4 py-3 text-base leading-relaxed focus:outline-hidden"
              />
              <div className="flex items-center justify-end gap-2">
                <button
                  className="text-primary hover:bg-muted hover:text-foreground dark:hover:bg-accent dark:hover:text-foreground rounded-full px-4 py-2 text-sm font-semibold transition-colors"
                  onClick={() => setIsEditClicked(false)}
                >
                  {t('conversation.edit.cancel')}
                </button>
                <button
                  className="bg-primary not-disabled:hover:bg-primary/90 not-disabled:dark:hover:bg-primary/90 disabled:bg-primary/30 rounded-full px-4 py-2 text-sm font-medium text-white transition-colors disabled:cursor-not-allowed"
                  onClick={handleEditClick}
                  disabled={
                    !editInputBox.trim() ||
                    editInputBox.trim() === (message ?? '').trim()
                  }
                >
                  {t('conversation.edit.update')}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  } else {
    const preprocessLaTeX = (content: string) => {
      // Replace block-level LaTeX delimiters \[ \] with $$ $$
      const blockProcessedContent = content.replace(
        /\\\[(.*?)\\\]/gs,
        (_, equation) => `$$${equation}$$`,
      );

      // Replace inline LaTeX delimiters \( \) with $ $
      const inlineProcessedContent = blockProcessedContent.replace(
        /\\\((.*?)\\\)/gs,
        (_, equation) => `$${equation}$`,
      );

      return inlineProcessedContent;
    };
    const processMarkdownContent = (content: string) => {
      let processedContent = preprocessLaTeX(content);

      // Convert citation references [N] into markdown links [N](#cite-N)
      // so ReactMarkdown renders them as <a> tags we can style.
      // Avoid matching inside code blocks or existing links.
      processedContent = processedContent.replace(
        /(?<!\[)\[(\d+)\](?!\()/g,
        (_, num) => `[${num}](#cite-${num})`,
      );

      const contentSegments: Array<{
        type: 'text' | 'mermaid';
        content: string;
      }> = [];

      let lastIndex = 0;
      const regex = /```mermaid\n([\s\S]*?)```/g;
      let match;

      while ((match = regex.exec(processedContent)) !== null) {
        const textBefore = processedContent.substring(lastIndex, match.index);
        if (textBefore) {
          contentSegments.push({ type: 'text', content: textBefore });
        }

        contentSegments.push({ type: 'mermaid', content: match[1].trim() });

        lastIndex = match.index + match[0].length;
      }

      const textAfter = processedContent.substring(lastIndex);
      if (textAfter) {
        contentSegments.push({ type: 'text', content: textAfter });
      }

      return contentSegments;
    };

    bubble = (
      <div
        ref={ref}
        className={`flex flex-wrap self-start ${className} group dark:text-foreground flex-col`}
      >
        {DisableSourceFE ||
        type === 'ERROR' ||
        sources?.length === 0 ||
        sources?.some((source) => source.link === 'None')
          ? null
          : sources && (
              <div className="mb-4 flex flex-col flex-wrap items-start self-start lg:flex-nowrap">
                <div className="my-2 flex flex-row items-center justify-center gap-3">
                  <Avatar
                    className="h-[26px] w-[30px] text-xl"
                    avatar={
                      <img
                        src={Sources}
                        alt={t('conversation.sources.title')}
                        className="h-full w-full object-fill"
                      />
                    }
                  />
                  <p className="text-base font-semibold">
                    {t('conversation.sources.title')}
                  </p>
                </div>
                <div className="fade-in mr-5 ml-3 max-w-[90vw] md:max-w-[70vw] lg:max-w-[50vw]">
                  <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
                    {sources?.slice(0, 3)?.map((source, index) => (
                      <div
                        key={index}
                        id={`source-${index}`}
                        className="relative transition-all duration-300"
                      >
                        <div
                          className="bg-muted hover:bg-accent dark:bg-answer-bubble dark:hover:bg-muted h-28 cursor-pointer rounded-4xl p-4"
                          onMouseOver={() => setActiveTooltip(index)}
                          onMouseOut={() => setActiveTooltip(null)}
                        >
                          <p className="ellipsis-text h-12 text-xs wrap-break-word">
                            {source.text}
                          </p>
                          <div
                            className={`mt-3.5 flex flex-row items-center gap-1.5 underline-offset-2 ${
                              source.link && source.link !== 'local'
                                ? 'hover:text-[#007DFF] hover:underline dark:hover:text-blue-400'
                                : ''
                            }`}
                            onClick={() =>
                              source.link && source.link !== 'local'
                                ? window.open(
                                    source.link,
                                    '_blank',
                                    'noopener, noreferrer',
                                  )
                                : null
                            }
                          >
                            <img
                              src={Document}
                              alt="Document"
                              className="h-[17px] w-[17px] object-fill"
                            />
                            <p
                              className="mt-0.5 truncate text-xs"
                              title={
                                source.link && source.link !== 'local'
                                  ? source.link
                                  : source.title
                              }
                            >
                              {source.link && source.link !== 'local'
                                ? source.link
                                : source.title}
                            </p>
                          </div>
                        </div>
                        {activeTooltip === index && (
                          <div
                            className={`dark:bg-card dark:text-foreground absolute left-1/2 z-50 max-h-48 w-40 translate-x-[-50%] translate-y-[3px] rounded-xl bg-[#FBFBFB] p-4 text-black shadow-xl sm:w-56`}
                            onMouseOver={() => setActiveTooltip(index)}
                            onMouseOut={() => setActiveTooltip(null)}
                          >
                            <p className="line-clamp-6 max-h-[164px] overflow-hidden rounded-md text-sm wrap-break-word text-ellipsis">
                              {source.text}
                            </p>
                          </div>
                        )}
                      </div>
                    ))}
                    {(sources?.length ?? 0) > 3 && (
                      <div
                        className="bg-muted text-primary hover:bg-accent hover:text-primary dark:bg-answer-bubble dark:hover:bg-muted dark:hover:text-primary flex h-28 cursor-pointer flex-col-reverse rounded-4xl p-4"
                        onClick={() => setIsSidebarOpen(true)}
                      >
                        <p className="ellipsis-text h-22 text-xs">
                          {t('conversation.sources.view_more', {
                            count: sources?.length ? sources.length - 3 : 0,
                          })}
                        </p>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
        {research && <ResearchProgress research={research} />}
        {toolCalls && toolCalls.length > 0 && (
          <ToolCalls toolCalls={toolCalls} onToolAction={onToolAction} />
        )}
        {!message && primaryArtifactCall?.artifact_id && onOpenArtifact && (
          <div className="my-2 ml-2 flex justify-start">
            <button
              type="button"
              onClick={() =>
                onOpenArtifact({
                  id: primaryArtifactCall.artifact_id!,
                  toolName: primaryArtifactCall.tool_name,
                })
              }
              className="flex items-center gap-2 rounded-full bg-purple-100 px-3 py-2 text-sm font-medium text-purple-700 transition-colors hover:bg-purple-200 dark:bg-purple-900/30 dark:text-purple-300 dark:hover:bg-purple-900/50"
            >
              <svg
                className="h-4 w-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                />
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
                />
              </svg>
              {primaryArtifactCall.tool_name
                ? formatToolName(primaryArtifactCall.tool_name)
                : artifactCount > 1
                  ? `View artifacts (${artifactCount})`
                  : 'View artifact'}
            </button>
          </div>
        )}
        {thought && (
          <Thought thought={thought} preprocessLaTeX={preprocessLaTeX} />
        )}
        {message && (
          <div className="flex max-w-full flex-col flex-wrap items-start self-start lg:flex-nowrap">
            <div className="my-2 flex flex-row items-center justify-center gap-3">
              <Avatar
                className="h-[34px] w-[34px] text-2xl"
                avatar={
                  <img
                    src={DocsGPT3}
                    alt={t('conversation.answer')}
                    className="h-full w-full object-cover"
                  />
                }
              />
              <p className="text-base font-semibold">
                {t('conversation.answer')}
              </p>
            </div>
            <div
              className={`fade-in-bubble bg-answer-bubble mr-5 flex max-w-full rounded-[18px] px-6 py-4.5 ${
                type === 'ERROR'
                  ? 'text-destructive/80 dark:border-destructive dark:bg-destructive/15 relative flex-row items-center rounded-full border border-transparent bg-[#FFE7E7] p-2 py-5 text-sm font-normal dark:text-white'
                  : 'flex-col rounded-3xl'
              }`}
            >
              {(() => {
                const contentSegments = processMarkdownContent(message);
                return (
                  <>
                    {contentSegments.map((segment, index) => (
                      <Fragment key={index}>
                        {segment.type === 'text' ? (
                          <ReactMarkdown
                            className="fade-in flex flex-col gap-3 leading-normal wrap-break-word whitespace-pre-wrap"
                            remarkPlugins={[remarkGfm, remarkMath]}
                            rehypePlugins={[rehypeKatex]}
                            components={{
                              a({ href, children }) {
                                if (href?.startsWith('#cite-')) {
                                  const num = href.replace('#cite-', '');
                                  const sourceIdx = parseInt(num, 10) - 1;
                                  return (
                                    <button
                                      type="button"
                                      onClick={() => {
                                        const el = document.getElementById(
                                          `source-${sourceIdx}`,
                                        );
                                        if (el) {
                                          el.scrollIntoView({
                                            behavior: 'smooth',
                                            block: 'center',
                                          });
                                          el.classList.add(
                                            'ring-2',
                                            'ring-purple-500',
                                          );
                                          setTimeout(
                                            () =>
                                              el.classList.remove(
                                                'ring-2',
                                                'ring-purple-500',
                                              ),
                                            2000,
                                          );
                                        }
                                      }}
                                      className="mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-purple-100 px-1.5 text-xs font-semibold text-purple-700 transition-colors hover:bg-purple-200 dark:bg-purple-900/40 dark:text-purple-300 dark:hover:bg-purple-900/60"
                                      title={`Jump to source ${num}`}
                                    >
                                      {num}
                                    </button>
                                  );
                                }
                                return (
                                  <a
                                    href={href}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                  >
                                    {children}
                                  </a>
                                );
                              },
                              code(props) {
                                const {
                                  children,
                                  className,
                                  node,
                                  ref,
                                  ...rest
                                } = props;
                                const match = /language-(\w+)/.exec(
                                  className || '',
                                );
                                const language = match ? match[1] : '';

                                return match ? (
                                  <div className="group border-border relative overflow-hidden rounded-[14px] border">
                                    <div className="bg-platinum dark:bg-muted flex items-center justify-between px-2 py-1">
                                      <span className="text-foreground dark:text-foreground text-xs font-medium">
                                        {language}
                                      </span>
                                      <CopyButton
                                        textToCopy={String(children).replace(
                                          /\n$/,
                                          '',
                                        )}
                                      />
                                    </div>
                                    <SyntaxHighlighter
                                      {...rest}
                                      PreTag="div"
                                      language={language}
                                      style={
                                        isDarkTheme ? vscDarkPlus : oneLight
                                      }
                                      className="mt-0!"
                                      customStyle={{
                                        margin: 0,
                                        borderRadius: 0,
                                      }}
                                    >
                                      {String(children).replace(/\n$/, '')}
                                    </SyntaxHighlighter>
                                  </div>
                                ) : (
                                  <code className="dark:bg-accent dark:text-foreground rounded-[6px] bg-gray-200 px-2 py-1 text-xs font-normal whitespace-pre-line">
                                    {children}
                                  </code>
                                );
                              },
                              ul({ children }) {
                                return (
                                  <ul
                                    className={`list-inside list-disc pl-4 whitespace-normal ${classes.list}`}
                                  >
                                    {children}
                                  </ul>
                                );
                              },
                              ol({ children }) {
                                return (
                                  <ol
                                    className={`list-inside list-decimal pl-4 whitespace-normal ${classes.list}`}
                                  >
                                    {children}
                                  </ol>
                                );
                              },
                              table({ children }) {
                                return (
                                  <div className="border-border relative overflow-x-auto rounded-lg border">
                                    <table className="dark:text-foreground w-full text-left text-gray-700">
                                      {children}
                                    </table>
                                  </div>
                                );
                              },
                              thead({ children }) {
                                return (
                                  <thead className="bg-muted text-foreground text-xs uppercase">
                                    {children}
                                  </thead>
                                );
                              },
                              tr({ children }) {
                                return (
                                  <tr className="border-border odd:bg-card even:bg-muted border-b">
                                    {children}
                                  </tr>
                                );
                              },
                              th({ children }) {
                                return (
                                  <th className="px-6 py-3">{children}</th>
                                );
                              },
                              td({ children }) {
                                return (
                                  <td className="px-6 py-3">{children}</td>
                                );
                              },
                            }}
                          >
                            {segment.content}
                          </ReactMarkdown>
                        ) : (
                          <div
                            className="my-4 w-full"
                            style={{ minWidth: '100%' }}
                          >
                            <MermaidRenderer
                              code={segment.content}
                              isLoading={isStreaming}
                            />
                          </div>
                        )}
                      </Fragment>
                    ))}
                  </>
                );
              })()}
            </div>
          </div>
        )}
        {message && (
          <div className="my-2 ml-2 flex justify-start">
            {type === 'ERROR' ? (
              <div className="relative mr-2 block items-center justify-center">
                <div>{retryBtn}</div>
              </div>
            ) : (
              <>
                {primaryArtifactCall?.artifact_id && onOpenArtifact && (
                  <div className="relative mr-2 flex items-center justify-center">
                    <button
                      type="button"
                      onClick={() =>
                        onOpenArtifact({
                          id: primaryArtifactCall.artifact_id!,
                          toolName: primaryArtifactCall.tool_name,
                        })
                      }
                      className="flex items-center gap-2 rounded-full bg-purple-100 px-3 py-2 text-sm font-medium text-purple-700 transition-colors hover:bg-purple-200 dark:bg-purple-900/30 dark:text-purple-300 dark:hover:bg-purple-900/50"
                      aria-label="View artifacts"
                    >
                      <svg
                        className="h-4 w-4"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                        />
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
                        />
                      </svg>
                      {primaryArtifactCall.tool_name
                        ? formatToolName(primaryArtifactCall.tool_name)
                        : artifactCount > 1
                          ? `Artifacts (${artifactCount})`
                          : 'Artifact'}
                    </button>
                  </div>
                )}
                {!isStreaming && (
                  <>
                    <div className="relative mr-2 block items-center justify-center">
                      <CopyButton textToCopy={message} />
                    </div>
                    {research && message && (
                      <div className="relative mr-2 block items-center justify-center">
                        <button
                          type="button"
                          onClick={() => {
                            const blob = new Blob([message], {
                              type: 'text/markdown',
                            });
                            const url = URL.createObjectURL(blob);
                            const link = document.createElement('a');
                            link.href = url;
                            link.download = `research-report.md`;
                            link.click();
                            URL.revokeObjectURL(url);
                          }}
                          className="bg-card dark:hover:bg-accent hover:bg-muted flex cursor-pointer items-center justify-center rounded-full p-2 dark:bg-transparent"
                          aria-label="Export as Markdown"
                          title="Export as Markdown"
                        >
                          <svg
                            className="stroke-muted-foreground h-5 w-5"
                            fill="none"
                            viewBox="0 0 24 24"
                            strokeWidth={1.5}
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3"
                            />
                          </svg>
                        </button>
                      </div>
                    )}
                    <div className="relative mr-2 block items-center justify-center">
                      <SpeakButton text={message} />
                    </div>
                    {handleFeedback && (
                      <>
                        <div className="relative mr-2 flex items-center justify-center">
                          <button
                            type="button"
                            className="hover:bg-accent flex cursor-pointer items-center justify-center rounded-full bg-transparent p-2"
                            onClick={() => {
                              if (feedback === 'LIKE') {
                                handleFeedback?.(null);
                              } else {
                                handleFeedback?.('LIKE');
                              }
                            }}
                            aria-label={
                              feedback === 'LIKE' ? 'Remove like' : 'Like'
                            }
                          >
                            <Like
                              className={`${feedback === 'LIKE' ? 'stroke-primary fill-white dark:fill-transparent' : 'stroke-muted-foreground fill-none'}`}
                            ></Like>
                          </button>
                        </div>

                        <div className="relative mr-2 flex items-center justify-center">
                          <button
                            type="button"
                            className="hover:bg-accent flex cursor-pointer items-center justify-center rounded-full bg-transparent p-2"
                            onClick={() => {
                              if (feedback === 'DISLIKE') {
                                handleFeedback?.(null);
                              } else {
                                handleFeedback?.('DISLIKE');
                              }
                            }}
                            aria-label={
                              feedback === 'DISLIKE'
                                ? 'Remove dislike'
                                : 'Dislike'
                            }
                          >
                            <Dislike
                              className={`${feedback === 'DISLIKE' ? 'stroke-destructive fill-white dark:fill-transparent' : 'stroke-muted-foreground fill-none'}`}
                            ></Dislike>
                          </button>
                        </div>
                      </>
                    )}
                  </>
                )}
              </>
            )}
          </div>
        )}
        {sources && (
          <Sidebar
            isOpen={isSidebarOpen}
            toggleState={(state: boolean) => {
              setIsSidebarOpen(state);
            }}
          >
            <AllSources sources={sources} />
          </Sidebar>
        )}
      </div>
    );
  }
  return bubble;
});

type AllSourcesProps = {
  sources: { title: string; text: string; link?: string }[];
};

function AllSources(sources: AllSourcesProps) {
  const { t } = useTranslation();

  const handleCardClick = (link: string) => {
    if (link && link !== 'local') {
      window.open(link, '_blank', 'noopener,noreferrer');
    }
  };

  return (
    <div className="h-full w-full">
      <div className="w-full">
        <p className="text-left text-xl">{`${sources.sources.length} ${t('conversation.sources.title')}`}</p>
        <div className="mx-1 mt-2 h-[0.8px] w-full rounded-full bg-[#C4C4C4]/40 lg:w-[95%]"></div>
      </div>
      <div className="mt-6 flex h-[90%] w-52 flex-col gap-4 overflow-y-auto pr-3 sm:w-64">
        {sources.sources.map((source, index) => {
          const isExternalSource = source.link && source.link !== 'local';
          return (
            <div
              key={index}
              className={`group/card bg-muted hover:bg-accent dark:bg-card dark:hover:bg-muted relative w-full rounded-4xl p-4 transition-colors ${
                isExternalSource ? 'cursor-pointer' : ''
              }`}
              onClick={() =>
                isExternalSource && source.link && handleCardClick(source.link)
              }
            >
              <p
                title={source.title}
                className={`ellipsis-text text-left text-sm font-semibold wrap-break-word ${
                  isExternalSource
                    ? 'group-hover/card:text-primary dark:group-hover/card:text-[#8C67D7]'
                    : ''
                }`}
              >
                {`${index + 1}. ${source.title}`}
                {isExternalSource && (
                  <img
                    src={Link}
                    alt="External Link"
                    className={`ml-1 inline h-3 w-3 object-fill dark:invert ${
                      isExternalSource
                        ? 'group-hover/card:contrast-50 group-hover/card:hue-rotate-235 group-hover/card:invert-31 group-hover/card:saturate-752 group-hover/card:sepia-80 group-hover/card:filter'
                        : ''
                    }`}
                  />
                )}
              </p>
              <p className="dark:text-foreground mt-3 line-clamp-4 rounded-md text-left text-xs wrap-break-word text-black">
                {source.text}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
export default ConversationBubble;

function ToolCallApprovalBar({
  toolCall,
  onToolAction,
}: {
  toolCall: ToolCallsType;
  onToolAction?: (
    callId: string,
    decision: 'approved' | 'denied',
    comment?: string,
  ) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [comment, setComment] = useState('');
  const actionLabel = toolCall.action_name.substring(
    0,
    toolCall.action_name.lastIndexOf('_'),
  );
  const argPreview = JSON.stringify(toolCall.arguments);
  const truncated =
    argPreview.length > 60 ? argPreview.slice(0, 57) + '...' : argPreview;

  return (
    <div className="border-border bg-muted dark:bg-card mb-2 w-full overflow-hidden rounded-2xl border">
      <div className="flex items-center gap-3 px-4 py-2.5">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <span className="text-sm font-semibold whitespace-nowrap">
            {toolCall.tool_name}
          </span>
          <span className="text-muted-foreground text-xs">{actionLabel}</span>
          <span
            className="text-muted-foreground hidden min-w-0 truncate font-mono text-xs md:block"
            title={argPreview}
          >
            {truncated}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            className={`rounded-full px-4 py-1 text-xs font-medium transition-colors ${
              comment
                ? 'bg-muted text-muted-foreground cursor-default opacity-50'
                : 'bg-primary hover:bg-primary/90 text-white'
            }`}
            onClick={() => {
              if (!comment) onToolAction?.(toolCall.call_id, 'approved');
            }}
          >
            Approve
          </button>
          <button
            className={`rounded-full border px-4 py-1 text-xs font-medium transition-colors ${
              comment
                ? 'border-destructive bg-destructive/10 text-destructive font-semibold'
                : 'hover:bg-accent text-muted-foreground'
            }`}
            onClick={() => {
              if (expanded && comment) {
                onToolAction?.(toolCall.call_id, 'denied', comment);
              } else if (expanded) {
                onToolAction?.(toolCall.call_id, 'denied');
              } else {
                setExpanded(true);
              }
            }}
          >
            Deny
          </button>
          <button
            className="text-muted-foreground hover:text-foreground flex h-6 w-6 items-center justify-center rounded-full transition-colors"
            onClick={() => setExpanded(!expanded)}
            title="Details"
          >
            <img
              src={ChevronDown}
              alt="expand"
              className={`h-3.5 w-3.5 transition-transform duration-200 dark:invert ${expanded ? 'rotate-180' : ''}`}
            />
          </button>
        </div>
      </div>
      {expanded && (
        <div className="border-border border-t px-4 py-3">
          <p className="text-muted-foreground mb-1 text-xs font-medium">
            Arguments
          </p>
          <pre className="bg-background dark:bg-background/50 mb-2 max-h-40 overflow-auto rounded-lg p-2 font-mono text-xs">
            {JSON.stringify(toolCall.arguments, null, 2)}
          </pre>
          <input
            type="text"
            placeholder="Optional reason for denying..."
            className="border-border bg-background w-full rounded-lg border px-3 py-1.5 text-sm"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && comment) {
                onToolAction?.(toolCall.call_id, 'denied', comment);
              }
            }}
          />
        </div>
      )}
    </div>
  );
}

function ToolCalls({
  toolCalls,
  onToolAction,
}: {
  toolCalls: ToolCallsType[];
  onToolAction?: (
    callId: string,
    decision: 'approved' | 'denied',
    comment?: string,
  ) => void;
}) {
  const [isToolCallsOpen, setIsToolCallsOpen] = useState(false);

  const awaitingCalls = toolCalls.filter(
    (tc) => tc.status === 'awaiting_approval',
  );
  const resolvedCalls = toolCalls.filter(
    (tc) => tc.status !== 'awaiting_approval',
  );

  return (
    <div className="mb-4 flex w-full flex-col flex-wrap items-start self-start lg:flex-nowrap">
      {/* Approval bars — always visible, compact inline */}
      {awaitingCalls.length > 0 && (
        <div className="fade-in mt-4 ml-3 w-[90vw] md:w-[70vw] lg:w-full">
          {awaitingCalls.map((tc) => (
            <ToolCallApprovalBar
              key={`approval-${tc.call_id}`}
              toolCall={tc}
              onToolAction={onToolAction}
            />
          ))}
        </div>
      )}

      {/* Regular tool calls accordion */}
      {resolvedCalls.length > 0 && (
        <>
          <div className="my-2 flex flex-row items-center justify-center gap-3">
            <Avatar
              className="h-[26px] w-[30px] text-xl"
              avatar={
                <img
                  src={Sources}
                  alt={'ToolCalls'}
                  className="h-full w-full object-fill"
                />
              }
            />
            <button
              className="flex flex-row items-center gap-2"
              onClick={() => setIsToolCallsOpen(!isToolCallsOpen)}
            >
              <p className="text-base font-semibold">Tool Calls</p>
              <img
                src={ChevronDown}
                alt="ChevronDown"
                className={`h-4 w-4 transform transition-transform duration-200 dark:invert ${isToolCallsOpen ? 'rotate-180' : ''}`}
              />
            </button>
          </div>
          {isToolCallsOpen && (
            <div className="fade-in mr-5 ml-3 w-[90vw] md:w-[70vw] lg:w-full">
              <div className="grid grid-cols-1 gap-2">
                {resolvedCalls.map((toolCall, index) => (
                  <Accordion
                    key={`tool-call-${index}`}
                    title={`${toolCall.tool_name}  -  ${toolCall.action_name.substring(0, toolCall.action_name.lastIndexOf('_'))}`}
                    className="bg-muted dark:bg-answer-bubble w-full rounded-4xl"
                    titleClassName="px-6 py-2 text-sm font-semibold"
                  >
                    <div className="flex flex-col gap-1">
                      <div className="border-border flex flex-col rounded-2xl border">
                        <p className="dark:bg-background flex flex-row items-center justify-between rounded-t-2xl bg-black/10 px-2 py-1 text-sm font-semibold wrap-break-word">
                          <span style={{ fontFamily: 'IBMPlexMono-Medium' }}>
                            Arguments
                          </span>{' '}
                          <CopyButton
                            textToCopy={JSON.stringify(
                              toolCall.arguments,
                              null,
                              2,
                            )}
                          />
                        </p>
                        <p className="dark:bg-card rounded-b-2xl p-2 font-mono text-sm wrap-break-word">
                          <span
                            className="dark:text-muted-foreground leading-[23px] text-black"
                            style={{ fontFamily: 'IBMPlexMono-Medium' }}
                          >
                            {JSON.stringify(toolCall.arguments, null, 2)}
                          </span>
                        </p>
                      </div>
                      <div className="border-border flex flex-col rounded-2xl border">
                        <p className="dark:bg-background flex flex-row items-center justify-between rounded-t-2xl bg-black/10 px-2 py-1 text-sm font-semibold wrap-break-word">
                          <span style={{ fontFamily: 'IBMPlexMono-Medium' }}>
                            Response
                          </span>{' '}
                          <CopyButton
                            textToCopy={
                              toolCall.status === 'error'
                                ? toolCall.error || 'Unknown error'
                                : JSON.stringify(toolCall.result, null, 2)
                            }
                          />
                        </p>
                        {toolCall.status === 'pending' && (
                          <span className="dark:bg-card flex w-full items-center justify-center rounded-b-2xl p-2">
                            <Spinner size="small" />
                          </span>
                        )}
                        {toolCall.status === 'completed' && (
                          <p className="dark:bg-card rounded-b-2xl p-2 font-mono text-sm wrap-break-word">
                            <span
                              className="dark:text-muted-foreground leading-[23px] text-black"
                              style={{ fontFamily: 'IBMPlexMono-Medium' }}
                            >
                              {JSON.stringify(toolCall.result, null, 2)}
                            </span>
                          </p>
                        )}
                        {toolCall.status === 'error' && (
                          <p className="dark:bg-card rounded-b-2xl p-2 font-mono text-sm wrap-break-word">
                            <span
                              className="text-destructive leading-[23px]"
                              style={{ fontFamily: 'IBMPlexMono-Medium' }}
                            >
                              {toolCall.error}
                            </span>
                          </p>
                        )}
                        {toolCall.status === 'denied' && (
                          <p className="dark:bg-card rounded-b-2xl p-2 font-mono text-sm wrap-break-word">
                            <span
                              className="text-muted-foreground leading-[23px]"
                              style={{ fontFamily: 'IBMPlexMono-Medium' }}
                            >
                              Denied by user
                            </span>
                          </p>
                        )}
                      </div>
                    </div>
                  </Accordion>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Thought({
  thought,
  preprocessLaTeX,
}: {
  thought: string;
  preprocessLaTeX: (content: string) => string;
}) {
  const { t } = useTranslation();
  const [isDarkTheme] = useDarkTheme();
  const [isThoughtOpen, setIsThoughtOpen] = useState(false);

  return (
    <div className="mb-4 flex w-full flex-col flex-wrap items-start self-start lg:flex-nowrap">
      <div className="my-2 flex flex-row items-center justify-center gap-3">
        <Avatar
          className="h-[26px] w-[30px] text-xl"
          avatar={
            <img
              src={Cloud}
              alt={'Thought'}
              className="h-full w-full object-fill"
            />
          }
        />
        <button
          className="flex flex-row items-center gap-2"
          onClick={() => setIsThoughtOpen(!isThoughtOpen)}
        >
          <p className="text-base font-semibold">
            {t('conversation.reasoning')}
          </p>
          <img
            src={ChevronDown}
            alt="ChevronDown"
            className={`h-4 w-4 transform transition-transform duration-200 dark:invert ${isThoughtOpen ? 'rotate-180' : ''}`}
          />
        </button>
      </div>
      {isThoughtOpen && (
        <div className="fade-in mr-5 ml-2 max-w-[90vw] md:max-w-[70vw] lg:max-w-[50vw]">
          <div className="bg-muted dark:bg-answer-bubble rounded-[28px] px-7 py-[18px]">
            <ReactMarkdown
              className="fade-in leading-normal wrap-break-word whitespace-pre-wrap"
              remarkPlugins={[remarkGfm, remarkMath]}
              rehypePlugins={[rehypeKatex]}
              components={{
                code(props) {
                  const { children, className, node, ref, ...rest } = props;
                  const match = /language-(\w+)/.exec(className || '');
                  const language = match ? match[1] : '';

                  return match ? (
                    <div className="group border-border relative overflow-hidden rounded-[14px] border">
                      <div className="bg-platinum dark:bg-muted flex items-center justify-between px-2 py-1">
                        <span className="text-foreground dark:text-foreground text-xs font-medium">
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
                        className="mt-0!"
                        customStyle={{
                          margin: 0,
                          borderRadius: 0,
                        }}
                      >
                        {String(children).replace(/\n$/, '')}
                      </SyntaxHighlighter>
                    </div>
                  ) : (
                    <code className="dark:bg-accent dark:text-foreground rounded-[6px] bg-gray-200 px-2 py-1 text-xs font-normal whitespace-pre-line">
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
                table({ children }) {
                  return (
                    <div className="border-border relative overflow-x-auto rounded-lg border">
                      <table className="dark:text-foreground w-full text-left text-gray-700">
                        {children}
                      </table>
                    </div>
                  );
                },
                thead({ children }) {
                  return (
                    <thead className="bg-muted text-foreground text-xs uppercase">
                      {children}
                    </thead>
                  );
                },
                tr({ children }) {
                  return (
                    <tr className="border-border odd:bg-card even:bg-muted border-b">
                      {children}
                    </tr>
                  );
                },
                th({ children }) {
                  return <th className="px-6 py-3">{children}</th>;
                },
                td({ children }) {
                  return <td className="px-6 py-3">{children}</td>;
                },
              }}
            >
              {preprocessLaTeX(thought ?? '')}
            </ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  );
}
