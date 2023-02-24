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
              className="mb-7"
              key={index}
              message={message.text}
              type={message.type}
            ></ConversationBubble>
          );
        })}
        {messages.length === 0 && <Hero className="mt-24 md:mt-36"></Hero>}
      </div>
      <div className="fixed bottom-2 flex w-10/12 md:w-[50%]">
        <div
          ref={inputRef}
          contentEditable
          className={`min-h-5 border-000000 overflow-x-hidden; max-h-24 w-full overflow-y-auto rounded-xl border bg-white p-2 pr-9 opacity-100 focus:border-2 focus:outline-none`}
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
    </div>
  );
}
