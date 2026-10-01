import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useParams } from 'react-router-dom';

import userService from '../api/services/userService';
import { canOpenAgentEditor } from '../agents/agentAccess';
import SharedAgentCard from '../agents/SharedAgentCard';
import { Agent } from '../agents/types';
import ArtifactPanel from '../components/ArtifactPanel';
import ErrorBoundary from '../components/ErrorBoundary';
import MessageInput from '../components/MessageInput';
import { SidePanel } from '../components/ui/side-panel';
import { agentChatPath, agentEditPathFor } from '../agents/paths';
import { useMediaQuery } from '../hooks';
import {
  selectAgents,
  selectConversationId,
  selectSelectedAgent,
  selectToken,
  setSelectedAgent,
} from '../preferences/preferenceSlice';
import { AppDispatch } from '../store';
import { ChatCompanionContext, type AnswerSource } from './chatCompanion';
import { handleSendFeedback } from './conversationHandlers';
import ConversationMessages from './ConversationMessages';
import SourcesPanel from './SourcesPanel';
import { FEEDBACK, Query } from './conversationModels';
import { composerSubmitTarget, resendPlan } from './turnSubmission';
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
  selectSendableAttachments,
} from '../upload/uploadSlice';
import { cn } from '@/lib/utils';

/** What the chat's one docked side panel shows (DESIGN.md "Side panels"). */
type ChatCompanion =
  | { kind: 'artifact'; id: string; toolName: string }
  | { kind: 'sources'; sources: AnswerSource[] };

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
  const agents = useSelector(selectAgents);
  const sendableAttachments = useSelector(selectSendableAttachments);
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
      ? agentChatPath(urlAgentId, conversationId)
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
  // The mount key the auto-open below last saw; a new one is a chat
  // whose history must not open anything.
  const autoOpenMountKey = useRef<number | null>(null);

  const [companion, setCompanion] = useState<ChatCompanion | null>(null);
  // Keeps the last content on screen while the phone sheet slides out.
  const [shownCompanion, setShownCompanion] = useState(companion);
  if (companion && companion !== shownCompanion) setShownCompanion(companion);

  // The first prompt sent while the chat had no id. The id the server then
  // assigns belongs to that chat; a chat opened from the sidebar while the
  // URL is still /c/new starts with another prompt.
  const [unsavedFirstPrompt, setUnsavedFirstPrompt] = useState<string | null>(
    null,
  );
  const firstPrompt = queries[0]?.prompt ?? null;
  if (conversationId === null && unsavedFirstPrompt !== firstPrompt)
    setUnsavedFirstPrompt(firstPrompt);

  const [conversationMountKey, setConversationMountKey] = useState(0);
  const [prevMountConversationId, setPrevMountConversationId] = useState<
    string | null
  >(conversationId);
  const [prevMountAgentId, setPrevMountAgentId] = useState(urlAgentId);
  const conversationChanged = prevMountConversationId !== conversationId;
  const agentChanged = prevMountAgentId !== urlAgentId;
  if (conversationChanged || agentChanged) {
    const isServerAssignedId =
      prevMountConversationId === null &&
      conversationId !== null &&
      isNewChatRoute &&
      unsavedFirstPrompt !== null &&
      unsavedFirstPrompt === firstPrompt;
    // Another agent's new chat keeps the null id, so only the agent tells
    // it apart; a draft or armed send must not carry over to that agent.
    const isNewChatForAnotherAgent =
      agentChanged && prevMountConversationId === null && !conversationId;
    setPrevMountConversationId(conversationId);
    setPrevMountAgentId(urlAgentId);
    if (
      (conversationChanged && !isServerAssignedId) ||
      isNewChatForAnotherAgent
    ) {
      // Switching chats keeps this component mounted (a route change
      // does not remount it), so the per-chat state resets here.
      setConversationMountKey((k) => k + 1);
      setQueuedQuestion(null);
      setLastQueryReturnedErr(false);
      setCompanion(null);
    }
  }

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
        // row — the composer slice was consumed by the original send —
        // unless they went to Knowledge since.
        const plan = resendPlan(queries[index], isRetry);
        if (plan.dropRowAttachments) {
          dispatch(
            updateQuery({
              index,
              query: { attachments: undefined, attachmentsInKnowledge: false },
            }),
          );
        }
        dispatch(
          resendQuery({
            index,
            prompt: trimmedQuestion,
            keepIdempotencyKey: plan.keepIdempotencyKey,
          }),
        );
        handleFetchAnswer({
          question: trimmedQuestion,
          index,
          attachmentIds: plan.attachmentIds,
        });
      } else if (getSendReadiness(attachments).state !== 'ready') {
        // Direct new sends (hero suggestion cards) bypass MessageInput's
        // submit gate. With files still uploading/parsing, sending now
        // would silently drop them — route the question into the composer
        // instead, where the armed-send banner takes over.
        setQueuedQuestion(trimmedQuestion);
      } else {
        const filesAttached = sendableAttachments;

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
        // Clears the sent files and drops any failed ones, which never
        // hold a send (nothing is pending here, so nothing else remains).
        if (attachments.length > 0) dispatch(clearAttachments());
      }
    },
    [dispatch, handleFetchAnswer, sendableAttachments, attachments, queries],
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
      const target = composerSubmitTarget({
        question,
        queries,
        lastQueryReturnedErr,
        composerFileCount: sendableAttachments.length,
      });
      if (target.kind === 'retry') {
        // Different prompt = new logical action, fresh idempotency key.
        if (!target.samePrompt) {
          dispatch(
            updateQuery({
              index: target.index,
              query: {
                prompt: question,
              },
            }),
          );
        }
        handleQuestion({
          question,
          isRetry: target.samePrompt,
          index: target.index,
        });
      } else {
        handleQuestion({
          question,
        });
      }
    }
  };

  const handleKnowledgeAdded = useCallback(
    (index: number) => {
      dispatch(updateQuery({ index, query: { attachmentsInKnowledge: true } }));
    },
    [dispatch],
  );

  useEffect(() => {
    if (queries.length) {
      const last = queries[queries.length - 1];
      if (last.error) setLastQueryReturnedErr(true);
      if (last.response) setLastQueryReturnedErr(false);
    }
  }, [queries]);

  useEffect(() => {
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

    const found = findLatestCompletedArtifactCall(queries);
    const latest =
      found?.artifact_id && isNotesOrTodoTool(found.tool_name) ? found : null;

    // A chat's existing history (first mount, or another chat loaded)
    // opens nothing. Its latest artifact counts as seen, so the next send
    // does not open it either; only a new one does.
    if (autoOpenMountKey.current !== conversationMountKey) {
      autoOpenMountKey.current = conversationMountKey;
      lastAutoOpenedArtifactId.current = latest?.artifact_id ?? null;
      return;
    }

    if (!latest?.artifact_id) return;
    if (latest.artifact_id === lastAutoOpenedArtifactId.current) return;

    lastAutoOpenedArtifactId.current = latest.artifact_id;
    setCompanion({
      kind: 'artifact',
      id: latest.artifact_id,
      toolName: latest.tool_name,
    });
  }, [queries, conversationMountKey]);

  const handleOpenArtifact = useCallback(
    (artifact: { id: string; toolName: string }) => {
      lastAutoOpenedArtifactId.current = artifact.id;
      setCompanion({ kind: 'artifact', ...artifact });
    },
    [],
  );

  const companionContext = useMemo(
    () => ({
      openSources: (sources: AnswerSource[]) =>
        setCompanion({ kind: 'sources', sources }),
    }),
    [],
  );

  const isCompanionDocked = !isMobile && companion !== null;

  const companionPanel =
    shownCompanion?.kind === 'artifact' ? (
      <ArtifactPanel
        artifactId={shownCompanion.id}
        toolName={shownCompanion.toolName}
        conversationId={conversationId}
      />
    ) : shownCompanion?.kind === 'sources' ? (
      <SourcesPanel sources={shownCompanion.sources} />
    ) : null;

  return (
    <ChatCompanionContext.Provider value={companionContext}>
      <div className="relative flex h-full overflow-hidden">
        <div
          className={cn(
            'relative flex h-full min-h-0 min-w-0 flex-1 flex-col transition-[padding] duration-300 ease-in-out',
            isCompanionDocked && 'px-6',
          )}
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
                isSplitView={isCompanionDocked}
                agentId={selectedAgent?.id}
                // Same rule as the composer's Knowledge picker: an agent's
                // sources are its own.
                canAddToKnowledge={!selectedAgent}
                onKnowledgeAdded={handleKnowledgeAdded}
                headerContent={
                  selectedAgent ? (
                    <div className="flex w-full items-center justify-center py-4">
                      <SharedAgentCard
                        agent={selectedAgent}
                        onEdit={
                          // Only a role that may open the edit page gets Edit.
                          canOpenAgentEditor(selectedAgent, agents)
                            ? () => navigate(agentEditPathFor(selectedAgent))
                            : undefined
                        }
                      />
                    </div>
                  ) : undefined
                }
              />
            </ErrorBoundary>
            <div
              className={cn(
                'from-background pointer-events-none absolute bottom-0 left-1/2 h-6 w-full -translate-x-1/2 rounded-t-2xl bg-linear-to-t to-transparent bg-clip-content px-2',
                isCompanionDocked
                  ? 'max-w-325'
                  : 'max-w-325 md:w-11/12 lg:w-10/12 xl:w-9/12 2xl:w-8/12',
              )}
            />
          </div>

          {/* One notch narrower than the message column above it, which keeps its
            own width. */}
          <div
            className={cn(
              'z-10 flex h-auto w-full flex-col items-end self-center rounded-2xl py-1',
              isCompanionDocked
                ? 'max-w-290'
                : 'max-w-290 md:w-10/12 lg:w-9/12 xl:w-8/12 2xl:w-7/12',
            )}
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

        {/* One docked slot: an artifact or an answer's sources. */}
        <SidePanel
          variant="docked"
          open={companion !== null}
          onOpenChange={(open) => {
            if (!open) setCompanion(null);
          }}
          expandable={
            shownCompanion?.kind === 'artifact' ? 'artifact' : undefined
          }
        >
          {companionPanel}
        </SidePanel>
      </div>
    </ChatCompanionContext.Provider>
  );
}
