import { useCallback, useEffect, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import MessageInput from '../components/MessageInput';
import ConversationMessages from '../conversation/ConversationMessages';
import { Query } from '../conversation/conversationModels';
import {
  addQuery,
  fetchAnswer,
  handleAbort,
  resendQuery,
  resetConversation,
  selectQueries,
  selectStatus,
} from '../conversation/conversationSlice';
import { selectSelectedAgent } from '../preferences/preferenceSlice';
import { AppDispatch } from '../store';

export default function AgentPreview() {
  const dispatch = useDispatch<AppDispatch>();

  const queries = useSelector(selectQueries);
  const status = useSelector(selectStatus);
  const selectedAgent = useSelector(selectSelectedAgent);

  const [input, setInput] = useState('');
  const [lastQueryReturnedErr, setLastQueryReturnedErr] = useState(false);

  const fetchStream = useRef<any>(null);

  const handleFetchAnswer = useCallback(
    ({ question, index }: { question: string; index?: number }) => {
      fetchStream.current = dispatch(
        fetchAnswer({ question, indx: index, isPreview: true }),
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
    updatedQuestion?: string,
    updated?: boolean,
    indx?: number,
  ) => {
    if (
      updated === true &&
      updatedQuestion !== undefined &&
      indx !== undefined
    ) {
      handleQuestion({
        question: updatedQuestion,
        index: indx,
        isRetry: false,
      });
    } else if (input.trim() && status !== 'loading') {
      const currentInput = input.trim();
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
      setInput('');
    }
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      handleQuestionSubmission();
    }
  };

  useEffect(() => {
    dispatch(resetConversation());
    return () => {
      if (fetchStream.current) fetchStream.current.abort();
      handleAbort();
      dispatch(resetConversation());
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
      <div className="flex h-full flex-col items-center justify-between gap-2 overflow-y-hidden dark:bg-raisin-black">
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
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onSubmit={() => handleQuestionSubmission()}
            loading={status === 'loading'}
            showSourceButton={selectedAgent ? false : true}
            showToolButton={selectedAgent ? false : true}
          />
          <p className="w-full self-center bg-transparent pt-2 text-center text-xs text-gray-4000 dark:text-sonic-silver md:inline">
            This is a preview of the agent. You can publish it to start using it
            in conversations.
          </p>
        </div>
      </div>
    </div>
  );
}
