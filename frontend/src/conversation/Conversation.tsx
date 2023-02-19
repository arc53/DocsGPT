import { useSelector } from 'react-redux';
import Hero from '../Hero';
import ConversationBubble from './ConversationBubble';
import ConversationInput from './ConversationInput';
import { selectConversation } from './conversationSlice';

export default function Conversation() {
  const messages = useSelector(selectConversation);
  return (
    <div className="flex justify-center p-6">
      <div className="w-10/12 transition-all md:w-1/2">
        {messages.map((message, index) => {
          return (
            <ConversationBubble
              className="mt-5"
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
