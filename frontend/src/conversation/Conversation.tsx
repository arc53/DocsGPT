import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useParams } from 'react-router-dom';

import userService from '../api/services/userService';
import SharedAgentCard from '../agents/SharedAgentCard';
import { Agent } from '../agents/types';
import ArtifactSidebar from '../components/ArtifactSidebar';
import ErrorBoundary from '../components/ErrorBoundary';
import MessageInput from '../components/MessageInput';
import { useMediaQuery } from '../hooks';
import {
  selectConversationId,
  selectSelectedAgent,
  selectToken,
  setSelectedAgent,
} from '../preferences/preferenceSlice';
import { AppDispatch } from '../store';
import { handleSendFeedback } from './conversationHandlers';
import ConversationMessages from './ConversationMessages';
import { FEEDBACK, Query } from './conversationModels';
import { ToolCallsType } from './types';
import {
  addQuery,
  fetchAnswer,
  loadConversation,
  resendQuery,
  resetConversation,
  selectQueries,
  selectStatus,
  submitToolActions,
  updateQuery,
} from './conversationSlice';
import { getSendReadiness } from '../components/message-input/armedSend';
import {
  clearAttachments,
  selectAttachments,
  selectCompletedAttachments,
} from '../upload/uploadSlice';

export default function Conversation() {
  const { t } = useTranslation();
  const { isMobile } = useMediaQuery();
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const params = useParams<{
    conversationId?: string;
    agentId?: string;
  }>();
  const urlConversationId = params.conversationId;
  const urlAgentId = params.agentId;
  // ``new`` is treated as empty-chat intent, not a real id to fetch.
  const isNewChatRoute =
    urlConversationId === undefined || urlConversationId === 'new';

  const token = useSelector(selectToken);
  const queries = useSelector(selectQueries);
  const status = useSelector(selectStatus);
  const conversationId = useSelector(selectConversationId);
  const selectedAgent = useSelector(selectSelectedAgent);
  const completedAttachments = useSelector(selectCompletedAttachments);
  const attachments = useSelector(selectAttachments);
  // A direct send (hero card) that must wait for pending attachments is
  // parked here; MessageInput consumes it into an armed composer send.
  const [queuedQuestion, setQueuedQuestion] = useState<string | null>(null);

  const [lastQueryReturnedErr, setLastQueryReturnedErr] =
    useState<boolean>(false);

  // URL → state. Thunk short-circuits when Redux already matches.
  useEffect(() => {
    if (isNewChatRoute) {
      // Skip when nothing to reset; avoids wiping the in-flight stream
      // during the null → assigned-id replace below.
      if (conversationId !== null) {
        dispatch(resetConversation());
      }
      return;
    }
    if (urlConversationId && urlConversationId !== conversationId) {
      dispatch(loadConversation({ id: urlConversationId }))
        .unwrap()
        .then((result) => {
          if (result.stale) return;
          if (result.data === null) {
            navigate('/c/new', { replace: true });
          }
        })
        .catch(() => navigate('/c/new', { replace: true }));
    }
  }, [urlConversationId, isNewChatRoute]);

  // Agent context follows the URL. ``cancelled`` covers two races:
  // the user switches agents before the fetch resolves, or leaves the
  // agent route entirely; either way the late dispatch must be dropped.
  useEffect(() => {
    let cancelled = false;
    if (urlAgentId) {
      if (selectedAgent?.id !== urlAgentId) {
        userService
          .getAgent(urlAgentId, token)
          .then((response) => (response.ok ? response.json() : null))
          .then((agent: Agent | null) => {
            if (cancelled) return;
            if (agent) dispatch(setSelectedAgent(agent));
          })
          .catch((err) => {
            if (!cancelled) console.error('Failed to load agent:', err);
          });
      }
    } else if (selectedAgent !== null) {
      dispatch(setSelectedAgent(null));
    }
    return () => {
      cancelled = true;
    };
  }, [urlAgentId, token]);

  // State → URL. ``replace`` so Back doesn't return to /c/new and
  // reset the just-streamed chat.
  useEffect(() => {
    if (!isNewChatRoute || !conversationId) return;
    const target = urlAgentId
      ? `/agents/${urlAgentId}/c/${conversationId}`
      : `/c/${conversationId}`;
    navigate(target, { replace: true });
  }, [conversationId, isNewChatRoute, urlAgentId]);

  const handleToolAction = useCallback(
    (callId: string, decision: 'approved' | 'denied', comment?: string) => {
      dispatch(
        submitToolActions({
          toolActions: [{ call_id: callId, decision, comment }],
        }),
      );
    },
    [dispatch],
  );

  const lastAutoOpenedArtifactId = useRef<string | null>(null);
  const didInitArtifactAutoOpen = useRef(false);
  const prevConversationId = useRef<string | null>(conversationId);

  const [openArtifact, setOpenArtifact] = useState<{
    id: string;
    toolName: string;
  } | null>(null);

  const [conversationMountKey, setConversationMountKey] = useState(0);
  const [prevMountConversationId, setPrevMountConversationId] = useState<
    string | null
  >(conversationId);
  if (prevMountConversationId !== conversationId) {
    const isServerAssignedId =
      prevMountConversationId === null &&
      conversationId !== null &&
      isNewChatRoute;
    setPrevMountConversationId(conversationId);
    if (!isServerAssignedId) setConversationMountKey((k) => k + 1);
  }

  useEffect(() => {
    const prevId = prevConversationId.current;
    // Don't reset when the backend assigns the conversation id mid-stream (null -> id)
    const isServerAssignedId =
      prevId === null && conversationId !== null && status === 'loading';

    if (!isServerAssignedId && prevId !== conversationId) {
      setOpenArtifact(null);
      lastAutoOpenedArtifactId.current = null;
    }

    prevConversationId.current = conversationId;
  }, [conversationId, status]);

  const handleFetchAnswer = useCallback(
    ({
      question,
      index,
      attachmentIds,
    }: {
      question: string;
      index?: number;
      attachmentIds?: string[];
    }) => {
      dispatch(fetchAnswer({ question, indx: index, attachmentIds }));
    },
    [dispatch, selectedAgent],
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
        // Retry/edit of an existing turn: re-send the ids bound to that
        // row — the composer slice was consumed by the original send.
        const rowAttachmentIds = (queries[index]?.attachments ?? []).map(
          (a) => a.id,
        );
        dispatch(
          resendQuery({
            index,
            prompt: trimmedQuestion,
            keepIdempotencyKey: isRetry,
          }),
        );
        handleFetchAnswer({
          question: trimmedQuestion,
          index,
          attachmentIds: rowAttachmentIds,
        });
      } else if (getSendReadiness(attachments).state !== 'ready') {
        // Direct new sends (hero suggestion cards) bypass MessageInput's
        // submit gate. With files still uploading/parsing (or failed),
        // sending now would silently drop them — route the question into
        // the composer instead, where the armed-send banner takes over.
        setQueuedQuestion(trimmedQuestion);
      } else {
        const filesAttached = completedAttachments
          .filter((a) => a.id)
          .map((a) => ({ id: a.id as string, fileName: a.fileName }));

        if (!isRetry)
          dispatch(
            addQuery({
              prompt: trimmedQuestion,
              attachments: filesAttached,
            }),
          );
        // One source of truth: the ids on the wire are exactly the ids
        // the optimistic row displays.
        handleFetchAnswer({
          question: trimmedQuestion,
          index,
          attachmentIds: filesAttached.map((f) => f.id),
        });
        if (filesAttached.length > 0) dispatch(clearAttachments());
      }
    },
    [dispatch, handleFetchAnswer, completedAttachments, attachments, queries],
  );

  const handleFeedback = (query: Query, feedback: FEEDBACK, index: number) => {
    const prevFeedback = query.feedback;
    dispatch(updateQuery({ index, query: { feedback } }));
    handleSendFeedback(
      query.prompt,
      query.response!,
      feedback,
      conversationId as string,
      index,
      token,
    ).catch(() =>
      handleSendFeedback(
        query.prompt,
        query.response!,
        feedback,
        conversationId as string,
        index,
        token,
      ).catch(() =>
        dispatch(updateQuery({ index, query: { feedback: prevFeedback } })),
      ),
    );
  };

  const handleQuestionSubmission = (
    question?: string,
    updated?: boolean,
    indx?: number,
  ) => {
    if (updated === true) {
      handleQuestion({ question: question as string, index: indx });
    } else if (question && status !== 'loading') {
      if (lastQueryReturnedErr && queries.length > 0) {
        const retryIndex = queries.length - 1;
        // Different prompt = new logical action, fresh idempotency key.
        const prevPrompt = queries[retryIndex].prompt;
        const isSamePrompt = prevPrompt === question;
        if (!isSamePrompt) {
          dispatch(
            updateQuery({
              index: retryIndex,
              query: {
                prompt: question,
              },
            }),
          );
        }
        handleQuestion({
          question,
          isRetry: isSamePrompt,
          index: retryIndex,
        });
      } else {
        handleQuestion({
          question,
        });
      }
    }
  };

  useEffect(() => {
    if (queries.length) {
      const last = queries[queries.length - 1];
      if (last.error) setLastQueryReturnedErr(true);
      if (last.response) setLastQueryReturnedErr(false);
    }
  }, [queries]);

  useEffect(() => {
    // Avoid auto-opening an artifact from existing conversation history on first mount.
    if (!didInitArtifactAutoOpen.current) {
      didInitArtifactAutoOpen.current = true;
      return;
    }

    const isNotesOrTodoTool = (toolName?: string) => {
      const t = (toolName ?? '').toLowerCase();
      return t === 'notes' || t === 'todo_list' || t === 'todo';
    };

    const findLatestCompletedArtifactCall = (
      items: Query[],
    ): ToolCallsType | null => {
      for (let i = items.length - 1; i >= 0; i -= 1) {
        const calls = items[i].tool_calls ?? [];
        for (let j = calls.length - 1; j >= 0; j -= 1) {
          const call = calls[j];
          if (call.artifact_id && call.status === 'completed') return call;
        }
      }
      return null;
    };

    const latest = findLatestCompletedArtifactCall(queries);
    if (!latest?.artifact_id) return;
    if (!isNotesOrTodoTool(latest.tool_name)) return;
    if (latest.artifact_id === lastAutoOpenedArtifactId.current) return;

    lastAutoOpenedArtifactId.current = latest.artifact_id;
    setOpenArtifact({
      id: latest.artifact_id,
      toolName: latest.tool_name,
    });
  }, [queries]);

  const handleOpenArtifact = useCallback(
    (artifact: { id: string; toolName: string }) => {
      lastAutoOpenedArtifactId.current = artifact.id;
      setOpenArtifact(artifact);
    },
    [],
  );

  const handleCloseArtifact = useCallback(() => setOpenArtifact(null), []);

  const isSplitArtifactOpen = !isMobile && openArtifact !== null;

  return (
    <div className="flex h-full">
      <div
        className={`flex h-full min-h-0 flex-col transition-all ${
          isSplitArtifactOpen ? 'w-[60%] px-6' : 'w-full'
        }`}
      >
        <div className="relative min-h-0 flex-1">
          {/* A render crash in the message list must leave the composer
              usable; the boundary resets on conversation switch. */}
          <ErrorBoundary key={conversationMountKey}>
            <ConversationMessages
              handleQuestion={handleQuestion}
              handleQuestionSubmission={handleQuestionSubmission}
              handleFeedback={handleFeedback}
              queries={queries}
              status={status}
              showHeroOnEmpty={selectedAgent ? false : true}
              onOpenArtifact={handleOpenArtifact}
              onToolAction={handleToolAction}
              isSplitView={isSplitArtifactOpen}
              agentId={selectedAgent?.id}
              headerContent={
                selectedAgent ? (
                  <div className="flex w-full items-center justify-center py-4">
                    <SharedAgentCard
                      agent={selectedAgent}
                      onEdit={
                        selectedAgent.id
                          ? () =>
                              navigate(
                                selectedAgent.agent_type === 'workflow'
                                  ? `/agents/workflow/edit/${selectedAgent.id}`
                                  : `/agents/edit/${selectedAgent.id}`,
                              )
                          : undefined
                      }
                    />
                  </div>
                ) : undefined
              }
            />
          </ErrorBoundary>
          <div
            className={`from-background pointer-events-none absolute bottom-0 left-1/2 h-6 w-full -translate-x-1/2 rounded-t-2xl bg-linear-to-t to-transparent bg-clip-content px-2 ${
              isSplitArtifactOpen
                ? 'max-w-325'
                : 'max-w-325 md:w-11/12 lg:w-10/12 xl:w-9/12 2xl:w-8/12'
            }`}
          />
        </div>

        {/* One notch narrower than the message column above it, which keeps its
            own width. */}
        <div
          className={`bg-opacity-0 z-3 flex h-auto w-full flex-col items-end self-center rounded-2xl py-1 ${
            isSplitArtifactOpen
              ? 'max-w-290'
              : 'max-w-290 md:w-10/12 lg:w-9/12 xl:w-8/12 2xl:w-7/12'
          }`}
        >
          <div className="flex w-full items-center rounded-full px-2">
            <MessageInput
              key={conversationMountKey}
              onSubmit={(text) => {
                handleQuestionSubmission(text);
              }}
              queuedQuestion={queuedQuestion}
              onQueuedQuestionConsumed={() => setQueuedQuestion(null)}
              loading={status === 'loading'}
              showSourceButton={selectedAgent ? false : true}
              showToolButton={selectedAgent ? false : true}
            />
          </div>

          <p className="text-muted-foreground hidden w-full self-center bg-transparent py-2 text-center text-xs md:inline">
            {t('tagline')}
          </p>
        </div>
      </div>

      {isSplitArtifactOpen && (
        <div className="h-full min-h-0 w-[40%]">
          <ArtifactSidebar
            variant="split"
            isOpen={true}
            onClose={handleCloseArtifact}
            artifactId={openArtifact?.id ?? null}
            toolName={openArtifact?.toolName}
            conversationId={conversationId}
          />
        </div>
      )}

      {isMobile && (
        <ArtifactSidebar
          variant="overlay"
          isOpen={openArtifact !== null}
          onClose={handleCloseArtifact}
          artifactId={openArtifact?.id ?? null}
          toolName={openArtifact?.toolName}
          conversationId={conversationId}
        />
      )}
    </div>
  );
}
