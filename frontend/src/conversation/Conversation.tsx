import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import SharedAgentCard from '../agents/SharedAgentCard';
import ArtifactSidebar from '../components/ArtifactSidebar';
import MessageInput from '../components/MessageInput';
import { useMediaQuery } from '../hooks';
import {
  selectConversationId,
  selectSelectedAgent,
  selectToken,
} from '../preferences/preferenceSlice';
import { AppDispatch } from '../store';
import { handleSendFeedback } from './conversationHandlers';
import ConversationMessages from './ConversationMessages';
import { FEEDBACK, Query } from './conversationModels';
import { ToolCallsType } from './types';
import {
  addQuery,
  fetchAnswer,
  resendQuery,
  selectQueries,
  selectStatus,
  updateQuery,
} from './conversationSlice';
import { selectCompletedAttachments } from '../upload/uploadSlice';

export default function Conversation() {
  const { t } = useTranslation();
  const { isMobile } = useMediaQuery();
  const dispatch = useDispatch<AppDispatch>();

  const token = useSelector(selectToken);
  const queries = useSelector(selectQueries);
  const status = useSelector(selectStatus);
  const conversationId = useSelector(selectConversationId);
  const selectedAgent = useSelector(selectSelectedAgent);
  const completedAttachments = useSelector(selectCompletedAttachments);

  const [lastQueryReturnedErr, setLastQueryReturnedErr] =
    useState<boolean>(false);

  const lastAutoOpenedArtifactId = useRef<string | null>(null);
  const didInitArtifactAutoOpen = useRef(false);
  const prevConversationId = useRef<string | null>(conversationId);

  const [openArtifact, setOpenArtifact] = useState<{
    id: string;
    toolName: string;
  } | null>(null);

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
    ({ question, index }: { question: string; index?: number }) => {
      dispatch(fetchAnswer({ question, indx: index }));
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

      const filesAttached = completedAttachments
        .filter((a) => a.id)
        .map((a) => ({ id: a.id as string, fileName: a.fileName }));

      if (index !== undefined) {
        if (!isRetry) dispatch(resendQuery({ index, prompt: trimmedQuestion }));
        handleFetchAnswer({ question: trimmedQuestion, index });
      } else {
        if (!isRetry)
          dispatch(
            addQuery({
              prompt: trimmedQuestion,
              attachments: filesAttached,
            }),
          );
        handleFetchAnswer({ question: trimmedQuestion, index });
      }
    },
    [dispatch, handleFetchAnswer, completedAttachments],
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
        dispatch(
          updateQuery({
            index: retryIndex,
            query: {
              prompt: question,
            },
          }),
        );
        handleQuestion({
          question,
          isRetry: true,
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
        <div className="min-h-0 flex-1">
          <ConversationMessages
            handleQuestion={handleQuestion}
            handleQuestionSubmission={handleQuestionSubmission}
            handleFeedback={handleFeedback}
            queries={queries}
            status={status}
            showHeroOnEmpty={selectedAgent ? false : true}
            onOpenArtifact={handleOpenArtifact}
            isSplitView={isSplitArtifactOpen}
            headerContent={
              selectedAgent ? (
                <div className="flex w-full items-center justify-center py-4">
                  <SharedAgentCard agent={selectedAgent} />
                </div>
              ) : undefined
            }
          />
        </div>

        <div
          className={`bg-opacity-0 z-3 flex h-auto w-full flex-col items-end self-center rounded-2xl py-1 ${
            isSplitArtifactOpen
              ? 'max-w-[1300px]'
              : 'max-w-[1300px] md:w-9/12 lg:w-8/12 xl:w-8/12 2xl:w-6/12'
          }`}
        >
          <div className="flex w-full items-center rounded-[40px] px-2">
            <MessageInput
              key={conversationId || 'new'}
              onSubmit={(text) => {
                handleQuestionSubmission(text);
              }}
              loading={status === 'loading'}
              showSourceButton={selectedAgent ? false : true}
              showToolButton={selectedAgent ? false : true}
            />
          </div>

          <p className="text-gray-4000 dark:text-sonic-silver hidden w-full self-center bg-transparent py-2 text-center text-xs md:inline">
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
        />
      )}
    </div>
  );
}
