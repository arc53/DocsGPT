import Avatar from '../Avatar';
import { User } from '../models/misc';
import { MESSAGE_TYPE } from './conversationModels';

export default function ConversationBubble({
  message,
  type,
  className,
}: {
  message: string;
  type: MESSAGE_TYPE;
  className: string;
}) {
  return (
    <div
      className={`flex rounded-3xl ${
        type === 'QUESTION' ? '' : 'bg-gray-1000'
      } py-7 px-5 ${className}`}
    >
      <Avatar avatar={type === 'QUESTION' ? '👤' : '🦖'}></Avatar>
      <p className="ml-5">{message}</p>
    </div>
  );
}
