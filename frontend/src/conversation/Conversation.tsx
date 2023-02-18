import ConversationBubble from './ConversationBubble';
import ConversationInput from './ConversationInput';

export default function Conversation() {
  // uncomment below JSX to see the sample harcoded chat box
  return (
    <div className="flex justify-center p-6">
      {/* <div className="w-10/12 transition-all md:w-1/2">
        {new Array(10).fill(1).map((item, index) => {
          return (
            <ConversationBubble
              className="mt-5"
              key={index}
              user={index % 2 === 0 ? { avatar: '🦖' } : { avatar: '👤' }}
              message={
                index % 2 === 0
                  ? 'A chatbot is a computer program that simulates human conversation through voice commands or text chats or both. It can be integrated with various messaging platforms like Facebook Messenger, WhatsApp, WeChat, etc.'
                  : 'what is DocsGPT'
              }
              isCurrentUser={index % 2 === 0 ? false : true}
            ></ConversationBubble>
          );
        })}
      </div>
      <ConversationInput className="fixed bottom-2 w-10/12 md:w-[50%]"></ConversationInput> */}
    </div>
  );
}
