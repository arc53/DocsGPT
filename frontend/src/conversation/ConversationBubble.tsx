import { forwardRef } from 'react';
import Avatar from '../Avatar';
import { MESSAGE_TYPE } from './conversationModels';

const ConversationBubble = forwardRef<
  HTMLDivElement,
  {
    message: string;
    type: MESSAGE_TYPE;
    className: string;
  }
>(function ConversationBubble({ message, type, className }, ref) {
  return (
    <div
      ref={ref}
      className={`flex rounded-3xl ${
        type === 'QUESTION' ? '' : 'bg-gray-1000'
      } py-7 px-5 ${className}`}
    >
      <Avatar avatar={type === 'QUESTION' ? '👤' : '🦖'}></Avatar>
      <p className="ml-5">{message}</p>
    </div>
  );
});

export default ConversationBubble;
