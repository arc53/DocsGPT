import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useParams } from 'react-router-dom';

import userService from '../api/services/userService';
import Clock from '../assets/clock.svg';
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
      fetchStream.current = dispatch(
        fetchAnswer({ question, indx: index, isPreview: false }),
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
          <p className="text-center text-lg text-[#71717A] dark:text-[#949494]">
            No agent found. Please ensure the agent is shared.
          </p>
        </div>
      </div>
    );
  return (
    <div className="relative h-full w-full">
      <div className="absolute left-4 top-5 hidden items-center gap-3 sm:flex">
        <img
          src={sharedAgent.image ?? Robot}
          alt="agent-logo"
          className="h-6 w-6"
        />
        <h2 className="text-lg font-semibold text-[#212121] dark:text-[#E0E0E0]">
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
        <div className="flex w-[95%] max-w-[1500px] flex-col items-center gap-4 pb-2 md:w-9/12 lg:w-8/12 xl:w-8/12 2xl:w-6/12">
          <MessageInput
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onSubmit={() => handleQuestionSubmission()}
            loading={status === 'loading'}
            showSourceButton={sharedAgent ? false : true}
            showToolButton={sharedAgent ? false : true}
            autoFocus={false}
          />
          <p className="hidden w-[100vw] self-center bg-transparent py-2 text-center text-xs text-gray-4000 dark:text-sonic-silver md:inline md:w-full">
            {t('tagline')}
          </p>
        </div>
      </div>
    </div>
  );
}

function SharedAgentCard({ agent }: { agent: Agent }) {
  return (
    <div className="flex w-full max-w-[720px] flex-col rounded-3xl border border-dark-gray p-6 shadow-sm dark:border-grey sm:w-fit sm:min-w-[480px]">
      <div className="flex items-center gap-3">
        <div className="flex h-12 w-12 items-center justify-center overflow-hidden rounded-full p-1">
          <img src={Robot} className="h-full w-full object-contain" />
        </div>
        <div className="flex max-h-[92px] w-[80%] flex-col gap-px">
          <h2 className="text-base font-semibold text-[#212121] dark:text-[#E0E0E0] sm:text-lg">
            {agent.name}
          </h2>
          <p className="overflow-y-auto text-wrap break-all text-xs text-[#71717A] dark:text-[#949494] sm:text-sm">
            {agent.description}
          </p>
        </div>
      </div>
      <div className="mt-4 flex items-center gap-8">
        {agent.shared_metadata?.shared_by && (
          <p className="text-xs font-light text-[#212121] dark:text-[#E0E0E0] sm:text-sm">
            by {agent.shared_metadata.shared_by}
          </p>
        )}
        {agent.shared_metadata?.shared_at && (
          <div className="flex items-center gap-[6px]">
            <img src={Clock} />
            <p className="text-xs font-light text-[#71717A] dark:text-[#949494] sm:text-sm">
              Shared on{' '}
              {new Date(agent.shared_metadata.shared_at).toLocaleString(
                'en-US',
                {
                  month: 'long',
                  day: 'numeric',
                  year: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit',
                  hour12: true,
                },
              )}
            </p>
          </div>
        )}
      </div>
      {agent.tools.length > 0 && (
        <div className="mt-8">
          <p className="text-sm font-semibold text-[#212121] dark:text-[#E0E0E0] sm:text-base">
            Connected Tools
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {agent.tools.map((tool, index) => (
              <span
                key={index}
                className="flex items-center gap-1 rounded-full bg-bright-gray px-3 py-1 text-xs font-light text-[#212121] dark:bg-dark-charcoal dark:text-[#E0E0E0]"
              >
                <img
                  src={`/toolIcons/tool_${tool}.svg`}
                  alt={`${tool} icon`}
                  className="h-3 w-3"
                />{' '}
                {tool}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
