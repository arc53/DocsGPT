import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import MessageInput from '../components/MessageInput';
import ConversationMessages from '../conversation/ConversationMessages';
import { Query } from '../conversation/conversationModels';
import { selectSelectedAgent } from '../preferences/preferenceSlice';
import { AppDispatch } from '../store';
import {
  addQuery,
  fetchPreviewAnswer,
  handlePreviewAbort,
  resendQuery,
  resetPreview,
  selectPreviewQueries,
  selectPreviewStatus,
} from './agentPreviewSlice';

export default function AgentPreview() {
  const { t } = useTranslation();
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
    <div className="relative h-full w-full">
      <div className="scrollbar-overlay absolute inset-0 bottom-[180px] overflow-hidden px-4 pt-4 [&>div>div]:w-full! [&>div>div]:max-w-none!">
        <ConversationMessages
          handleQuestion={handleQuestion}
          handleQuestionSubmission={handleQuestionSubmission}
          queries={queries}
          status={status}
          showHeroOnEmpty={false}
        />
      </div>
      <div className="absolute right-0 bottom-0 left-0 flex w-full flex-col gap-4 pb-2">
        <div className="w-full px-4">
          <MessageInput
            onSubmit={(text) => handleQuestionSubmission(text)}
            loading={status === 'loading'}
            showSourceButton={selectedAgent ? false : true}
            showToolButton={selectedAgent ? false : true}
            autoFocus={false}
          />
        </div>
        <p className="text-gray-4000 dark:text-sonic-silver w-full bg-transparent text-center text-xs md:inline">
          {t('agents.preview.testMessage')}
        </p>
      </div>
    </div>
  );
}
