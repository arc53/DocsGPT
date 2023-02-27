import { useEffect, useRef } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import Hero from '../Hero';
import { AppDispatch } from '../store';
import ConversationBubble from './ConversationBubble';
import {
  addMessage,
  fetchAnswer,
  selectConversation,
  selectStatus,
} from './conversationSlice';
import Send from './../assets/send.svg';
import Spinner from './../assets/spinner.svg';

export default function Conversation() {
  const messages = useSelector(selectConversation);
  const status = useSelector(selectStatus);
  const dispatch = useDispatch<AppDispatch>();
  const endMessageRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLDivElement>(null);

  useEffect(
    () => endMessageRef?.current?.scrollIntoView({ behavior: 'smooth' }),
    [messages],
  );

  const handleQuestion = (question: string) => {
    dispatch(addMessage({ text: question, type: 'QUESTION' }));
    dispatch(fetchAnswer({ question }));
  };

  return (
    <div className="flex justify-center p-6">
      <div className="mt-20 flex w-10/12 flex-col transition-all md:w-1/2">
        {messages.map((message, index) => {
          return (
            <ConversationBubble
              ref={index === messages.length - 1 ? endMessageRef : null}
              className={`${index === messages.length - 1 ? 'mb-20' : 'mb-7'}`}
              key={index}
              message={message.text}
              type={message.type}
            ></ConversationBubble>
          );
        })}
        {messages.length === 0 && <Hero className="mt-24 md:mt-52"></Hero>}
      </div>
      <div className="fixed bottom-6 flex w-10/12 flex-col items-end self-center md:w-[50%]">
        <div className="flex w-full">
          <div
            ref={inputRef}
            contentEditable
            className={`border-000000 overflow-x-hidden; max-h-24 min-h-[2.6rem] w-full overflow-y-auto whitespace-pre-wrap rounded-xl border bg-white py-2 pl-4 pr-9 leading-7 opacity-100 focus:outline-none`}
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
              className="relative right-[38px] bottom-[7px] -mr-[30px] animate-spin cursor-pointer self-end"
            ></img>
          ) : (
            <img
              onClick={() => {
                if (inputRef.current?.textContent) {
                  handleQuestion(inputRef.current.textContent);
                  inputRef.current.textContent = '';
                }
              }}
              src={Send}
              className="relative right-[35px] bottom-[15px] -mr-[21px] cursor-pointer self-end"
            ></img>
          )}
        </div>
        <p className="mt-3 w-10/12 self-center text-center text-xs text-gray-2000">
          This is a chatbot that uses the GPT-3, Faiss and LangChain to answer
          questions.
        </p>
      </div>
    </div>
  );
}
