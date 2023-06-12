import { forwardRef, useState } from 'react';
import Avatar from '../Avatar';
import { FEEDBACK, MESSAGE_TYPE } from './conversationModels';
import Alert from './../assets/alert.svg';
import { ReactComponent as Like } from './../assets/like.svg';
import { ReactComponent as Dislike } from './../assets/dislike.svg';
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/cjs/styles/prism';

const DisableSourceFE = import.meta.env.VITE_DISABLE_SOURCE_FE || false;

const ConversationBubble = forwardRef<
  HTMLDivElement,
  {
    message: string;
    type: MESSAGE_TYPE;
    className?: string;
    feedback?: FEEDBACK;
    handleFeedback?: (feedback: FEEDBACK) => void;
    sources?: { title: string; text: string }[];
  }
>(function ConversationBubble(
  { message, type, className, feedback, handleFeedback, sources },
  ref,
) {
  const [showFeedback, setShowFeedback] = useState(false);
  const [openSource, setOpenSource] = useState<number | null>(null);
  const List = ({
    ordered,
    children,
  }: {
    ordered?: boolean;
    children: React.ReactNode;
  }) => {
    const Tag = ordered ? 'ol' : 'ul';
    return <Tag className="list-inside list-disc">{children}</Tag>;
  };
  let bubble;

  if (type === 'QUESTION') {
    bubble = (
      <div ref={ref} className={`flex flex-row-reverse self-end ${className}`}>
        <Avatar className="mt-2 text-2xl" avatar="🧑‍💻"></Avatar>
        <div className="mr-2 ml-10 flex items-center rounded-3xl bg-blue-1000 p-3.5 text-white">
          <ReactMarkdown className="whitespace-pre-wrap break-words">
            {message}
          </ReactMarkdown>
        </div>
      </div>
    );
  } else {
    bubble = (
      <div
        ref={ref}
        className={`flex self-start ${className} flex-col`}
        onMouseEnter={() => setShowFeedback(true)}
        onMouseLeave={() => setShowFeedback(false)}
      >
        <div className="flex self-start">
          <Avatar className="mt-2 text-2xl" avatar="🦖"></Avatar>
          <div
            className={`ml-2 mr-5 flex items-center rounded-3xl bg-gray-1000 p-3.5 ${
              type === 'ERROR'
                ? ' rounded-lg border border-red-2000 bg-red-1000 p-2 text-red-3000'
                : ''
            }`}
          >
            {type === 'ERROR' && (
              <img src={Alert} alt="alert" className="mr-2 inline" />
            )}
            <ReactMarkdown
              className="whitespace-pre-wrap break-words"
              components={{
                code({ node, inline, className, children, ...props }) {
                  const match = /language-(\w+)/.exec(className || '');

                  return !inline && match ? (
                    <SyntaxHighlighter
                      PreTag="div"
                      language={match[1]}
                      {...props}
                      style={vscDarkPlus}
                    >
                      {String(children).replace(/\n$/, '')}
                    </SyntaxHighlighter>
                  ) : (
                    <code className={className ? className : ''} {...props}>
                      {children}
                    </code>
                  );
                },
                ul({ node, children }) {
                  return <List>{children}</List>;
                },
                ol({ node, children }) {
                  return <List ordered>{children}</List>;
                },
              }}
            >
              {message}
            </ReactMarkdown>
          </div>
          <div
            className={`mr-2 flex items-center justify-center ${
              feedback === 'LIKE' || (type !== 'ERROR' && showFeedback)
                ? ''
                : 'md:invisible'
            }`}
          >
            <Like
              className={`cursor-pointer ${
                feedback === 'LIKE'
                  ? 'fill-blue-1000 stroke-blue-1000'
                  : 'fill-none  stroke-gray-4000 hover:fill-gray-4000'
              }`}
              onClick={() => handleFeedback?.('LIKE')}
            ></Like>
          </div>
          <div
            className={`mr-10 flex items-center justify-center ${
              feedback === 'DISLIKE' || (type !== 'ERROR' && showFeedback)
                ? ''
                : 'md:invisible'
            }`}
          >
            <Dislike
              className={`cursor-pointer ${
                feedback === 'DISLIKE'
                  ? 'fill-red-2000 stroke-red-2000'
                  : 'fill-none  stroke-gray-4000 hover:fill-gray-4000'
              }`}
              onClick={() => handleFeedback?.('DISLIKE')}
            ></Dislike>
          </div>
        </div>
        <div className="ml-8 mt-2 grid w-1/2 grid-cols-3 gap-2">
          {DisableSourceFE
            ? null
            : sources?.map((source, index) => (
                <div
                  key={index}
                  className="w-26 cursor-pointer rounded-xl border border-gray-200 py-1 px-2 hover:bg-gray-100"
                  onClick={() =>
                    setOpenSource(openSource === index ? null : index)
                  }
                >
                  <p className="truncate text-xs text-gray-500">
                    {index + 1}. {source.title}
                  </p>
                </div>
              ))}
        </div>

        {sources && openSource !== null && sources[openSource] && (
          <div className="ml-8 mt-2 w-3/4 rounded-xl bg-blue-200 p-2">
            <p className="w-3/4 truncate text-xs text-gray-500">
              Source: {sources[openSource].title}
            </p>

            <div className="rounded-xl border-2 border-gray-200 bg-white p-2">
              <p className="text-xs text-gray-500 ">
                {sources[openSource].text}
              </p>
            </div>
          </div>
        )}
      </div>
    );
  }
  return bubble;
});

export default ConversationBubble;
