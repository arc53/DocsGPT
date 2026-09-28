import {
  Bot,
  ChevronDown,
  Circle,
  CircleAlert,
  CircleCheck,
  CircleX,
  CodeXml,
  Database,
  FileBox,
  Flag,
  GitBranch,
  type LucideIcon,
  Play,
  StickyNote,
  Workflow,
} from 'lucide-react';
import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { SectionHeader } from '@/components/ui/section-header';
import { Spinner } from '@/components/ui/spinner';
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from '@/components/ui/message-scroller';
import { cn } from '@/lib/utils';

import MessageInput from '../../components/MessageInput';
import ConversationBubble from '../../conversation/ConversationBubble';
import { Query } from '../../conversation/conversationModels';
import { AppDispatch } from '../../store';
import { selectCompletedAttachments } from '../../upload/uploadSlice';
import { WorkflowEdge, WorkflowNode } from '../types/workflow';
import WorkflowRunArtifacts from './WorkflowRunArtifacts';
import {
  addQuery,
  fetchWorkflowPreviewAnswer,
  handleWorkflowPreviewAbort,
  previewSendBlockReason,
  resendQuery,
  resetWorkflowPreview,
  selectActiveNodeId,
  selectWorkflowExecutionSteps,
  selectWorkflowPreviewQueries,
  selectWorkflowPreviewStatus,
  WorkflowExecutionStep,
  WorkflowQuery,
} from './workflowPreviewSlice';

interface WorkflowData {
  name: string;
  description?: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}

interface WorkflowPreviewProps {
  workflowData: WorkflowData;
  // Saved workflow id (when the draft has been persisted); enables run-artifact
  // listing by persisting a ``workflow_runs`` row for the preview run.
  workflowId?: string | null;
}

// Components, not elements: the step list draws them at 12px, the minimap
// rows at 14px.
const NODE_ICONS: Record<string, LucideIcon> = {
  start: Play,
  agent: Bot,
  end: Flag,
  note: StickyNote,
  state: Database,
  condition: GitBranch,
  code: CodeXml,
};

const NODE_COLORS: Record<string, string> = {
  start: 'text-success',
  agent: 'text-primary',
  end: 'text-destructive',
  note: 'text-warning',
  state: 'text-info',
  condition: 'text-warning',
  code: 'text-info',
};

/**
 * A step row under an answer, like Reasoning in chat (AnswerFlow): a ghost
 * button whose muted icon sits on the answer's ml-6 column, then the panel it
 * opens in place on that column.
 */
function StepDisclosure({
  icon: Icon,
  label,
  count,
  isOpen,
  onToggle,
  children,
}: {
  icon: LucideIcon;
  label: string;
  count?: string;
  isOpen: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="my-2 flex w-full flex-col">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={onToggle}
        aria-expanded={isOpen}
        // ml-3.5 plus size sm's own has-[>svg]:px-2.5 puts the icon on the
        // answer's ml-6 text column.
        className="ml-3.5 w-fit max-w-full justify-start"
      >
        <Icon className="text-muted-foreground" aria-hidden />
        <span className="text-muted-foreground min-w-0 truncate">{label}</span>
        {count && (
          <span className="text-muted-foreground/70 font-normal">{count}</span>
        )}
        <ChevronDown
          aria-hidden
          className={cn(
            'text-muted-foreground shrink-0 transition-transform duration-200',
            isOpen && 'rotate-180',
          )}
        />
      </Button>
      <div
        className={cn(
          'mr-5 ml-6 grid transition-[grid-template-rows,opacity] duration-300 ease-out',
          isOpen ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0',
        )}
      >
        <div className="min-h-0 overflow-hidden">{children}</div>
      </div>
    </div>
  );
}

export function ExecutionDetails({
  steps,
  nodes,
  isOpen,
  onToggle,
  stepRefs,
}: {
  steps: WorkflowExecutionStep[];
  nodes: WorkflowNode[];
  isOpen: boolean;
  onToggle: () => void;
  stepRefs?: React.RefObject<Map<string, HTMLDivElement>>;
}) {
  const { t } = useTranslation();
  const completedSteps = steps.filter(
    (s) => s.status === 'completed' || s.status === 'failed',
  );

  if (completedSteps.length === 0) return null;

  const formatValue = (value: unknown): string => {
    if (typeof value === 'string') return value;
    if (value === undefined) return '';
    const formatted = JSON.stringify(value, null, 2);
    return formatted ?? String(value);
  };

  return (
    <StepDisclosure
      icon={Workflow}
      label={t('agents.workflow.preview.executionDetails')}
      count={t('agents.workflow.preview.stepCount', {
        count: completedSteps.length,
      })}
      isOpen={isOpen}
      onToggle={onToggle}
    >
      <div className="flex flex-col gap-2 pt-1">
        {completedSteps.map((step, stepIndex) => {
          const node = nodes.find((n) => n.id === step.nodeId);
          const displayName =
            node?.title || node?.data?.title || step.nodeTitle;
          const StepIcon = NODE_ICONS[step.nodeType] || Circle;
          const stateVars = step.stateDelta
            ? Object.entries(step.stateDelta).filter(
                ([key]) => !['query', 'chat_history'].includes(key),
              )
            : [];

          const truncateText = (text: string, maxLength: number) => {
            if (text.length <= maxLength) return text;
            return text.slice(0, maxLength) + '...';
          };
          const hasOutput =
            step.output !== undefined &&
            step.output !== null &&
            formatValue(step.output) !== '';
          const formattedOutput = hasOutput ? formatValue(step.output) : '';

          // A step is a place you read inside: a subtle panel on the
          // drawer's background, with its output in a filled well.
          return (
            <Card
              key={step.nodeId}
              ref={(el: HTMLDivElement | null) => {
                if (el && stepRefs) stepRefs.current.set(step.nodeId, el);
              }}
              variant="subtle"
              padding="sm"
            >
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground flex size-5 shrink-0 items-center justify-center text-xs font-medium">
                  {stepIndex + 1}.
                </span>
                <StepIcon
                  aria-hidden
                  className={cn(
                    'size-3 shrink-0',
                    NODE_COLORS[step.nodeType] || NODE_COLORS.state,
                  )}
                />
                <span className="text-foreground min-w-0 truncate font-medium">
                  {displayName}
                </span>
                <div className="ml-auto shrink-0">
                  {step.status === 'completed' && (
                    <CircleCheck className="text-success size-4" />
                  )}
                  {step.status === 'failed' && (
                    <CircleX className="text-destructive size-4" />
                  )}
                </div>
              </div>
              {hasOutput && (
                <Card variant="filled" padding="sm">
                  <p className="wrap-break-word whitespace-pre-wrap">
                    <span className="text-muted-foreground font-medium">
                      {t('agents.workflow.preview.outputLabel')}{' '}
                    </span>
                    <span className="text-foreground">
                      {truncateText(formattedOutput, 300)}
                    </span>
                  </p>
                </Card>
              )}
              {step.error && (
                <Alert variant="destructive" role="status">
                  <CircleAlert />
                  <AlertDescription>
                    <span className="font-medium">
                      {t('agents.workflow.preview.errorLabel')}{' '}
                    </span>
                    <span className="wrap-break-word whitespace-pre-wrap">
                      {step.error}
                    </span>
                  </AlertDescription>
                </Alert>
              )}
              {stateVars.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {stateVars.map(([key, value]) => (
                    // eslint-disable-next-line shadcn/no-restyle -- state keys and values are serialised by the app, so the chip is set in mono
                    <Badge key={key} variant="neutral" className="font-mono">
                      <span className="max-w-[100px] truncate">{key}:</span>
                      <span
                        className="text-foreground max-w-[200px] truncate"
                        title={formatValue(value)}
                      >
                        {truncateText(formatValue(value), 50)}
                      </span>
                    </Badge>
                  ))}
                </div>
              )}
            </Card>
          );
        })}
      </div>
    </StepDisclosure>
  );
}

export function RunArtifactsSection({
  workflowRunId,
  isOpen,
  onToggle,
  runInProgress = false,
}: {
  workflowRunId: string;
  isOpen: boolean;
  onToggle: () => void;
  runInProgress?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <StepDisclosure
      icon={FileBox}
      label={t('agents.workflow.preview.artifacts')}
      isOpen={isOpen}
      onToggle={onToggle}
    >
      <div className="max-h-[480px] overflow-y-auto pt-1">
        {isOpen && (
          <WorkflowRunArtifacts
            workflowRunId={workflowRunId}
            inProgress={runInProgress}
          />
        )}
      </div>
    </StepDisclosure>
  );
}

export function WorkflowMiniMap({
  nodes,
  activeNodeId,
  executionSteps,
  onNodeClick,
}: {
  nodes: WorkflowNode[];
  activeNodeId: string | null;
  executionSteps: WorkflowExecutionStep[];
  onNodeClick?: (nodeId: string) => void;
}) {
  const { t } = useTranslation();
  const getNodeDisplayName = (node: WorkflowNode) => {
    if (node.type === 'start') return t('agents.workflow.nodes.start');
    if (node.type === 'end') return t('agents.workflow.nodes.end');
    return node.title || node.data?.title || node.type;
  };

  const getNodeSubtitle = (node: WorkflowNode) => {
    if (node.type === 'agent' && node.data?.model_id) {
      return node.data.model_id;
    }
    return null;
  };

  const getNodeStatus = (nodeId: string) => {
    const step = executionSteps.find((s) => s.nodeId === nodeId);
    return step?.status || 'pending';
  };

  const executedOrder = new Map(executionSteps.map((s, i) => [s.nodeId, i]));
  const startNode = nodes.find((node) => node.type === 'start');
  const visibleNodeIds = new Set(executionSteps.map((step) => step.nodeId));
  if (activeNodeId) {
    visibleNodeIds.add(activeNodeId);
  }
  if (startNode) {
    visibleNodeIds.add(startNode.id);
  }

  const sortedNodes = nodes
    .filter((node) => visibleNodeIds.has(node.id))
    .sort((a, b) => {
      if (a.type === 'start') return -1;
      if (b.type === 'start') return 1;

      const aIdx = executedOrder.get(a.id);
      const bIdx = executedOrder.get(b.id);
      if (aIdx !== undefined && bIdx !== undefined) return aIdx - bIdx;
      if (aIdx !== undefined) return -1;
      if (bIdx !== undefined) return 1;
      return (a.position?.y || 0) - (b.position?.y || 0);
    });

  const hasStepData = (nodeId: string) => {
    const step = executionSteps.find((s) => s.nodeId === nodeId);
    return step && (step.status === 'completed' || step.status === 'failed');
  };

  return (
    <div className="flex flex-col gap-1">
      {sortedNodes.map((node, index) => {
        const status = getNodeStatus(node.id);
        const NodeIcon = NODE_ICONS[node.type] || Circle;
        const isActive = node.id === activeNodeId;
        return (
          <div key={node.id} className="relative">
            {index < sortedNodes.length - 1 && (
              <div className="bg-border absolute top-12 left-4 h-3 w-0.5" />
            )}

            <Button
              type="button"
              variant="outline"
              size="xs"
              onClick={() => hasStepData(node.id) && onNodeClick?.(node.id)}
              disabled={!hasStepData(node.id)}
              /* eslint-disable shadcn/no-restyle --
                 Preview minimap status row: the fill, border and ring follow the step status (success, primary running + pulse,
                 destructive, muted pending), pending and running rows stay unfaded while disabled, and clickable rows dim on hover.
                 No Button variant is status-tinted. See DESIGN.md, Approved exceptions. */
              className={cn(
                'h-12 w-full justify-start disabled:opacity-100',
                isActive
                  ? 'bg-secondary ring-primary hover:bg-secondary dark:bg-secondary dark:hover:bg-secondary ring-2'
                  : status === 'completed'
                    ? 'border-success/50 bg-success/10 hover:bg-success/10 dark:border-success/50 dark:bg-success/10 dark:hover:bg-success/10'
                    : status === 'running'
                      ? 'border-primary/50 bg-secondary hover:bg-secondary dark:border-primary/50 dark:bg-secondary dark:hover:bg-secondary animate-pulse'
                      : status === 'failed'
                        ? 'border-destructive/50 bg-destructive/10 hover:bg-destructive/10 dark:border-destructive/50 dark:bg-destructive/10 dark:hover:bg-destructive/10'
                        : 'border-border bg-muted hover:bg-muted dark:border-border dark:bg-muted dark:hover:bg-muted',
                hasStepData(node.id) && 'hover:opacity-80',
              )}
              /* eslint-enable shadcn/no-restyle */
            >
              <div
                className={cn(
                  'flex size-5 shrink-0 items-center justify-center rounded-full',
                  NODE_COLORS[node.type] || NODE_COLORS.state,
                )}
              >
                <NodeIcon className="size-3.5" />
              </div>
              <div className="min-w-0 flex-1 text-left">
                <div className="text-foreground truncate font-medium">
                  {getNodeDisplayName(node)}
                </div>
                {getNodeSubtitle(node) && (
                  <div className="text-muted-foreground truncate text-xs">
                    {getNodeSubtitle(node)}
                  </div>
                )}
              </div>
              <div className="shrink-0">
                {status === 'running' && (
                  <Spinner size="xs" className="text-primary" />
                )}
                {status === 'completed' && (
                  <CircleCheck className="text-success size-3.5" />
                )}
                {status === 'failed' && (
                  <CircleX className="text-destructive size-3.5" />
                )}
              </div>
            </Button>
          </div>
        );
      })}
    </div>
  );
}

export default function WorkflowPreview({
  workflowData,
  workflowId,
}: WorkflowPreviewProps) {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();

  const queries = useSelector(selectWorkflowPreviewQueries) as WorkflowQuery[];
  const status = useSelector(selectWorkflowPreviewStatus);
  const executionSteps = useSelector(selectWorkflowExecutionSteps);
  const activeNodeId = useSelector(selectActiveNodeId);
  const completedAttachments = useSelector(selectCompletedAttachments);
  const hasCompletedAttachment = completedAttachments.length > 0;

  const [lastQueryReturnedErr, setLastQueryReturnedErr] = useState(false);
  const [sendBlockedMessage, setSendBlockedMessage] = useState<string | null>(
    null,
  );
  const [openDetailsIndex, setOpenDetailsIndex] = useState<number | null>(null);
  const [openArtifactsIndex, setOpenArtifactsIndex] = useState<number | null>(
    null,
  );

  const fetchStream = useRef<{ abort: () => void } | null>(null);
  const stepRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  const scrollToStep = useCallback(
    (nodeId: string) => {
      const lastQueryIndex = queries.length - 1;
      if (lastQueryIndex >= 0) {
        setOpenDetailsIndex(lastQueryIndex);
        setTimeout(() => {
          const stepEl = stepRefs.current.get(nodeId);
          if (stepEl) {
            stepEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }
        }, 100);
      }
    },
    [queries.length],
  );

  const handleFetchAnswer = useCallback(
    ({ question, index }: { question: string; index?: number }) => {
      const promise = dispatch(
        fetchWorkflowPreviewAnswer({
          question,
          workflowData,
          indx: index,
          workflowId,
        }),
      );
      fetchStream.current = promise;
    },
    [dispatch, workflowData, workflowId],
  );

  const handleQuestion = useCallback(
    ({
      question,
      isRetry = false,
      index = undefined,
    }: {
      question: string;
      isRetry?: boolean;
      index?: number;
    }) => {
      // An unsaved draft can't bridge uploaded documents into the run (no
      // persisted workflow_id), so block the send rather than run with the docs
      // silently dropped. The uploads are kept (not cleared) for a retry after
      // the workflow is saved.
      const blockReason = previewSendBlockReason(
        workflowId,
        hasCompletedAttachment,
      );
      if (blockReason) {
        setSendBlockedMessage(blockReason);
        return;
      }
      setSendBlockedMessage(null);

      const trimmedQuestion = question.trim();
      // Doc-driven nodes read ``input_documents`` rather than the query, so an
      // attachment-only run is allowed to proceed with an empty question.
      if (trimmedQuestion === '' && !hasCompletedAttachment) return;

      if (index !== undefined) {
        if (!isRetry) dispatch(resendQuery({ index, prompt: trimmedQuestion }));
        handleFetchAnswer({ question: trimmedQuestion, index });
      } else {
        if (!isRetry) {
          const newQuery: Query = { prompt: trimmedQuestion };
          dispatch(addQuery(newQuery));
        }
        handleFetchAnswer({ question: trimmedQuestion, index: undefined });
      }
    },
    [dispatch, handleFetchAnswer, hasCompletedAttachment, workflowId],
  );

  // Clear the block message once it no longer applies (the workflow was saved,
  // or the attachments were removed) so a stale warning doesn't linger.
  useEffect(() => {
    if (workflowId || !hasCompletedAttachment) setSendBlockedMessage(null);
  }, [workflowId, hasCompletedAttachment]);

  const handleQuestionSubmission = (
    question?: string,
    updated?: boolean,
    indx?: number,
  ) => {
    if (updated === true && question !== undefined && indx !== undefined) {
      handleQuestion({
        question,
        index: indx,
        isRetry: false,
      });
    } else if ((question || hasCompletedAttachment) && status !== 'loading') {
      const currentInput = (question ?? '').trim();
      if (lastQueryReturnedErr && queries.length > 0) {
        const lastQueryIndex = queries.length - 1;
        handleQuestion({
          question: currentInput,
          isRetry: true,
          index: lastQueryIndex,
        });
      } else {
        handleQuestion({
          question: currentInput,
          isRetry: false,
          index: undefined,
        });
      }
    }
  };

  useEffect(() => {
    dispatch(resetWorkflowPreview());
    return () => {
      if (fetchStream.current) fetchStream.current.abort();
      handleWorkflowPreviewAbort();
      dispatch(resetWorkflowPreview());
    };
  }, [dispatch]);

  useEffect(() => {
    if (queries.length > 0) {
      const lastQuery = queries[queries.length - 1];
      setLastQueryReturnedErr(!!lastQuery.error);
    } else setLastQueryReturnedErr(false);
  }, [queries]);

  const lastQuerySteps =
    queries.length > 0 ? queries[queries.length - 1].executionSteps || [] : [];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex min-h-0 flex-1">
        <div className="border-border flex w-64 shrink-0 flex-col border-r">
          <div className="flex items-center justify-between px-4 py-3">
            <SectionHeader
              as="h3"
              size="sm"
              title={t('agents.workflow.preview.minimapHeading')}
            />
          </div>
          <div className="flex-1 overflow-y-auto p-3">
            <WorkflowMiniMap
              nodes={workflowData.nodes}
              activeNodeId={activeNodeId}
              executionSteps={
                lastQuerySteps.length > 0 ? lastQuerySteps : executionSteps
              }
              onNodeClick={scrollToStep}
            />
          </div>
        </div>

        <div className="flex min-w-0 flex-1 flex-col">
          <div className="relative min-h-0 flex-1">
            {queries.length === 0 ? (
              <div className="flex h-full items-center justify-center px-4">
                <EmptyState
                  size="sm"
                  illustration="none"
                  title={t('agents.workflow.preview.emptyTitle')}
                />
              </div>
            ) : (
              <MessageScrollerProvider autoScroll>
                <MessageScroller>
                  <MessageScrollerViewport className="px-4 pt-4">
                    <MessageScrollerContent className="w-full">
                      {queries.map((query, index) => {
                        const querySteps = query.executionSteps || [];
                        const hasResponse = !!(query.response || query.error);
                        const isLastQuery = index === queries.length - 1;
                        const isStreamingLastQuery =
                          status === 'loading' && isLastQuery;
                        const shouldShowThought =
                          !isStreamingLastQuery && Boolean(query.thought);
                        const isOpen =
                          openDetailsIndex === index ||
                          (!hasResponse &&
                            isLastQuery &&
                            querySteps.length > 0);
                        const hasAnswerBubble =
                          !!query.response ||
                          shouldShowThought ||
                          !!query.tool_calls;
                        const hasResponseItem =
                          querySteps.length > 0 ||
                          !!query.workflowRunId ||
                          hasAnswerBubble ||
                          !!query.error;

                        return (
                          <Fragment key={index}>
                            <MessageScrollerItem
                              messageId={`q-${index}`}
                              scrollAnchor
                            >
                              <ConversationBubble
                                className={index === 0 ? 'mt-5' : ''}
                                message={query.prompt}
                                type="QUESTION"
                                handleUpdatedQuestionSubmission={
                                  handleQuestionSubmission
                                }
                                questionNumber={index}
                              />
                            </MessageScrollerItem>

                            {hasResponseItem && (
                              <MessageScrollerItem messageId={`a-${index}`}>
                                {/* Execution Details */}
                                {querySteps.length > 0 && (
                                  <ExecutionDetails
                                    steps={querySteps}
                                    nodes={workflowData.nodes}
                                    isOpen={isOpen}
                                    onToggle={() =>
                                      setOpenDetailsIndex(
                                        openDetailsIndex === index
                                          ? null
                                          : index,
                                      )
                                    }
                                    stepRefs={
                                      isLastQuery ? stepRefs : undefined
                                    }
                                  />
                                )}
                                {query.workflowRunId && (
                                  <RunArtifactsSection
                                    workflowRunId={query.workflowRunId}
                                    isOpen={openArtifactsIndex === index}
                                    onToggle={() =>
                                      setOpenArtifactsIndex(
                                        openArtifactsIndex === index
                                          ? null
                                          : index,
                                      )
                                    }
                                    runInProgress={isStreamingLastQuery}
                                  />
                                )}

                                {/* Response bubble */}
                                {hasAnswerBubble && (
                                  <ConversationBubble
                                    className="mb-7"
                                    message={query.response}
                                    type="ANSWER"
                                    thought={
                                      shouldShowThought
                                        ? query.thought
                                        : undefined
                                    }
                                    sources={query.sources}
                                    toolCalls={query.tool_calls}
                                    feedback={query.feedback}
                                    isStreaming={isStreamingLastQuery}
                                  />
                                )}

                                {/* Error bubble */}
                                {query.error && (
                                  <ConversationBubble
                                    className="mb-7"
                                    message={query.error}
                                    type="ERROR"
                                  />
                                )}
                              </MessageScrollerItem>
                            )}
                          </Fragment>
                        );
                      })}
                    </MessageScrollerContent>
                  </MessageScrollerViewport>
                  <MessageScrollerButton />
                </MessageScroller>
              </MessageScrollerProvider>
            )}
          </div>
          <div className="flex w-full flex-col gap-2 px-4 pt-2 pb-4">
            {sendBlockedMessage && (
              <Alert variant="destructive">
                <CircleAlert />
                <AlertDescription>{t(sendBlockedMessage)}</AlertDescription>
              </Alert>
            )}
            <MessageInput
              onSubmit={(text) => handleQuestionSubmission(text)}
              loading={status === 'loading'}
              showSourceButton={false}
              showToolButton={false}
              autoFocus={true}
              allowSendWithoutText={true}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
