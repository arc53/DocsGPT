import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useParams } from 'react-router-dom';

import userService from '../api/services/userService';
import NoFilesDarkIcon from '../assets/no-files-dark.svg';
import NoFilesIcon from '../assets/no-files.svg';
import Robot from '../assets/robot.svg';
import MessageInput from '../components/MessageInput';
import Spinner from '../components/Spinner';
import ConversationMessages from '../conversation/ConversationMessages';
import { Query } from '../conversation/conversationModels';
import {
  addQuery,
  fetchAnswer,
  resendQuery,
  selectQueries,
  selectStatus,
} from '../conversation/conversationSlice';
import { useDarkTheme } from '../hooks';
import { selectToken, setSelectedAgent } from '../preferences/preferenceSlice';
import { AppDispatch } from '../store';
import SharedAgentCard from './SharedAgentCard';
import { Agent } from './types';

export default function SharedAgent() {
  const { t } = useTranslation();
  const { agentId } = useParams();
  const dispatch = useDispatch<AppDispatch>();
  const [isDarkTheme] = useDarkTheme();

  const token = useSelector(selectToken);
  const queries = useSelector(selectQueries);
  const status = useSelector(selectStatus);

  const [sharedAgent, setSharedAgent] = useState<Agent>();
  const [isLoading, setIsLoading] = useState(true);
  const [input, setInput] = useState('');
  const [lastQueryReturnedErr, setLastQueryReturnedErr] = useState(false);

  const fetchStream = useRef<any>(null);

  const getSharedAgent = async () => {
    try {
      setIsLoading(true);
      const response = await userService.getSharedAgent(agentId ?? '', token);
      if (!response.ok) throw new Error('Failed to fetch Shared Agent');
      const agent: Agent = await response.json();
      setSharedAgent(agent);
    } catch (error) {
      console.error('Error: ', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleFetchAnswer = useCallback(
    ({ question, index }: { question: string; index?: number }) => {
      fetchStream.current = dispatch(fetchAnswer({ question, indx: index }));
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
      setInput('');
    }
  };

  useEffect(() => {
    if (agentId) getSharedAgent();
  }, [agentId, token]);

  useEffect(() => {
    if (sharedAgent) dispatch(setSelectedAgent(sharedAgent));
  }, [sharedAgent, dispatch]);

  if (isLoading)
    return (
      <div className="flex h-full w-full items-center justify-center">
        <Spinner />
      </div>
    );
  if (!sharedAgent)
    return (
      <div className="flex h-full w-full items-center justify-center">
        <div className="flex w-full flex-col items-center justify-center gap-4">
          <img
            src={isDarkTheme ? NoFilesDarkIcon : NoFilesIcon}
            alt="No agent found"
            className="mx-auto mb-6 h-32 w-32"
          />
          <p className="dark:text-gray-4000 text-center text-lg text-[#71717A]">
            No agent found. Please ensure the agent is shared.
          </p>
        </div>
      </div>
    );
  return (
    <div className="relative h-full w-full">
      <div className="absolute top-5 left-4 hidden items-center gap-3 sm:flex">
        <img
          src={
            sharedAgent.image && sharedAgent.image.trim() !== ''
              ? sharedAgent.image
              : Robot
          }
          alt="agent-logo"
          className="h-6 w-6 rounded-full object-contain"
        />
        <h2 className="text-eerie-black text-lg font-semibold dark:text-[#E0E0E0]">
          {sharedAgent.name}
        </h2>
      </div>
      <div className="flex h-full w-full flex-col items-center justify-between sm:pt-12">
        <div className="flex w-full flex-col items-center overflow-y-auto">
          <ConversationMessages
            handleQuestion={handleQuestion}
            handleQuestionSubmission={handleQuestionSubmission}
            queries={queries}
            status={status}
            showHeroOnEmpty={false}
            headerContent={
              <div className="flex w-full items-center justify-center py-4">
                <SharedAgentCard agent={sharedAgent} />
              </div>
            }
          />
        </div>
        <div className="flex w-[95%] max-w-[1500px] flex-col items-center pb-2 md:w-9/12 lg:w-8/12 xl:w-8/12 2xl:w-6/12">
          <MessageInput
            onSubmit={(text) => handleQuestionSubmission(text)}
            loading={status === 'loading'}
            showSourceButton={sharedAgent ? false : true}
            showToolButton={sharedAgent ? false : true}
            autoFocus={false}
          />
          <p className="text-gray-4000 dark:text-sonic-silver hidden w-screen self-center bg-transparent py-2 text-center text-xs md:inline md:w-full">
            {t('tagline')}
          </p>
        </div>
      </div>
    </div>
  );
}
