import { Query } from './conversationModels';
import { Fragment, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';

import conversationService from '../api/services/conversationService';
import ConversationBubble from './ConversationBubble';
import Send from '../assets/send.svg';
import Spinner from '../assets/spinner.svg';
import {
  selectClientAPIKey,
  setClientApiKey,
  updateQuery,
  addQuery,
  fetchSharedAnswer,
  selectStatus,
} from './sharedConversationSlice';
import { setIdentifier, setFetchedData } from './sharedConversationSlice';

import { useDispatch } from 'react-redux';
import { AppDispatch } from '../store';

import {
  selectDate,
  selectTitle,
  selectQueries,
} from './sharedConversationSlice';
import { useSelector } from 'react-redux';
const apiHost = import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';

export const SharedConversation = () => {
  const navigate = useNavigate();
  const { identifier } = useParams(); //identifier is a uuid, not conversationId

  const queries = useSelector(selectQueries);
  const title = useSelector(selectTitle);
  const date = useSelector(selectDate);
  const apiKey = useSelector(selectClientAPIKey);
  const status = useSelector(selectStatus);

  const inputRef = useRef<HTMLDivElement>(null);
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();

  const [lastQueryReturnedErr, setLastQueryReturnedErr] = useState(false);
  const [eventInterrupt, setEventInterrupt] = useState(false);
  const endMessageRef = useRef<HTMLDivElement>(null);
  const handleUserInterruption = () => {
    if (!eventInterrupt && status === 'loading') setEventInterrupt(true);
  };
  useEffect(() => {
    !eventInterrupt && scrollIntoView();
  }, [queries.length, queries[queries.length - 1]]);

  useEffect(() => {
    identifier && dispatch(setIdentifier(identifier));
    const element = document.getElementById('inputbox') as HTMLInputElement;
    if (element) {
      element.focus();
    }
  }, []);

  function formatISODate(isoDateStr: string) {
    const date = new Date(isoDateStr);

    const monthNames = [
      'Jan',
      'Feb',
      'Mar',
      'Apr',
      'May',
      'June',
      'July',
      'Aug',
      'Sept',
      'Oct',
      'Nov',
      'Dec',
    ];

    const month = monthNames[date.getMonth()];
    const day = date.getDate();
    const year = date.getFullYear();

    let hours = date.getHours();
    const minutes = date.getMinutes();
    const ampm = hours >= 12 ? 'PM' : 'AM';

    hours = hours % 12;
    hours = hours ? hours : 12;
    const minutesStr = minutes < 10 ? '0' + minutes : minutes;
    const formattedDate = `Published ${month} ${day}, ${year} at ${hours}:${minutesStr} ${ampm}`;
    return formattedDate;
  }
  useEffect(() => {
    if (queries.length) {
      queries[queries.length - 1].error && setLastQueryReturnedErr(true);
      queries[queries.length - 1].response && setLastQueryReturnedErr(false); //considering a query that initially returned error can later include a response property on retry
    }
  }, [queries[queries.length - 1]]);

  const scrollIntoView = () => {
    endMessageRef?.current?.scrollIntoView({
      behavior: 'smooth',
      block: 'start',
    });
  };

  const fetchQueries = () => {
    identifier &&
      conversationService
        .getSharedConversation(identifier || '')
        .then((res) => {
          if (res.status === 404 || res.status === 400)
            navigate('/pagenotfound');
          return res.json();
        })
        .then((data) => {
          if (data.success) {
            dispatch(
              setFetchedData({
                queries: data.queries,
                title: data.title,
                date: data.date,
                identifier,
              }),
            );
            data.api_key && dispatch(setClientApiKey(data.api_key));
          }
        });
  };
  const handlePaste = (e: React.ClipboardEvent) => {
    e.preventDefault();
    const text = e.clipboardData.getData('text/plain');
    inputRef.current && (inputRef.current.innerText = text);
  };
  const prepResponseView = (query: Query, index: number) => {
    let responseView;
    if (query.response) {
      responseView = (
        <ConversationBubble
          ref={endMessageRef}
          className={`${index === queries.length - 1 ? 'mb-32' : 'mb-7'}`}
          key={`${index}ANSWER`}
          message={query.response}
          type={'ANSWER'}
          sources={query.sources ?? []}
        ></ConversationBubble>
      );
    } else if (query.error) {
      responseView = (
        <ConversationBubble
          ref={endMessageRef}
          className={`${index === queries.length - 1 ? 'mb-32' : 'mb-7'} `}
          key={`${index}ERROR`}
          message={query.error}
          type="ERROR"
        ></ConversationBubble>
      );
    }
    return responseView;
  };
  const handleQuestionSubmission = () => {
    if (inputRef.current?.textContent && status !== 'loading') {
      if (lastQueryReturnedErr) {
        // update last failed query with new prompt
        dispatch(
          updateQuery({
            index: queries.length - 1,
            query: {
              prompt: inputRef.current.textContent,
            },
          }),
        );
        handleQuestion({
          question: queries[queries.length - 1].prompt,
          isRetry: true,
        });
      } else {
        handleQuestion({ question: inputRef.current.textContent });
      }
      inputRef.current.textContent = '';
    }
  };

  const handleQuestion = ({
    question,
    isRetry = false,
  }: {
    question: string;
    isRetry?: boolean;
  }) => {
    question = question.trim();
    if (question === '') return;
    setEventInterrupt(false);
    !isRetry && dispatch(addQuery({ prompt: question })); //dispatch only new queries
    dispatch(fetchSharedAnswer({ question }));
  };
  useEffect(() => {
    fetchQueries();
  }, []);

  return (
    <div className="flex h-full flex-col items-center justify-between gap-2 overflow-y-hidden dark:bg-raisin-black">
      <div className="flex w-full justify-center overflow-auto">
        <div className="mt-0 w-11/12 md:w-10/12 lg:w-6/12">
          <div className="mb-2 w-full border-b pb-2 dark:border-b-silver">
            <h1 className="font-semi-bold text-4xl text-chinese-black dark:text-chinese-silver">
              {title}
            </h1>
            <h2 className="font-semi-bold text-base text-chinese-black dark:text-chinese-silver">
              {t('sharedConv.subtitle')}{' '}
              <a href="/" className="text-[#007DFF]">
                DocsGPT
              </a>
            </h2>
            <h2 className="font-semi-bold text-base text-chinese-black dark:text-chinese-silver">
              {date}
            </h2>
          </div>
          <div className="">
            {queries?.map((query, index) => {
              return (
                <Fragment key={index}>
                  <ConversationBubble
                    ref={endMessageRef}
                    className={'mb-1 last:mb-28 md:mb-7'}
                    key={`${index}QUESTION`}
                    message={query.prompt}
                    type="QUESTION"
                    sources={query.sources}
                  ></ConversationBubble>

                  {prepResponseView(query, index)}
                </Fragment>
              );
            })}
          </div>
        </div>
      </div>

      <div className=" flex w-11/12 flex-col items-center gap-4 pb-2 md:w-10/12 lg:w-6/12">
        {apiKey ? (
          <div className="flex h-full w-full items-center rounded-[40px] border border-silver bg-white py-1 dark:bg-raisin-black">
            <div
              id="inputbox"
              ref={inputRef}
              tabIndex={1}
              onPaste={handlePaste}
              placeholder={t('inputPlaceholder')}
              contentEditable
              className={`inputbox-style max-h-24 w-full overflow-y-auto overflow-x-hidden whitespace-pre-wrap rounded-full bg-white pt-5 pb-[22px] text-base leading-tight opacity-100 focus:outline-none dark:bg-raisin-black dark:text-bright-gray`}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleQuestionSubmission();
                }
              }}
            ></div>
            {status === 'loading' ? (
              <img
                src={Spinner}
                className="relative right-[38px] bottom-[24px] -mr-[30px] animate-spin cursor-pointer self-end bg-transparent filter dark:invert"
              ></img>
            ) : (
              <div className="mx-1 cursor-pointer rounded-full p-3 text-center hover:bg-gray-3000 dark:hover:bg-dark-charcoal">
                <img
                  onClick={handleQuestionSubmission}
                  className="ml-[4px] h-6 w-6 text-white filter dark:invert"
                  src={Send}
                ></img>
              </div>
            )}
          </div>
        ) : (
          <button
            onClick={() => navigate('/')}
            className="w-fit rounded-full bg-purple-30 p-4 text-white shadow-xl transition-colors duration-200 hover:bg-purple-taupe"
          >
            {t('sharedConv.button')}
          </button>
        )}
        <span className="mb-2 hidden text-xs text-dark-charcoal dark:text-silver sm:inline">
          {t('sharedConv.meta')}
        </span>
      </div>
    </div>
  );
};
