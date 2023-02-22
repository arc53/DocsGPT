import { forwardRef } from 'react';
import Avatar from '../Avatar';
import { MESSAGE_TYPE } from './conversationModels';
import Alert from './../assets/alert.svg';

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
        type === 'ANSWER'
          ? 'bg-gray-1000'
          : type === 'ERROR'
          ? 'bg-red-1000'
          : ''
      } py-7 px-5 ${className}`}
    >
      <Avatar avatar={type === 'QUESTION' ? '👤' : '🦖'}></Avatar>
      <div
        className={`ml-5 flex items-center ${
          type === 'ERROR'
            ? 'rounded-lg border border-red-2000 p-2 text-red-3000'
            : ''
        }`}
      >
        {type === 'ERROR' && (
          <img src={Alert} alt="alert" className="mr-2 inline" />
        )}
        <span>{message}</span>
      </div>
    </div>
  );
});

export default ConversationBubble;
