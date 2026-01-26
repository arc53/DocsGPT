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
  XCircle,
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import { cn } from '@/lib/utils';

import MessageInput from '../../components/MessageInput';
import ConversationMessages from '../../conversation/ConversationMessages';
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

function WorkflowMiniMap({
  nodes,
  activeNodeId,
  executionSteps,
}: {
  nodes: WorkflowNode[];
  activeNodeId: string | null;
  executionSteps: WorkflowExecutionStep[];
}) {
  const getNodeIcon = (type: string) => {
    switch (type) {
      case 'start':
        return <Play className="h-3 w-3" />;
      case 'agent':
        return <Bot className="h-3 w-3" />;
      case 'end':
        return <Flag className="h-3 w-3" />;
      case 'note':
        return <StickyNote className="h-3 w-3" />;
      case 'state':
        return <Database className="h-3 w-3" />;
      default:
        return <Circle className="h-3 w-3" />;
    }
  };

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

  return (
    <div className="space-y-1">
      {sortedNodes.map((node, index) => (
        <div key={node.id} className="relative">
          {index < sortedNodes.length - 1 && (
            <div className="absolute top-12 left-4 h-3 w-0.5 bg-gray-200 dark:bg-gray-700" />
          )}

          <div
            className={cn(
              'flex h-12 items-center gap-2 rounded-lg border px-3 text-xs transition-all',
              getStatusColor(node.id, node.type),
            )}
          >
            <div
              className={cn(
                'flex h-5 w-5 shrink-0 items-center justify-center rounded-full',
                node.type === 'start' && 'text-green-600 dark:text-green-400',
                node.type === 'agent' && 'text-purple-600 dark:text-purple-400',
                node.type === 'end' && 'text-gray-600 dark:text-gray-400',
                node.type === 'note' && 'text-yellow-600 dark:text-yellow-400',
                node.type === 'state' && 'text-blue-600 dark:text-blue-400',
              )}
            >
              {getNodeIcon(node.type)}
            </div>
            <div className="min-w-0 flex-1">
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
          </div>
        </div>
      ))}
    </div>
  );
}

export default function WorkflowPreview({
  workflowData,
}: WorkflowPreviewProps) {
  const dispatch = useDispatch<AppDispatch>();

  const queries = useSelector(selectWorkflowPreviewQueries);
  const status = useSelector(selectWorkflowPreviewStatus);
  const executionSteps = useSelector(selectWorkflowExecutionSteps);
  const activeNodeId = useSelector(selectActiveNodeId);

  const [lastQueryReturnedErr, setLastQueryReturnedErr] = useState(false);

  const fetchStream = useRef<{ abort: () => void } | null>(null);

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
              executionSteps={executionSteps}
            />
          </div>
        </div>

        <div className="relative flex min-w-0 flex-1 flex-col">
          <div className="scrollbar-thin absolute inset-0 bottom-[100px] overflow-y-auto px-4 pt-4">
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
              <div className="[&>div>div]:w-full! [&>div>div]:max-w-none!">
                <ConversationMessages
                  handleQuestion={handleQuestion}
                  handleQuestionSubmission={handleQuestionSubmission}
                  queries={queries}
                  status={status}
                  showHeroOnEmpty={false}
                />
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
