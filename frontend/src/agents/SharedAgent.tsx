import { useCallback, useEffect, useRef, useState } from 'react';
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
  updateConversationId,
} from '../conversation/conversationSlice';
import { useDarkTheme } from '../hooks';
import {
  selectToken,
  setConversations,
  setSelectedAgent,
} from '../preferences/preferenceSlice';
import { AppDispatch } from '../store';
import { Agent } from './types';

export default function SharedAgent() {
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
    <div className="h-full w-full pt-10">
      <div className="flex h-full w-full flex-col items-center justify-between">
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
          <p className="w-full self-center bg-transparent pt-2 text-center text-xs text-gray-4000 dark:text-sonic-silver md:inline">
            This is a preview of the agent. You can publish it to start using it
            in conversations.
          </p>
        </div>
      </div>
    </div>
  );
}

function SharedAgentCard({ agent }: { agent: Agent }) {
  return (
    <div className="flex max-w-[720px] flex-col rounded-3xl border border-dark-gray p-6 shadow-md dark:border-grey">
      <div className="flex items-center gap-3">
        <div className="flex h-12 w-12 items-center justify-center overflow-hidden rounded-full p-1">
          <img src={Robot} className="h-full w-full object-contain" />
        </div>
        <div className="flex max-h-[92px] w-[80%] flex-col gap-px">
          <h2 className="text-lg font-semibold text-[#212121] dark:text-[#E0E0E0]">
            {agent.name}
          </h2>
          <p className="overflow-y-auto text-wrap break-all text-sm text-[#71717A] dark:text-[#949494]">
            {agent.description}
          </p>
        </div>
      </div>
      <div className="mt-4 flex items-center gap-8">
        {agent.shared_metadata?.shared_by && (
          <p className="text-sm font-light text-[#212121] dark:text-[#E0E0E0]">
            by {agent.shared_metadata.shared_by}
          </p>
        )}
        {agent.shared_metadata?.shared_at && (
          <p className="text-sm font-light text-[#71717A] dark:text-[#949494]">
            Shared on{' '}
            {new Date(agent.shared_metadata.shared_at).toLocaleString('en-US', {
              month: 'long',
              day: 'numeric',
              year: 'numeric',
              hour: '2-digit',
              minute: '2-digit',
              hour12: true,
            })}
          </p>
        )}
      </div>
      <div className="mt-8">
        <p className="font-semibold text-[#212121] dark:text-[#E0E0E0]">
          Connected Tools
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          {agent.tools.map((tool, index) => (
            <span
              key={index}
              className="rounded-full bg-[#E0E0E0] px-3 py-1 text-xs font-light text-[#212121] dark:bg-[#4B5563] dark:text-[#E0E0E0]"
            >
              {tool}
            </span>
          ))}
        </div>
      </div>
      {/* <button className="mt-8 w-full rounded-xl bg-gradient-to-b from-violets-are-blue to-[#6e45c2] px-4 py-2 text-sm text-white shadow-lg transition duration-300 ease-in-out hover:shadow-xl">
        Start using
      </button> */}
    </div>
  );
}
