import Avatar from '../Avatar';
import { User } from '../models/misc';

export default function ConversationBubble({
  user,
  message,
  isCurrentUser,
  className,
}: {
  user: User;
  message: string;
  isCurrentUser: boolean;
  className: string;
}) {
  return (
    <div
      className={`flex rounded-3xl ${
        isCurrentUser ? '' : 'bg-gray-1000'
      } py-7 px-5 ${className}`}
    >
      <Avatar avatar={user.avatar}></Avatar>
      <p className="ml-5">{message}</p>
    </div>
  );
}
