import { envVar } from '@/env';
import { cn } from '@/lib/utils';
import 'katex/dist/katex.min.css';

import {
  ChevronDown as ChevronDownIcon,
  Database,
  Download,
  Eye,
  FileText,
  Pencil,
  ThumbsDown,
  ThumbsUp,
  ExternalLink,
} from 'lucide-react';
import { forwardRef, Fragment, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import WorkflowRunArtifacts from '../agents/workflow/WorkflowRunArtifacts';
import DocumentationDark from '../assets/documentation-dark.svg';
import CopyButton from '../components/CopyButton';

import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Sheet, SheetContent } from '../components/ui/sheet';
import { Textarea } from '../components/ui/textarea';
import SpeakButton from '../components/TextToSpeechButton';
import { useOutsideAlerter } from '../hooks';
import {
  selectChunks,
  selectSelectedDocs,
  selectToken,
  selectTtsAvailable,
} from '../preferences/preferenceSlice';
import { isToolCallRunning } from '../utils/streamingStatusUtils';
import AnswerFlow from './AnswerFlow';
import { AnswerSegment } from './answerSegments';
import { deriveArtifactChips } from './artifactChips';
import { FEEDBACK, MESSAGE_TYPE, ResearchState } from './conversationModels';
import MarkdownAnswer from './MarkdownAnswer';
import ResearchProgress from './ResearchProgress';
import { ToolCallsType } from './types';
import { wikiWriteActionKey, wikiWritePath } from './wikiToolCall';

const DisableSourceFE = envVar('VITE_DISABLE_SOURCE_FE') === 'true';

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
    /** Arrival order of the answer's parts; drives inline rendering. */
    segments?: AnswerSegment[];
    /** Set when this answer came from a workflow agent run; renders the
     * run's produced artifacts as click-through chips/previews. */
    workflowRunId?: string;
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
    /**
     * Every artifact in the conversation, for resolving inline links. Refs
     * are conversation-scoped, so a link may point at an earlier turn's file.
     * The chip RAIL still uses this turn's artifacts only.
     */
    conversationArtifacts?: ReturnType<typeof deriveArtifactChips>;
    onOpenArtifact?: (artifact: { id: string; toolName: string }) => void;
    onToolAction?: (
      callId: string,
      decision: 'approved' | 'denied',
      comment?: string,
    ) => void;
    /** Active agent id; refreshes the Schedules tab from SchedulerToolCallCard. */
    agentId?: string;
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
    segments,
    workflowRunId,
    research,
    retryBtn,
    questionNumber,
    isStreaming,
    handleUpdatedQuestionSubmission,
    filesAttached,
    conversationArtifacts,
    onOpenArtifact,
    onToolAction,
    agentId,
  },
  ref,
) {
  const { t } = useTranslation();
  // const bubbleRef = useRef<HTMLDivElement | null>(null);
  const chunks = useSelector(selectChunks);
  const selectedDocs = useSelector(selectSelectedDocs);
  const ttsAvailable = useSelector(selectTtsAvailable);
  const [isEditClicked, setIsEditClicked] = useState(false);
  const [editInputBox, setEditInputBox] = useState<string>('');
  const messageRef = useRef<HTMLDivElement>(null);
  const [shouldShowToggle, setShouldShowToggle] = useState(false);

  const [activeTooltip, setActiveTooltip] = useState<number | null>(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(false);
  const editableQueryRef = useRef<HTMLDivElement>(null);
  const [isQuestionCollapsed, setIsQuestionCollapsed] = useState(true);

  const completedArtifacts = deriveArtifactChips(toolCalls);

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
            <div className="mr-5 mb-4 flex flex-wrap justify-end gap-2">
              {filesAttached.map((file, index) => (
                <div
                  key={index}
                  title={file.fileName}
                  className="dark:text-foreground dark:bg-accent text-muted-foreground bg-muted flex items-center rounded-xl p-2 text-sm"
                >
                  <div className="bg-primary mr-2 items-center justify-center rounded-lg p-1.5">
                    <img
                      src={DocumentationDark}
                      alt="Attachment"
                      className="h-3.75 w-3.75 object-fill"
                    />
                  </div>
                  <span className="max-w-37.5 truncate font-normal">
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
            {!isEditClicked && (
              <>
                {/* ``mr-3`` plus the pill's own ``mr-2`` puts the question's
                    right edge on the answer's ``mr-5`` gutter. */}
                <div className="relative mr-3 flex w-full min-w-0 flex-col">
                  <div className="bg-secondary text-foreground mr-2 ml-2 flex max-w-full min-w-0 items-start gap-2 rounded-3xl px-5 py-4 text-sm leading-normal wrap-anywhere whitespace-pre-wrap sm:text-base">
                    <div
                      ref={messageRef}
                      className={`${isQuestionCollapsed ? 'line-clamp-4' : ''} w-full min-w-0`}
                    >
                      {message}
                    </div>
                    {shouldShowToggle && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-lg"
                        shape="pill"
                        onClick={(e) => {
                          e.stopPropagation();
                          setIsQuestionCollapsed(!isQuestionCollapsed);
                        }}
                        aria-label="Toggle"
                        className="ml-1"
                      >
                        <ChevronDownIcon
                          aria-hidden
                          className={cn(
                            'size-6 transition-transform duration-200',
                            !isQuestionCollapsed && 'rotate-180',
                          )}
                        />
                      </Button>
                    )}
                  </div>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  shape="pill"
                  onClick={() => {
                    setIsEditClicked(true);
                    setEditInputBox(message ?? '');
                  }}
                  className="invisible mt-3 shrink-0 cursor-pointer group-hover:visible"
                  aria-label="Edit"
                >
                  <Pencil />
                </Button>
              </>
            )}
          </div>
          {isEditClicked && (
            <div
              ref={editableQueryRef}
              className="mx-auto flex w-full flex-col gap-4 rounded-lg bg-transparent p-4"
            >
              <Textarea
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
                size="lg"
                resize="none"
              />
              <div className="flex items-center justify-end gap-2">
                <Button
                  type="button"
                  variant="ghost"
                  shape="pill"
                  onClick={() => setIsEditClicked(false)}
                >
                  {t('conversation.edit.cancel')}
                </Button>
                <Button
                  type="button"
                  shape="pill"
                  onClick={handleEditClick}
                  disabled={
                    !editInputBox.trim() ||
                    editInputBox.trim() === (message ?? '').trim()
                  }
                >
                  {t('conversation.edit.update')}
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  } else {
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
              // Stretched, not shrink-to-fit: the grid below sizes off this box,
              // so a fit-content parent would leave its width to the cards.
              <div className="mb-4 flex w-full flex-col flex-wrap items-start self-stretch lg:flex-nowrap">
                <div className="my-2 ml-6 flex flex-row items-center justify-center gap-3">
                  <Database className="size-6" />
                  <p className="text-base font-semibold">
                    {t('conversation.sources.title')}
                  </p>
                </div>
                {/* Width comes from the stretched parent minus these margins;
                    w-full here would be the column width plus them. */}
                <div className="fade-in mr-5 ml-6">
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
                                ? 'hover:text-primary hover:underline'
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
                            <FileText className="text-muted-foreground size-4 shrink-0" />
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
                            className="bg-popover text-popover-foreground absolute left-1/2 z-50 max-h-48 w-40 translate-x-[-50%] translate-y-0.75 rounded-xl p-4 shadow-md sm:w-56"
                            onMouseOver={() => setActiveTooltip(index)}
                            onMouseOut={() => setActiveTooltip(null)}
                          >
                            <p className="line-clamp-6 max-h-41 overflow-hidden rounded-md text-sm wrap-break-word text-ellipsis">
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
        {!message && onOpenArtifact && completedArtifacts.length > 0 && (
          <div className="my-2 ml-6 flex flex-wrap justify-start gap-2">
            {completedArtifacts.map((artifact, artifactIndex) => (
              <Button
                key={artifact.id ?? `${artifact.callId}-${artifactIndex}`}
                type="button"
                onClick={() =>
                  onOpenArtifact({
                    id: artifact.id,
                    toolName: artifact.toolName,
                  })
                }
                variant="secondary"
                shape="pill"
              >
                <Eye />
                <span className="max-w-50 truncate" title={artifact.label}>
                  {artifact.label}
                </span>
              </Button>
            ))}
          </div>
        )}
        {workflowRunId && (
          <div className="my-2 mr-5 ml-6">
            <WorkflowRunArtifacts
              workflowRunId={workflowRunId}
              inProgress={isStreaming}
            />
          </div>
        )}
        {type === 'ERROR' ? (
          message && (
            <div className="flex max-w-full flex-col flex-wrap items-start self-start lg:flex-nowrap">
              <div className="fade-in-bubble text-destructive/80 dark:border-destructive bg-destructive/10 relative mr-5 flex max-w-full flex-row items-center rounded-full border border-transparent p-2 px-6 py-5 text-sm font-normal dark:text-white">
                <MarkdownAnswer content={message} isStreaming={isStreaming} />
              </div>
            </div>
          )
        ) : (
          <AnswerFlow
            message={message}
            thought={thought}
            toolCalls={toolCalls}
            segments={segments}
            isStreaming={isStreaming}
            agentId={agentId}
            // A research run already narrates itself above; the status line
            // would be a second live indicator away from the point of action.
            suppressStatusLine={Boolean(research)}
            artifacts={conversationArtifacts ?? completedArtifacts}
            // The chip rail below renders from this turn's artifacts alone, so
            // a bare-filename link has to resolve against the same set or the
            // two controls in one bubble open different files.
            turnArtifacts={completedArtifacts}
            onOpenArtifact={onOpenArtifact}
            renderApproval={(toolCall: ToolCallsType) => (
              <div className="fade-in mt-4 mr-5 ml-6">
                <ToolCallApprovalBar
                  toolCall={toolCall}
                  onToolAction={onToolAction}
                />
              </div>
            )}
            renderWikiWrite={(toolCall: ToolCallsType, isLive: boolean) => (
              <WikiWriteToolCallCard toolCall={toolCall} isLive={isLive} />
            )}
          />
        )}
        {message && (
          // ml-4 plus each button's own p-2 puts the first glyph on the answer's
          // ml-6 text column.
          <div className="my-2 ml-4 flex flex-wrap justify-start gap-2">
            {type === 'ERROR' ? (
              <div className="relative block items-center justify-center">
                <div>{retryBtn}</div>
              </div>
            ) : (
              <>
                {onOpenArtifact &&
                  completedArtifacts.map((artifact, artifactIndex) => (
                    <div
                      key={artifact.id ?? `${artifact.callId}-${artifactIndex}`}
                      className="relative flex items-center justify-center"
                    >
                      <Button
                        type="button"
                        onClick={() =>
                          onOpenArtifact({
                            id: artifact.id,
                            toolName: artifact.toolName,
                          })
                        }
                        variant="secondary"
                        shape="pill"
                        aria-label="View artifact"
                      >
                        <Eye />
                        <span
                          className="max-w-50 truncate"
                          title={artifact.label}
                        >
                          {artifact.label}
                        </span>
                      </Button>
                    </div>
                  ))}
                {!isStreaming && (
                  <>
                    <div className="relative block items-center justify-center">
                      <CopyButton textToCopy={message} />
                    </div>
                    {research && message && (
                      <div className="relative block items-center justify-center">
                        <Button
                          type="button"
                          variant="ghost-muted"
                          size="icon-sm"
                          shape="pill"
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
                          className="cursor-pointer"
                          aria-label="Export as Markdown"
                          title="Export as Markdown"
                        >
                          <Download />
                        </Button>
                      </div>
                    )}
                    {ttsAvailable && (
                      <div className="relative block items-center justify-center">
                        <SpeakButton text={message} />
                      </div>
                    )}
                    {handleFeedback && (
                      <>
                        <div className="relative flex items-center justify-center">
                          <Button
                            type="button"
                            variant="ghost-muted"
                            size="icon-sm"
                            shape="pill"
                            className="cursor-pointer"
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
                            <ThumbsUp
                              className={cn(
                                feedback === 'LIKE' &&
                                  'text-primary fill-white dark:fill-transparent',
                              )}
                            />
                          </Button>
                        </div>

                        <div className="relative flex items-center justify-center">
                          <Button
                            type="button"
                            variant="ghost-muted"
                            size="icon-sm"
                            shape="pill"
                            className="cursor-pointer"
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
                            <ThumbsDown
                              className={cn(
                                feedback === 'DISLIKE' &&
                                  'text-destructive fill-white dark:fill-transparent',
                              )}
                            />
                          </Button>
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
          <Sheet open={isSidebarOpen} onOpenChange={setIsSidebarOpen}>
            <SheetContent
              side="right"
              title="Sources"
              className="w-64 sm:w-80 sm:max-w-none"
            >
              <div className="flex h-full flex-col items-center gap-2 px-6 py-4 text-center">
                <AllSources sources={sources} />
              </div>
            </SheetContent>
          </Sheet>
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
        <div className="bg-border mx-1 mt-2 h-[0.8px] w-full rounded-full lg:w-[95%]"></div>
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
                  isExternalSource ? 'group-hover/card:text-primary' : ''
                }`}
              >
                {`${index + 1}. ${source.title}`}
                {isExternalSource && (
                  <ExternalLink className="text-muted-foreground group-hover/card:text-primary ml-1 inline size-3" />
                )}
              </p>
              <p className="text-foreground mt-3 line-clamp-4 rounded-md text-left text-xs wrap-break-word">
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
  const token = useSelector(selectToken);
  const actionLabel = toolCall.action_name.substring(
    0,
    toolCall.action_name.lastIndexOf('_'),
  );
  const argPreview = JSON.stringify(toolCall.arguments);
  const truncated =
    argPreview.length > 60 ? argPreview.slice(0, 57) + '...' : argPreview;

  const isRemoteDevice =
    toolCall.tool_name === 'remote_device' && toolCall.device_id;
  const handleApproveSticky = async () => {
    if (!isRemoteDevice || !toolCall.device_id) return;
    const command =
      (toolCall.arguments && (toolCall.arguments.command as string)) || '';
    if (command) {
      try {
        const { default: devicesService } =
          await import('../api/services/devicesService');
        await devicesService.addAutoApprovePattern(
          toolCall.device_id,
          command,
          token,
        );
      } catch (err) {
        console.error('auto-approve register failed', err);
      }
    }
    onToolAction?.(toolCall.call_id, 'approved');
  };

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
          <Button
            type="button"
            size="xs"
            shape="pill"
            disabled={Boolean(comment)}
            onClick={() => {
              if (!comment) onToolAction?.(toolCall.call_id, 'approved');
            }}
          >
            Approve
          </Button>
          {isRemoteDevice && (
            <Button
              type="button"
              variant="outline"
              size="xs"
              shape="pill"
              onClick={() => {
                void handleApproveSticky();
              }}
              title="Approve and don't ask again for this command shape"
            >
              Approve, don&apos;t ask again
            </Button>
          )}
          <Button
            type="button"
            variant={comment ? 'destructive-outline' : 'outline'}
            size="xs"
            shape="pill"
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
          </Button>
          <Button
            type="button"
            variant="ghost-muted"
            size="icon-xs"
            shape="pill"
            onClick={() => setExpanded(!expanded)}
            title="Details"
            aria-label="expand"
          >
            <ChevronDownIcon
              className={cn(
                'transition-transform duration-200',
                expanded && 'rotate-180',
              )}
            />
          </Button>
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
          <Input
            type="text"
            placeholder="Optional reason for denying..."
            size="sm"
            variant="filled"
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

/** The wiki-write step, in the same inline chip language as the other steps. */
export function WikiWriteToolCallCard({
  toolCall,
  isLive,
}: {
  toolCall: ToolCallsType;
  isLive?: boolean;
}) {
  const { t } = useTranslation();
  const path = wikiWritePath(toolCall);
  const actionKey = wikiWriteActionKey(toolCall.action_name);
  const isError = toolCall.status === 'error';
  const namespace = isToolCallRunning(toolCall)
    ? 'wikiWrite.active'
    : 'wikiWrite';
  const label = t(`conversation.${namespace}.${actionKey}`, {
    defaultValue: t(`conversation.${namespace}.edited`),
  });

  return (
    <div className="my-2 mr-5 ml-6 flex min-w-0 items-center gap-2 py-1.5 text-sm">
      <Pencil
        aria-hidden
        className={`text-muted-foreground h-4 w-4 shrink-0 ${
          isLive ? 'animate-pulse' : ''
        }`}
      />
      <span
        className={`shrink-0 ${isLive ? 'shimmer-text' : 'text-muted-foreground'}`}
      >
        {label}
      </span>
      {path && (
        <code
          className="text-muted-foreground bg-muted dark:bg-answer-bubble min-w-0 truncate rounded-md px-1.5 py-0.5 font-mono text-xs"
          title={path}
        >
          {path}
        </code>
      )}
      {isError && (
        <span className="text-destructive shrink-0 text-xs">
          {t('conversation.wikiWrite.failed')}
        </span>
      )}
    </div>
  );
}
