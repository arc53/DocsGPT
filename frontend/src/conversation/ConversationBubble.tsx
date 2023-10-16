import { forwardRef, useState } from 'react';
import Avatar from '../Avatar';
import { FEEDBACK, MESSAGE_TYPE } from './conversationModels';
import Alert from './../assets/alert.svg';
import { ReactComponent as Like } from './../assets/like.svg';
import { ReactComponent as Dislike } from './../assets/dislike.svg';
import { ReactComponent as Copy } from './../assets/copy.svg';
import { ReactComponent as Checkmark } from './../assets/checkmark.svg';
import ReactMarkdown from 'react-markdown';
import copy from 'copy-to-clipboard';
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
  const [openSource, setOpenSource] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);

  const handleCopyClick = (text: string) => {
    copy(text);
    setCopied(true);
    // Reset copied to false after a few seconds
    setTimeout(() => {
      setCopied(false);
    }, 2000);
  };

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
        <div className="mr-2 ml-10 flex items-center rounded-3xl bg-purple-30 p-3.5 text-white">
          <ReactMarkdown className="whitespace-pre-wrap break-all">
            {message}
          </ReactMarkdown>
        </div>
      </div>
    );
  } else {
    bubble = (
      <div ref={ref} className={`flex self-start ${className} group flex-col`}>
        <div className="flex self-start">
          <Avatar className="mt-2 text-2xl" avatar="🦖"></Avatar>
          <div
            className={`ml-2 mr-5 flex flex-col rounded-3xl bg-gray-1000 p-3.5 ${
              type === 'ERROR'
                ? 'flex-row rounded-full border border-transparent bg-[#FFE7E7] p-2 py-5 text-sm font-normal text-red-3000  dark:border-red-2000 dark:text-white'
                : 'flex-col rounded-3xl'
            }`}
          >
            {type === 'ERROR' && (
              <img src={Alert} alt="alert" className="mr-2 inline" />
            )}
            <ReactMarkdown
              className="max-w-screen-md whitespace-pre-wrap break-words"
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
            {DisableSourceFE || type === 'ERROR' ? null : (
              <>
                <span className="mt-3 h-px w-full bg-[#DEDEDE]"></span>
                <div className="mt-3 flex w-full flex-row flex-wrap items-center justify-start gap-2">
                  <div className="py-1 text-base font-semibold">Sources:</div>
                  <div className="flex flex-row flex-wrap items-center justify-start gap-2">
                    {sources?.map((source, index) => (
                      <div
                        key={index}
                        className={`max-w-fit cursor-pointer rounded-[28px] py-1 px-4 ${
                          openSource === index
                            ? 'bg-[#007DFF]'
                            : 'bg-[#D7EBFD] hover:bg-[#BFE1FF]'
                        }`}
                        onClick={() =>
                          setOpenSource(openSource === index ? null : index)
                        }
                      >
                        <p
                          className={`truncate text-center text-base font-medium ${
                            openSource === index
                              ? 'text-white'
                              : 'text-[#007DFF]'
                          }`}
                        >
                          {index + 1}. {source.title.substring(0, 45)}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>
          <div
            className={`relative mr-2 flex items-center justify-center md:invisible ${
              type !== 'ERROR' ? 'group-hover:md:visible' : ''
            }`}
          >
            {copied ? (
              <Checkmark className="absolute left-2 top-4" />
            ) : (
              <Copy
                className={`absolute left-2 top-4 cursor-pointer fill-gray-4000 hover:stroke-gray-4000`}
                onClick={() => {
                  handleCopyClick(message);
                }}
              ></Copy>
            )}
          </div>
          <div
            className={`relative mr-2 flex items-center justify-center md:invisible ${
              feedback === 'LIKE' || type !== 'ERROR'
                ? 'group-hover:md:visible'
                : ''
            }`}
          >
            <Like
              className={`absolute left-6  top-4 cursor-pointer ${
                feedback === 'LIKE'
                  ? 'fill-purple-30 stroke-purple-30'
                  : 'fill-none  stroke-gray-4000 hover:fill-gray-4000'
              }`}
              onClick={() => handleFeedback?.('LIKE')}
            ></Like>
          </div>
          <div
            className={`relative mr-10 flex items-center justify-center md:invisible ${
              feedback === 'DISLIKE' || type !== 'ERROR'
                ? 'group-hover:md:visible'
                : ''
            }`}
          >
            <Dislike
              className={`absolute left-10 top-4 cursor-pointer ${
                feedback === 'DISLIKE'
                  ? 'fill-red-2000 stroke-red-2000'
                  : 'fill-none  stroke-gray-4000 hover:fill-gray-4000'
              }`}
              onClick={() => handleFeedback?.('DISLIKE')}
            ></Dislike>
          </div>
        </div>

        {sources && openSource !== null && sources[openSource] && (
          <div className="ml-10 mt-2 max-w-[800px] rounded-xl bg-blue-200 p-2">
            <p className="m-1 w-3/4 truncate text-xs text-gray-500">
              Source: {sources[openSource].title}
            </p>

            <div className="m-2 rounded-xl border-2 border-gray-200 bg-white p-2">
              <p className="text-black">{sources[openSource].text}</p>
            </div>
          </div>
        )}
      </div>
    );
  }
  return bubble;
});

export default ConversationBubble;
