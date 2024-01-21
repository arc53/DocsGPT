import { forwardRef, useState } from 'react';
import Avatar from '../components/Avatar';
import remarkGfm from 'remark-gfm';
import { FEEDBACK, MESSAGE_TYPE } from './conversationModels';
import classes from './ConversationBubble.module.css';
import Alert from './../assets/alert.svg';
import { ReactComponent as Like } from './../assets/like.svg';
import { ReactComponent as Dislike } from './../assets/dislike.svg';
import { ReactComponent as Copy } from './../assets/copy.svg';
import { ReactComponent as CheckMark } from './../assets/checkmark.svg';
import ReactMarkdown from 'react-markdown';
import copy from 'copy-to-clipboard';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/cjs/styles/prism';
import DocsGPT3 from '../assets/cute_docsgpt3.svg';

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
    }, 3000);
  };
  const [isCopyHovered, setIsCopyHovered] = useState(false);
  const [isLikeHovered, setIsLikeHovered] = useState(false);
  const [isDislikeHovered, setIsDislikeHovered] = useState(false);
  const [isLikeClicked, setIsLikeClicked] = useState(false);
  const [isDislikeClicked, setIsDislikeClicked] = useState(false);

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
      <div
        ref={ref}
        className={`flex self-start ${className} group flex-col pr-20  dark:text-bright-gray`}
      >
        <div className="flex self-start">
          <Avatar
            className="mt-2 h-12 w-12 text-2xl"
            avatar={
              <img
                src={DocsGPT3}
                alt="DocsGPT"
                className="h-full w-full object-cover"
              />
            }
          />

          <div
            className={`ml-2 mr-5 flex rounded-3xl bg-gray-1000 dark:bg-gun-metal p-3.5 ${
              type === 'ERROR'
                ? 'flex-row items-center rounded-full border border-transparent bg-[#FFE7E7] p-2 py-5 text-sm font-normal text-red-3000  dark:border-red-2000 dark:text-white'
                : 'flex-col rounded-3xl'
            }`}
          >
            {type === 'ERROR' && (
              <img src={Alert} alt="alert" className="mr-2 inline" />
            )}
            <ReactMarkdown
              className="max-w-screen-md whitespace-pre-wrap break-words"
              remarkPlugins={[remarkGfm]}
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
                ul({ children }) {
                  return (
                    <ul
                      className={`list-inside list-disc whitespace-normal pl-4 ${classes.list}`}
                    >
                      {children}
                    </ul>
                  );
                },
                ol({ children }) {
                  return (
                    <ol
                      className={`list-inside list-decimal whitespace-normal pl-4 ${classes.list}`}
                    >
                      {children}
                    </ol>
                  );
                },
                table({ children }) {
                  return (
                    <div className="relative overflow-x-auto rounded-lg border">
                      <table className="w-full text-left text-sm text-gray-700">
                        {children}
                      </table>
                    </div>
                  );
                },
                thead({ children }) {
                  return (
                    <thead className="text-xs uppercase text-gray-900 [&>.table-row]:bg-gray-50">
                      {children}
                    </thead>
                  );
                },
                tr({ children }) {
                  return (
                    <tr className="table-row border-b odd:bg-white even:bg-gray-50">
                      {children}
                    </tr>
                  );
                },
                td({ children }) {
                  return <td className="px-6 py-3">{children}</td>;
                },
                th({ children }) {
                  return <th className="px-6 py-3">{children}</th>;
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
            className={`relative mr-5 flex items-center justify-center md:invisible ${
              type !== 'ERROR' ? 'group-hover:md:visible' : ''
            }`}
          >
            <div className="absolute left-2 top-4">
              <div
                className="flex items-center justify-center rounded-full p-2"
                style={{
                  backgroundColor: isCopyHovered ? '#EEEEEE' : '#ffffff',
                }}
              >
                {copied ? (
                  <CheckMark
                    className="cursor-pointer stroke-green-2000"
                    onMouseEnter={() => setIsCopyHovered(true)}
                    onMouseLeave={() => setIsCopyHovered(false)}
                  />
                ) : (
                  <Copy
                    className={`cursor-pointer fill-none`}
                    onClick={() => {
                      handleCopyClick(message);
                    }}
                    onMouseEnter={() => setIsCopyHovered(true)}
                    onMouseLeave={() => setIsCopyHovered(false)}
                  ></Copy>
                )}
              </div>
            </div>
          </div>
          <div
            className={`relative mr-5 flex items-center justify-center ${
              !isLikeClicked ? 'md:invisible' : ''
            } ${
              feedback === 'LIKE' || type !== 'ERROR'
                ? 'group-hover:md:visible'
                : ''
            }`}
          >
            <div className="absolute left-6 top-4">
              <div
                className="flex items-center justify-center rounded-full p-2 dark:bg-transparent"
                style={{
                  backgroundColor: isLikeHovered
                    ? isLikeClicked
                      ? 'rgba(125, 84, 209, 0.3)'
                      : '#EEEEEE'
                    : isLikeClicked
                    ? 'rgba(125, 84, 209, 0.3)'
                    : '#ffffff',
                }}
              >
                <Like
                  className={`cursor-pointer ${
                    isLikeClicked || feedback === 'LIKE'
                      ? 'fill-white-3000 stroke-purple-30'
                      : 'fill-none  stroke-gray-4000'
                  }`}
                  onClick={() => {
                    handleFeedback?.('LIKE');
                    setIsLikeClicked(true);
                    setIsDislikeClicked(false);
                  }}
                  onMouseEnter={() => setIsLikeHovered(true)}
                  onMouseLeave={() => setIsLikeHovered(false)}
                ></Like>
              </div>
            </div>
          </div>
          <div
            className={`mr-13 relative flex items-center justify-center ${
              !isDislikeClicked ? 'md:invisible' : ''
            } ${
              feedback === 'DISLIKE' || type !== 'ERROR'
                ? 'group-hover:md:visible'
                : ''
            }`}
          >
            <div className="absolute left-10 top-4">
              <div
                className="flex items-center justify-center rounded-full p-2"
                style={{
                  backgroundColor: isDislikeHovered
                    ? isDislikeClicked
                      ? 'rgba(248, 113, 113, 0.3)'
                      : '#EEEEEE'
                    : isDislikeClicked
                    ? 'rgba(248, 113, 113, 0.3)'
                    : '#ffffff',
                }}
              >
                <Dislike
                  className={`cursor-pointer ${
                    isDislikeClicked || feedback === 'DISLIKE'
                      ? 'fill-white-3000 stroke-red-2000'
                      : 'fill-none  stroke-gray-4000'
                  }`}
                  onClick={() => {
                    handleFeedback?.('DISLIKE');
                    setIsDislikeClicked(true);
                    setIsLikeClicked(false);
                  }}
                  onMouseEnter={() => setIsDislikeHovered(true)}
                  onMouseLeave={() => setIsDislikeHovered(false)}
                ></Dislike>
              </div>
            </div>
          </div>
        </div>

        {sources && openSource !== null && sources[openSource] && (
          <div className="ml-10 mt-2 max-w-[800px] rounded-xl bg-blue-200 dark:bg-gun-metal p-2">
            <p className="m-1 w-3/4 truncate text-xs text-gray-500 dark:text-bright-gray">
              Source: {sources[openSource].title}
            </p>

            <div className="m-2 rounded-xl border-2 border-gray-200 dark:border-chinese-silver bg-white dark:bg-dark-charcoal p-2">
              <p className="text-break text-black dark:text-bright-gray">
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
