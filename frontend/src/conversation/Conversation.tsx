import { useEffect, useRef } from 'react';
import { useSelector } from 'react-redux';
import Hero from '../Hero';
import ConversationBubble from './ConversationBubble';
import ConversationInput from './ConversationInput';
import { selectConversation } from './conversationSlice';

export default function Conversation() {
  const messages = useSelector(selectConversation);
  const endMessageRef = useRef<HTMLDivElement>(null);

  useEffect(() => endMessageRef?.current?.scrollIntoView());

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
        {messages.length === 0 && <Hero className="mt-24"></Hero>}
      </div>
      <ConversationInput className="fixed bottom-2 w-10/12 md:w-[50%]"></ConversationInput>
    </div>
  );
}
