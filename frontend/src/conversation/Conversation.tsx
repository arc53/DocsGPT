import { Fragment, useEffect, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useDarkTheme } from '../hooks';
import Hero from '../Hero';
import { AppDispatch } from '../store';
import ConversationBubble from './ConversationBubble';
import {
  addQuery,
  fetchAnswer,
  selectQueries,
  selectStatus,
  updateQuery,
} from './conversationSlice';
import Send from './../assets/send.svg';
import SendDark from './../assets/send_dark.svg';
import Spinner from './../assets/spinner.svg';
import { FEEDBACK, Query } from './conversationModels';
import { sendFeedback } from './conversationApi';
import ArrowDown from './../assets/arrow-down.svg';
export default function Conversation() {
  const queries = useSelector(selectQueries);
  const status = useSelector(selectStatus);
  const dispatch = useDispatch<AppDispatch>();
  const endMessageRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLDivElement>(null);
  const [isDarkTheme] = useDarkTheme();
  const [hasScrolledToLast, setHasScrolledToLast] = useState(true);
  const fetchStream = useRef<any>(null);
  const [eventInterrupt, setEventInterrupt] = useState(false);

  const handleUserInterruption = () => {
    if (!eventInterrupt && status === 'loading') setEventInterrupt(true);
  };
  useEffect(() => {
    !eventInterrupt && scrollIntoView();
  }, [queries.length, queries[queries.length - 1]]);

  useEffect(() => {
    const element = document.getElementById('inputbox') as HTMLInputElement;
    if (element) {
      element.focus();
    }
  }, []);

  useEffect(() => {
    return () => {
      if (status !== 'idle') {
        fetchStream.current && fetchStream.current.abort(); //abort previous stream
      }
    };
  }, [status]);

  useEffect(() => {
    const observerCallback: IntersectionObserverCallback = (entries) => {
      entries.forEach((entry) => {
        setHasScrolledToLast(entry.isIntersecting);
      });
    };
 
    const observer = new IntersectionObserver(observerCallback, {
      root: null,
      threshold: [1, 0.8],
    });
    if (endMessageRef.current) {
      observer.observe(endMessageRef.current);
    }

    return () => {
      observer.disconnect();
    };
  }, [endMessageRef.current]);

  const scrollIntoView = () => {
    endMessageRef?.current?.scrollIntoView({
      behavior: 'smooth',
      block: 'start',
    });
  };

  const handleQuestion = (question: string) => {
    question = question.trim();
    if (question === '') return;
    setEventInterrupt(false);
    dispatch(addQuery({ prompt: question }));
    fetchStream.current = dispatch(fetchAnswer({ question }));
  };
  const handleFeedback = (query: Query, feedback: FEEDBACK, index: number) => {
    const prevFeedback = query.feedback;
    dispatch(updateQuery({ index, query: { feedback } }));
    sendFeedback(query.prompt, query.response!, feedback).catch(() =>
      dispatch(updateQuery({ index, query: { feedback: prevFeedback } })),
    );
  };

  const prepResponseView = (query: Query, index: number) => {
    let responseView;
    if (query.error) {
      responseView = (
        <ConversationBubble
          ref={endMessageRef}
          className={`${index === queries.length - 1 ? 'mb-32' : 'mb-7'}`}
          key={`${index}ERROR`}
          message={query.error}
          type="ERROR"
        ></ConversationBubble>
      );
    } else if (query.response) {
      responseView = (
        <ConversationBubble
          ref={endMessageRef}
          className={`${index === queries.length - 1 ? 'mb-32' : 'mb-7'}`}
          key={`${index}ANSWER`}
          message={query.response}
          type={'ANSWER'}
          sources={query.sources}
          feedback={query.feedback}
          handleFeedback={(feedback: FEEDBACK) =>
            handleFeedback(query, feedback, index)
          }
        ></ConversationBubble>
      );
    }
    return responseView;
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    e.preventDefault();
    const text = e.clipboardData.getData('text/plain');
    document.execCommand('insertText', false, text);
  };

  return (
    <div className='flex flex-col gap-1 h-screen'>
      <div
        onWheel={handleUserInterruption}
        onTouchMove={handleUserInterruption}
        className="flex w-full justify-center p-4 h-[87vh] overflow-y-auto"
      >
        {queries.length > 0 && !hasScrolledToLast && (
          <button
            onClick={scrollIntoView}
            aria-label="scroll to bottom"
            className="fixed bottom-32 right-14 z-10 flex h-7 w-7  items-center justify-center rounded-full border-[0.5px] border-gray-alpha bg-gray-100 bg-opacity-50 dark:bg-purple-taupe md:h-9 md:w-9 md:bg-opacity-100 "
          >
            <img
              src={ArrowDown}
              alt="arrow down"
              className="h-4 w-4 opacity-50 md:h-5 md:w-5"
            />
          </button>
        )}

        {queries.length > 0 && (
          <div className="w-full md:w-8/12 mt-16">
            {queries.map((query, index) => {
              return (
                <Fragment key={index}>
                  <ConversationBubble
                    className={'mb-1 md:mb-7 last:mb-28'}
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
        )}
        {queries.length === 0 && <Hero className="mt-24 md:mt-52"></Hero>}

      </div>
      <div className="bottom-0 flex flex-col items-end self-center bg-white pt-1 dark:bg-raisin-black md:fixed w-11/12 md:w-[60%]">
        <div className="flex h-full w-full">
          <div
            id="inputbox"
            ref={inputRef}
            tabIndex={1}
            placeholder="Type your message here..."
            contentEditable
            onPaste={handlePaste}
            className={`border-000000 max-h-24 min-h-[2.6rem] w-full overflow-y-auto overflow-x-hidden whitespace-pre-wrap rounded-3xl border bg-white py-2 pl-4 pr-9 text-base leading-7 opacity-100 focus:outline-none dark:bg-raisin-black dark:text-bright-gray`}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                if (inputRef.current?.textContent && status !== 'loading') {
                  handleQuestion(inputRef.current.textContent);
                  inputRef.current.textContent = '';
                }
              }
            }}
          ></div>
          {status === 'loading' ? (
            <img
              src={Spinner}
              className="relative right-[38px] bottom-[7px] -mr-[30px] animate-spin cursor-pointer self-end bg-transparent"
            ></img>
          ) : (
            <div className="relative right-[43px] bottom-[7px] -mr-[35px] h-[35px] w-[35px] cursor-pointer self-end rounded-full hover:bg-gray-3000">
              <img
                className="ml-[9px] mt-[9px] text-white"
                onClick={() => {
                  if (inputRef.current?.textContent) {
                    handleQuestion(inputRef.current.textContent);
                    inputRef.current.textContent = '';
                  }
                }}
                src={isDarkTheme ? SendDark : Send}
              ></img>
            </div>
          )}
        </div>
        <p className="hidden md:inline text-gray-595959 w-[100vw] self-center bg-white bg-transparent p-5 text-center text-xs dark:bg-raisin-black dark:text-bright-gray md:w-full">
          DocsGPT uses GenAI, please review critial information using sources.
        </p>
      </div>
    </div>
  );
}
