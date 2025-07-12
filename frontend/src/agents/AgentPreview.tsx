import { useCallback, useEffect, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import MessageInput from '../components/MessageInput';
import ConversationMessages from '../conversation/ConversationMessages';
import { Query } from '../conversation/conversationModels';
import {
  addQuery,
  fetchPreviewAnswer,
  handlePreviewAbort,
  resendQuery,
  resetPreview,
  selectPreviewQueries,
  selectPreviewStatus,
} from './agentPreviewSlice';
import { selectSelectedAgent } from '../preferences/preferenceSlice';
import { AppDispatch } from '../store';

export default function AgentPreview() {
  const dispatch = useDispatch<AppDispatch>();

  const queries = useSelector(selectPreviewQueries);
  const status = useSelector(selectPreviewStatus);
  const selectedAgent = useSelector(selectSelectedAgent);

  const [lastQueryReturnedErr, setLastQueryReturnedErr] = useState(false);

  const fetchStream = useRef<any>(null);

  const handleFetchAnswer = useCallback(
    ({ question, index }: { question: string; index?: number }) => {
      fetchStream.current = dispatch(
        fetchPreviewAnswer({ question, indx: index }),
      );
    },
    [dispatch],
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
    dispatch(resetPreview());
    return () => {
      if (fetchStream.current) fetchStream.current.abort();
      handlePreviewAbort();
      dispatch(resetPreview());
    };
  }, [dispatch]);

  useEffect(() => {
    if (queries.length > 0) {
      const lastQuery = queries[queries.length - 1];
      setLastQueryReturnedErr(!!lastQuery.error);
    } else setLastQueryReturnedErr(false);
  }, [queries]);
  return (
    <div>
      <div className="dark:bg-raisin-black flex h-full flex-col items-center justify-between gap-2 overflow-y-hidden">
        <div className="h-[512px] w-full overflow-y-auto">
          <ConversationMessages
            handleQuestion={handleQuestion}
            handleQuestionSubmission={handleQuestionSubmission}
            queries={queries}
            status={status}
            showHeroOnEmpty={false}
          />
        </div>
        <div className="flex w-[95%] max-w-[1500px] flex-col items-center gap-4 pb-2 md:w-9/12 lg:w-8/12 xl:w-8/12 2xl:w-6/12">
          <MessageInput
            onSubmit={(text) => handleQuestionSubmission(text)}
            loading={status === 'loading'}
            showSourceButton={selectedAgent ? false : true}
            showToolButton={selectedAgent ? false : true}
            autoFocus={false}
          />
          <p className="text-gray-4000 dark:text-sonic-silver w-full self-center bg-transparent pt-2 text-center text-xs md:inline">
            This is a preview of the agent. You can publish it to start using it
            in conversations.
          </p>
        </div>
      </div>
    </div>
  );
}
