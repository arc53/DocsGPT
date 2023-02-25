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

  useEffect(() =>
    endMessageRef?.current?.scrollIntoView({ behavior: 'smooth' }),
  );

  const handleQuestion = (question: string) => {
    dispatch(addMessage({ text: question, type: 'QUESTION' }));
    dispatch(fetchAnswer({ question }));
  };

  return (
    <div className="flex justify-center p-6">
      <div className="w-10/12 transition-all md:w-1/2">
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
      <div className="fixed bottom-14 flex w-10/12 md:bottom-12 md:w-[50%]">
        <div
          ref={inputRef}
          contentEditable
          className={`border-000000 overflow-x-hidden; max-h-24 min-h-[2.6rem] w-full overflow-y-auto whitespace-pre-wrap rounded-xl border bg-white p-2 pr-9 opacity-100 focus:border-2 focus:outline-none`}
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
            className="relative right-9 animate-spin cursor-pointer"
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
            className="relative right-9 cursor-pointer"
          ></img>
        )}
      </div>
      <p className="fixed bottom-6 w-10/12 text-center text-xs text-gray-2000">
        This is a chatbot that uses the GPT-3, Faiss and LangChain to answer
        questions.
      </p>
    </div>
  );
}
