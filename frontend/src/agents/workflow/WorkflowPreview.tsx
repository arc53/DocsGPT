import {
  Bot,
  CheckCircle2,
  Circle,
  Database,
  Flag,
  Loader2,
  MessageSquare,
  Play,
  StickyNote,
  Workflow,
  XCircle,
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import { cn } from '@/lib/utils';

import ChevronDownIcon from '../../assets/chevron-down.svg';
import MessageInput from '../../components/MessageInput';
import ConversationBubble from '../../conversation/ConversationBubble';
import { Query } from '../../conversation/conversationModels';
import { AppDispatch } from '../../store';
import { WorkflowEdge, WorkflowNode } from '../types/workflow';
import {
  addQuery,
  fetchWorkflowPreviewAnswer,
  handleWorkflowPreviewAbort,
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
}

const NODE_ICONS: Record<string, React.ReactNode> = {
  start: <Play className="h-3 w-3" />,
  agent: <Bot className="h-3 w-3" />,
  end: <Flag className="h-3 w-3" />,
  note: <StickyNote className="h-3 w-3" />,
  state: <Database className="h-3 w-3" />,
};

const NODE_COLORS: Record<string, string> = {
  start: 'text-green-600 dark:text-green-400',
  agent: 'text-purple-600 dark:text-purple-400',
  end: 'text-gray-600 dark:text-gray-400',
  note: 'text-yellow-600 dark:text-yellow-400',
  state: 'text-blue-600 dark:text-blue-400',
};

function ExecutionDetails({
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
  const completedSteps = steps.filter(
    (s) => s.status === 'completed' || s.status === 'failed',
  );

  if (completedSteps.length === 0) return null;

  const formatValue = (value: unknown): string => {
    if (typeof value === 'string') return value;
    return JSON.stringify(value, null, 2);
  };

  return (
    <div className="mb-4 flex w-full flex-col flex-wrap items-start self-start lg:flex-nowrap">
      <div className="my-2 flex flex-row items-center justify-center gap-3">
        <div className="flex h-[26px] w-[30px] items-center justify-center">
          <Workflow className="h-5 w-5 text-gray-600 dark:text-gray-400" />
        </div>
        <button className="flex flex-row items-center gap-2" onClick={onToggle}>
          <p className="text-base font-semibold">
            Execution Details
            <span className="ml-1.5 text-sm font-normal text-gray-500 dark:text-gray-400">
              ({completedSteps.length}{' '}
              {completedSteps.length === 1 ? 'step' : 'steps'})
            </span>
          </p>
          <img
            src={ChevronDownIcon}
            alt="ChevronDown"
            className={cn(
              'h-4 w-4 transform transition-transform duration-200 dark:invert',
              isOpen ? 'rotate-180' : '',
            )}
          />
        </button>
      </div>
      <div
        className={cn(
          'ml-3 grid w-full transition-all duration-300 ease-in-out',
          isOpen ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0',
        )}
      >
        <div className="overflow-hidden">
          <div className="space-y-2 pr-2">
            {completedSteps.map((step, stepIndex) => {
              const node = nodes.find((n) => n.id === step.nodeId);
              const displayName =
                node?.title || node?.data?.title || step.nodeTitle;
              const stateVars = step.stateSnapshot
                ? Object.entries(step.stateSnapshot).filter(
                    ([key]) => !['query', 'chat_history'].includes(key),
                  )
                : [];

              const truncateText = (text: string, maxLength: number) => {
                if (text.length <= maxLength) return text;
                return text.slice(0, maxLength) + '...';
              };

              return (
                <div
                  key={step.nodeId}
                  ref={(el) => {
                    if (el && stepRefs) stepRefs.current.set(step.nodeId, el);
                  }}
                  className="rounded-xl bg-[#F5F5F5] p-3 dark:bg-[#383838]"
                >
                  <div className="flex items-center gap-2 text-sm">
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center text-xs font-medium text-gray-500 dark:text-gray-400">
                      {stepIndex + 1}.
                    </span>
                    <div
                      className={cn(
                        'shrink-0',
                        NODE_COLORS[step.nodeType] || NODE_COLORS.state,
                      )}
                    >
                      {NODE_ICONS[step.nodeType] || (
                        <Circle className="h-3 w-3" />
                      )}
                    </div>
                    <span className="min-w-0 truncate font-medium text-gray-900 dark:text-white">
                      {displayName}
                    </span>
                    <div className="ml-auto shrink-0">
                      {step.status === 'completed' && (
                        <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-400" />
                      )}
                      {step.status === 'failed' && (
                        <XCircle className="h-4 w-4 text-red-600 dark:text-red-400" />
                      )}
                    </div>
                  </div>
                  {(step.output || step.error || stateVars.length > 0) && (
                    <div className="mt-3 space-y-2 text-sm">
                      {step.output && (
                        <div className="rounded-lg bg-white p-2 dark:bg-[#2A2A2A]">
                          <span className="font-medium text-gray-600 dark:text-gray-400">
                            Output:{' '}
                          </span>
                          <span className="wrap-break-word whitespace-pre-wrap text-gray-900 dark:text-gray-100">
                            {truncateText(step.output, 300)}
                          </span>
                        </div>
                      )}
                      {step.error && (
                        <div className="rounded-lg bg-red-50 p-2 dark:bg-red-900/30">
                          <span className="font-medium text-red-700 dark:text-red-300">
                            Error:{' '}
                          </span>
                          <span className="wrap-break-word whitespace-pre-wrap text-red-800 dark:text-red-200">
                            {step.error}
                          </span>
                        </div>
                      )}
                      {stateVars.length > 0 && (
                        <div className="flex flex-wrap gap-2">
                          {stateVars.map(([key, value]) => (
                            <span
                              key={key}
                              className="inline-flex items-center rounded-lg bg-white px-2 py-1 text-xs dark:bg-[#2A2A2A]"
                            >
                              <span className="max-w-[100px] truncate font-medium text-gray-600 dark:text-gray-400">
                                {key}:
                              </span>
                              <span
                                className="ml-1 max-w-[200px] truncate text-gray-900 dark:text-gray-100"
                                title={formatValue(value)}
                              >
                                {truncateText(formatValue(value), 50)}
                              </span>
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

function WorkflowMiniMap({
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
  const getNodeDisplayName = (node: WorkflowNode) => {
    if (node.type === 'start') return 'Start';
    if (node.type === 'end') return 'End';
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

  const getStatusColor = (nodeId: string, nodeType: string) => {
    const status = getNodeStatus(nodeId);
    const isActive = nodeId === activeNodeId;

    if (isActive) {
      return 'ring-2 ring-purple-500 bg-purple-100 dark:bg-purple-900/50';
    }

    switch (status) {
      case 'completed':
        return 'bg-green-100 dark:bg-green-900/30 border-green-300 dark:border-green-700';
      case 'running':
        return 'bg-purple-100 dark:bg-purple-900/30 border-purple-300 dark:border-purple-700 animate-pulse';
      case 'failed':
        return 'bg-red-100 dark:bg-red-900/30 border-red-300 dark:border-red-700';
      default:
        if (nodeType === 'start') {
          return 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800';
        }
        if (nodeType === 'agent') {
          return 'bg-purple-50 dark:bg-purple-900/20 border-purple-200 dark:border-purple-800';
        }
        if (nodeType === 'end') {
          return 'bg-gray-50 dark:bg-gray-800 border-gray-200 dark:border-gray-700';
        }
        return 'bg-gray-50 dark:bg-gray-800 border-gray-200 dark:border-gray-700';
    }
  };

  const sortedNodes = [...nodes].sort((a, b) => {
    if (a.type === 'start') return -1;
    if (b.type === 'start') return 1;
    if (a.type === 'end') return 1;
    if (b.type === 'end') return -1;
    return (a.position?.y || 0) - (b.position?.y || 0);
  });

  const hasStepData = (nodeId: string) => {
    const step = executionSteps.find((s) => s.nodeId === nodeId);
    return step && (step.status === 'completed' || step.status === 'failed');
  };

  return (
    <div className="space-y-1">
      {sortedNodes.map((node, index) => (
        <div key={node.id} className="relative">
          {index < sortedNodes.length - 1 && (
            <div className="absolute top-12 left-4 h-3 w-0.5 bg-gray-200 dark:bg-gray-700" />
          )}

          <button
            onClick={() => hasStepData(node.id) && onNodeClick?.(node.id)}
            disabled={!hasStepData(node.id)}
            className={cn(
              'flex h-12 w-full items-center gap-2 rounded-lg border px-3 text-xs transition-all',
              getStatusColor(node.id, node.type),
              hasStepData(node.id) && 'cursor-pointer hover:opacity-80',
            )}
          >
            <div
              className={cn(
                'flex h-5 w-5 shrink-0 items-center justify-center rounded-full',
                NODE_COLORS[node.type] || NODE_COLORS.state,
              )}
            >
              {NODE_ICONS[node.type] || <Circle className="h-3 w-3" />}
            </div>
            <div className="min-w-0 flex-1 text-left">
              <div className="truncate font-medium text-gray-700 dark:text-gray-200">
                {getNodeDisplayName(node)}
              </div>
              {getNodeSubtitle(node) && (
                <div className="truncate text-[10px] text-gray-500 dark:text-gray-400">
                  {getNodeSubtitle(node)}
                </div>
              )}
            </div>
            <div className="shrink-0">
              {getNodeStatus(node.id) === 'running' && (
                <Loader2 className="h-3 w-3 animate-spin text-purple-500" />
              )}
              {getNodeStatus(node.id) === 'completed' && (
                <CheckCircle2 className="h-3 w-3 text-green-500" />
              )}
              {getNodeStatus(node.id) === 'failed' && (
                <XCircle className="h-3 w-3 text-red-500" />
              )}
            </div>
          </button>
        </div>
      ))}
    </div>
  );
}

export default function WorkflowPreview({
  workflowData,
}: WorkflowPreviewProps) {
  const dispatch = useDispatch<AppDispatch>();

  const queries = useSelector(selectWorkflowPreviewQueries) as WorkflowQuery[];
  const status = useSelector(selectWorkflowPreviewStatus);
  const executionSteps = useSelector(selectWorkflowExecutionSteps);
  const activeNodeId = useSelector(selectActiveNodeId);

  const [lastQueryReturnedErr, setLastQueryReturnedErr] = useState(false);
  const [openDetailsIndex, setOpenDetailsIndex] = useState<number | null>(null);

  const fetchStream = useRef<{ abort: () => void } | null>(null);
  const stepRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const chatContainerRef = useRef<HTMLDivElement>(null);

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
        }),
      );
      fetchStream.current = promise;
    },
    [dispatch, workflowData],
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
      const trimmedQuestion = question.trim();
      if (trimmedQuestion === '') return;

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
    [dispatch, handleFetchAnswer],
  );

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
    } else if (question && status !== 'loading') {
      const currentInput = question.trim();
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
    <div className="dark:bg-raisin-black flex h-full flex-col bg-white">
      <div className="border-light-silver dark:bg-raisin-black flex h-[77px] items-center justify-between border-b bg-white px-6 dark:border-[#3A3A3A]">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center rounded-full bg-gray-100 p-3 text-gray-600 dark:bg-[#2C2C2C] dark:text-gray-300">
            <Play className="h-4 w-4" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-gray-900 dark:text-white">
              Preview
            </h2>
            <p className="max-w-md truncate text-xs text-gray-500 dark:text-gray-400">
              {workflowData.name}
              {workflowData.description && ` - ${workflowData.description}`}
            </p>
          </div>
        </div>
        {status === 'loading' && (
          <span className="text-purple-30 dark:text-violets-are-blue flex items-center gap-1 text-xs">
            <Loader2 className="h-3 w-3 animate-spin" />
            Running
          </span>
        )}
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="flex w-64 shrink-0 flex-col border-r border-gray-200 dark:border-[#3A3A3A]">
          <div className="flex items-center justify-between px-4 py-3">
            <h3 className="text-xs font-semibold tracking-wider text-gray-500 uppercase dark:text-gray-400">
              Workflow
            </h3>
          </div>
          <div className="scrollbar-thin flex-1 overflow-y-auto p-3">
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

        <div className="relative flex min-w-0 flex-1 flex-col">
          <div
            ref={chatContainerRef}
            className="scrollbar-thin absolute inset-0 bottom-[100px] overflow-y-auto px-4 pt-4"
          >
            {queries.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center">
                <div className="mb-2 flex size-14 shrink-0 items-center justify-center rounded-xl bg-gray-100 dark:bg-[#2C2C2C]">
                  <MessageSquare className="size-6 text-gray-600 dark:text-gray-300" />
                </div>
                <p className="text-xl font-semibold text-gray-700 dark:text-gray-200">
                  Test the workflow
                </p>
              </div>
            ) : (
              <div className="w-full">
                {queries.map((query, index) => {
                  const querySteps = query.executionSteps || [];
                  const hasResponse = !!(query.response || query.error);
                  const isLastQuery = index === queries.length - 1;
                  const isOpen =
                    openDetailsIndex === index ||
                    (!hasResponse && isLastQuery && querySteps.length > 0);

                  return (
                    <div key={index}>
                      {/* Query bubble */}
                      <ConversationBubble
                        className={index === 0 ? 'mt-5' : ''}
                        message={query.prompt}
                        type="QUESTION"
                        handleUpdatedQuestionSubmission={
                          handleQuestionSubmission
                        }
                        questionNumber={index}
                      />

                      {/* Execution Details */}
                      {querySteps.length > 0 && (
                        <ExecutionDetails
                          steps={querySteps}
                          nodes={workflowData.nodes}
                          isOpen={isOpen}
                          onToggle={() =>
                            setOpenDetailsIndex(
                              openDetailsIndex === index ? null : index,
                            )
                          }
                          stepRefs={isLastQuery ? stepRefs : undefined}
                        />
                      )}

                      {/* Response bubble */}
                      {(query.response ||
                        query.thought ||
                        query.tool_calls) && (
                        <ConversationBubble
                          className={isLastQuery ? 'mb-32' : 'mb-7'}
                          message={query.response}
                          type="ANSWER"
                          thought={query.thought}
                          sources={query.sources}
                          toolCalls={query.tool_calls}
                          feedback={query.feedback}
                          isStreaming={status === 'loading' && isLastQuery}
                        />
                      )}

                      {/* Error bubble */}
                      {query.error && (
                        <ConversationBubble
                          className={isLastQuery ? 'mb-32' : 'mb-7'}
                          message={query.error}
                          type="ERROR"
                        />
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
          <div className="dark:bg-raisin-black absolute right-0 bottom-0 left-0 flex w-full flex-col gap-2 bg-white px-4 pt-2 pb-4">
            <MessageInput
              onSubmit={(text) => handleQuestionSubmission(text)}
              loading={status === 'loading'}
              showSourceButton={false}
              showToolButton={false}
              autoFocus={true}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
